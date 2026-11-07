#include "kernels.cuh"

namespace h4nb {

__global__ void predict_kernel(int n, const d4* __restrict__ x, const d4* __restrict__ v, const d4* __restrict__ a,
                               const d4* __restrict__ j, const int64_t* __restrict__ t, int64_t T, double tick,
                               d4* __restrict__ xp, d4* __restrict__ vp) {
  const int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= n) return;
  predict(x[i], v[i], a[i], j[i], double(T - t[i]) * tick, xp[i], vp[i]);
}

__global__ void gather_kernel(int na, const int* __restrict__ act, const d4* __restrict__ xp,
                              const d4* __restrict__ vp, int base, d4* __restrict__ tx, d4* __restrict__ tv,
                              int* __restrict__ tid) {
  const int k = blockIdx.x * blockDim.x + threadIdx.x;
  if (k >= na) return;
  const int i = act[k];
  tx[k] = xp[i];
  tv[k] = vp[i];
  tid[k] = base + i;
}

__global__ void force_kernel(int na, const d4* __restrict__ tx, const d4* __restrict__ tv,
                             const int* __restrict__ tid, int ns, const d4* __restrict__ sx,
                             const d4* __restrict__ sv, int sbase, int chunk, double eps2, d4* __restrict__ pa,
                             d4* __restrict__ pj) {
  __shared__ d4 shx[BI], shv[BI];
  const int i = blockIdx.x * BI + threadIdx.x;
  const int j0 = blockIdx.y * chunk, j1 = min(ns, j0 + chunk);
  d4 xi{0, 0, 0, 0}, vi{0, 0, 0, 0};
  int gi = -1;
  if (i < na) {
    xi = tx[i];
    vi = tv[i];
    gi = tid[i];
  }
  AJ f;
  for (int t0 = j0; t0 < j1; t0 += BI) {
    const int js = t0 + threadIdx.x;
    if (js < j1) {
      shx[threadIdx.x] = sx[js];
      shv[threadIdx.x] = sv[js];
    }
    __syncthreads();
    const int nt = min(BI, j1 - t0);
#pragma unroll 4
    for (int k = 0; k < nt; ++k)
      if (sbase + t0 + k != gi) accumulate(f, xi, vi, shx[k], shv[k], eps2);
    __syncthreads();
  }
  if (i < na) {
    const size_t o = size_t(blockIdx.y) * na + i;
    pa[o] = d4{f.ax, f.ay, f.az, f.r2min};
    pj[o] = d4{f.jx, f.jy, f.jz, 0.0};
  }
}

__global__ void sum_partials(int na, int nparts, const d4* __restrict__ pa, const d4* __restrict__ pj,
                             d4* __restrict__ fa, d4* __restrict__ fj) {
  const int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= na) return;
  d4 a = pa[i], j = pj[i];
  for (int y = 1; y < nparts; ++y) {
    const d4 b = pa[size_t(y) * na + i], c = pj[size_t(y) * na + i];
    a.x += b.x; a.y += b.y; a.z += b.z; a.w = fmin(a.w, b.w);
    j.x += c.x; j.y += c.y; j.z += c.z;
  }
  fa[i] = a;
  fj[i] = j;
}

__global__ void correct_kernel(int na, const int* __restrict__ act, const d4* __restrict__ fa,
                               const d4* __restrict__ fj, StepParams p, int center, d4* x, d4* v, d4* a, d4* j,
                               int64_t* t, int64_t* next, int* level, unsigned* status,
                               unsigned long long* minr2) {
  const int k = blockIdx.x * blockDim.x + threadIdx.x;
  if (k >= na) return;
  const int i = act[k];
  const d4 f = fa[k], g = fj[k];
  const d4 a1{p.G * f.x, p.G * f.y, p.G * f.z, 0.0};
  const d4 j1{p.G * g.x, p.G * g.y, p.G * g.z, 0.0};
  d4 xi = x[i], vi = v[i], ai = a[i], ji = j[i];
  int64_t ti = t[i], ni = 0;
  int li = level[i];
  const unsigned st = update_particle(p, i == center, a1, j1, f.w, xi, vi, ai, ji, ti, ni, li);
  x[i] = xi; v[i] = vi; a[i] = ai; j[i] = ji;
  t[i] = ti; next[i] = ni; level[i] = li;
  if (st) atomicOr(status, st);
  atomicMin(minr2, static_cast<unsigned long long>(__double_as_longlong(f.w)));
}

__global__ void potential_kernel(int n, const d4* __restrict__ xall, int ns, int sbase, int chunk, double eps2,
                                 double* __restrict__ pphi) {
  __shared__ d4 shx[BI];
  const int i = blockIdx.x * BI + threadIdx.x;
  const int j0 = blockIdx.y * chunk, j1 = min(ns, j0 + chunk);
  double phi = 0;
  if (sbase + j1 - 1 > int(blockIdx.x) * BI) {  // The block has at least one pair j > i. This holds for the whole block.
    const d4 xi = i < n ? xall[i] : d4{0, 0, 0, 0};
    for (int t0 = j0; t0 < j1; t0 += BI) {
      const int js = t0 + threadIdx.x;
      if (js < j1) shx[threadIdx.x] = xall[sbase + js];
      __syncthreads();
      const int nt = min(BI, j1 - t0);
      for (int k = 0; k < nt; ++k) {
        if (sbase + t0 + k > i) {
          const double dx = shx[k].x - xi.x, dy = shx[k].y - xi.y, dz = shx[k].z - xi.z;
          phi += shx[k].w * h4_rsqrt(dx * dx + dy * dy + dz * dz + eps2);
        }
      }
      __syncthreads();
    }
  }
  if (i < n) pphi[size_t(blockIdx.y) * n + i] = phi;
}

__global__ void sum_phi(int n, int nparts, const double* __restrict__ pphi, double* __restrict__ phi) {
  const int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i >= n) return;
  double s = 0;
  for (int y = 0; y < nparts; ++y) s += pphi[size_t(y) * n + i];
  phi[i] = s;
}

}  // namespace h4nb
