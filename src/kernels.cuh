#pragma once
#include <cstdint>
#include "hermite.cuh"

namespace h4nb {

// TILE is the number of targets per block. It is also the number of sources per shared-memory tile.
// Config::tile selects the instance at run time. kernels.cu instantiates TILE = 64, 128 and 256.
// Keep __restrict__ in the template declarations. Without it, nvcc 12.0 does not use read-only loads (LDG.CONSTANT).

__global__ void predict_kernel(int n, const d4* x, const d4* v, const d4* a, const d4* j, const int64_t* t, int64_t T,
                               double tick, d4* xp, d4* vp);
__global__ void gather_kernel(int na, const int* act, const d4* xp, const d4* vp, int base, d4* tx, d4* tv, int* tid);
// Grid: (ceil(na/TILE), nj). Block size: TILE. chunk must be a multiple of TILE.
// Block row y handles the sources [y*chunk, min(ns, (y+1)*chunk)). It writes row y of pa and pj with stride na.
// pa.w is r^2 of the closest source.
template <int TILE>
__global__ void force_kernel(int na, const d4* __restrict__ tx, const d4* __restrict__ tv, const int* __restrict__ tid,
                             int ns, const d4* __restrict__ sx, const d4* __restrict__ sv, int sbase, int chunk,
                             double eps2, d4* __restrict__ pa, d4* __restrict__ pj);
// fa[i] is the sum of rows 0 to nparts-1 of pa (stride na), in row order. .w is the minimum.
__global__ void sum_partials(int na, int nparts, const d4* pa, const d4* pj, d4* fa, d4* fj);
// D selects the dissipation model at compile time. nodrag is the local index of particle 0 on this device, or -1.
// vp: owned predicted velocities. wd: owned work of the dissipative force. Off does not read vp and wd.
template <Dissipation D>
__global__ void correct_kernel(int na, const int* act, const d4* fa, const d4* fj, StepParams p, int center,
                               int nodrag, const d4* vp, d4* x, d4* v, d4* a, d4* j, int64_t* t, int64_t* next,
                               int* level, unsigned* status, unsigned long long* minr2, double* wd);
// Grid: (ceil(n/TILE), nj). Block size: TILE. chunk must be a multiple of TILE.
// Row y of pphi: phi_i is the sum over the sources j > i in chunk y of m_j / sqrt(r^2 + eps2). xall holds all positions in global order.
template <int TILE>
__global__ void potential_kernel(int n, const d4* __restrict__ xall, int ns, int sbase, int chunk, double eps2,
                                 double* __restrict__ pphi);
__global__ void sum_phi(int n, int nparts, const double* pphi, double* phi);

}  // namespace h4nb
