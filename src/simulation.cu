#include <cub/cub.cuh>
#include <thrust/iterator/counting_iterator.h>
#include <algorithm>
#include <climits>
#include <cmath>
#include <cstring>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
#include "h4nb/h4nb.hpp"
#include "kernels.cuh"

namespace h4nb {
namespace {

void ck(cudaError_t e, const char* what) {
  if (e != cudaSuccess) throw std::runtime_error(std::string(what) + ": " + cudaGetErrorString(e));
}
#define H4_CUDA(call) ck((call), #call)

int blocks(int n, int b) { return (n + b - 1) / b; }

struct IsActive {
  const int64_t* next;
  int64_t T;
  __device__ bool operator()(int i) const { return next[i] == T; }
};

// Split the sources (j) so that a launch has about bpsm blocks per SM (Config::blocks_per_sm).
// This holds even when few targets are active. tile is Config::tile. chunk is a multiple of tile.
// A different tile or bpsm gives a different chunk. This changes the grouping of the partial sums (constitution IV).
// The rows hold na * nj <= na + bpsm * sms * tile entries:
// nj <= ceil(bpsm * sms / b) with b = ceil(na / tile), and na <= b * tile. The final nj = ceil(ns / chunk) is not larger.
struct Split { int nj, chunk; };
Split split(int na, int ns, int sms, int bpsm, int tile) {
  const int nj = std::max(1, std::min(blocks(bpsm * sms, blocks(na, tile)), blocks(ns, tile)));
  const int chunk = blocks(blocks(ns, nj), tile) * tile;
  return {blocks(ns, chunk), chunk};
}

// Launch the force_kernel instance for tile. validate() accepts only 64, 128 and 256.
void launch_force(int tile, dim3 grid, cudaStream_t s, int na, const d4* tx, const d4* tv, const int* tid, int ns,
                  const d4* sx, const d4* sv, int sbase, int chunk, double eps2, d4* pa, d4* pj) {
  switch (tile) {
    case 64: force_kernel<64><<<grid, 64, 0, s>>>(na, tx, tv, tid, ns, sx, sv, sbase, chunk, eps2, pa, pj); break;
    case 128: force_kernel<128><<<grid, 128, 0, s>>>(na, tx, tv, tid, ns, sx, sv, sbase, chunk, eps2, pa, pj); break;
    case 256: force_kernel<256><<<grid, 256, 0, s>>>(na, tx, tv, tid, ns, sx, sv, sbase, chunk, eps2, pa, pj); break;
    default: throw std::logic_error("launch_force: tile must be 64, 128 or 256.");
  }
}

// Launch the potential_kernel instance for tile. validate() accepts only 64, 128 and 256.
void launch_potential(int tile, dim3 grid, cudaStream_t s, int n, const d4* xall, int ns, int sbase, int chunk,
                      double eps2, double* pphi) {
  switch (tile) {
    case 64: potential_kernel<64><<<grid, 64, 0, s>>>(n, xall, ns, sbase, chunk, eps2, pphi); break;
    case 128: potential_kernel<128><<<grid, 128, 0, s>>>(n, xall, ns, sbase, chunk, eps2, pphi); break;
    case 256: potential_kernel<256><<<grid, 256, 0, s>>>(n, xall, ns, sbase, chunk, eps2, pphi); break;
    default: throw std::logic_error("launch_potential: tile must be 64, 128 or 256.");
  }
}

// Neumaier compensated sum (TZ 4.4, 6.1). It reduces round-off error.
struct NSum {
  double s = 0, c = 0;
  void add(double x) {
    const double t = s + x;
    c += std::fabs(s) >= std::fabs(x) ? (s - t) + x : (x - t) + s;
    s = t;
  }
  double value() const { return s + c; }
};

void copy(void* dst, const void* src, size_t bytes, cudaStream_t s) {
  if (bytes) H4_CUDA(cudaMemcpyAsync(dst, src, bytes, cudaMemcpyDefault, s));
}

[[noreturn]] void bad(const std::string& msg) { throw std::invalid_argument("Config::" + msg); }

// Check each Config field that does not need the CUDA runtime. Throw std::invalid_argument with the field name.
// Do not clamp a value. The constructor checks the device ids after this function.
void validate(const Config& c) {
  if (!std::isfinite(c.G) || !(c.G > 0)) bad("G must be finite and > 0.");
  if (!std::isfinite(c.eps2) || !(c.eps2 >= 0)) bad("eps2 must be finite and >= 0.");
  if (!std::isfinite(c.eta) || !(c.eta > 0)) bad("eta must be finite and > 0.");
  if (!std::isfinite(c.eta_init) || !(c.eta_init > 0)) bad("eta_init must be finite and > 0.");
  int e = 0;
  if (!std::isfinite(c.dt_max) || !(c.dt_max > 0) || std::frexp(c.dt_max, &e) != 0.5)
    bad("dt_max must be finite, > 0 and an exact power of two (for example 1/64).");
  if (c.max_level < 1 || c.max_level > 50) bad("max_level must be in [1, 50].");
  if (c.mode != StepMode::Block && c.mode != StepMode::Fixed) bad("mode must be Block or Fixed.");
  if (c.mode == StepMode::Fixed && (c.fixed_level < 0 || c.fixed_level > c.max_level))
    bad("fixed_level must be in [0, max_level] in Fixed mode.");
  if (!std::isfinite(c.r2_close) || !(c.r2_close >= 0)) bad("r2_close must be finite and >= 0.");
  if (c.devices.empty()) bad("devices must not be empty.");
  if (c.tile != 64 && c.tile != 128 && c.tile != 256) bad("tile must be 64, 128 or 256.");
  if (c.blocks_per_sm < 1 || c.blocks_per_sm > 16) bad("blocks_per_sm must be in [1, 16].");
  if (c.dissipation != Dissipation::Off && c.dissipation != Dissipation::LinearDrag)
    bad("dissipation must be Off or LinearDrag.");
  if (c.dissipation == Dissipation::LinearDrag) {
    if (!std::isfinite(c.drag_tau) || !(c.drag_tau > 0)) bad("drag_tau must be finite and > 0 for LinearDrag.");
    for (double u : c.drag_vbg)
      if (!std::isfinite(u)) bad("drag_vbg must be finite for LinearDrag.");
  }
}

}  // namespace

struct Dev {
  int id = 0, base = 0, n = 0, sms = 0;  // Owns the global particles [base, base + n).
  cudaStream_t s{};
  cudaEvent_t ev_tx{}, ev_f{};
  d4 *x, *v, *a, *j, *xp, *vp;           // Owned state and predicted sources.
  int64_t *t, *next, *dmin;
  int *level, *act, *nsel;
  unsigned* status;
  unsigned long long* minr2;  // Bits of the smallest r^2 seen. The value is a non-negative double. See stats().
  d4 *tx, *tv;                           // All active targets (size N). Or all positions, for the diagnostics.
  int* tid;
  d4 *pa, *pj;                           // Partial sums of the j-split. Capacity: pcap.
  size_t pcap = 0;
  d4 *fa, *fj;                           // Force of this device on all targets (size N).
  d4 *ra, *rj;                           // Partial sums received from each device for the owned targets (G * n).
  d4 *ca, *cj;                           // Summed force on the owned targets (n).
  double* phi;                           // Potential sums (N).
  double* wd;                            // Work of the dissipative force on each owned particle since t = 0 (n).
  void* tmp = nullptr;
  size_t tmp_bytes = 0;
  int64_t* h_min = nullptr;              // Pinned host memory.
  int* h_nsel = nullptr;                 // Pinned host memory.
  std::vector<void*> mem;

  template <class T>
  T* alloc(size_t count) {
    void* p = nullptr;
    H4_CUDA(cudaMalloc(&p, std::max<size_t>(count, 1) * sizeof(T)));
    mem.push_back(p);
    return static_cast<T*>(p);
  }
};

struct Simulation::Impl {
  Config c;
  int N = 0;
  double tick = 0;
  int64_t T = 0;
  std::vector<int64_t> ids;
  std::vector<Dev> d;
  Stats st;

  static void use(const Dev& e) { H4_CUDA(cudaSetDevice(e.id)); }
  void sync() {
    for (auto& e : d) {
      use(e);
      H4_CUDA(cudaStreamSynchronize(e.s));
    }
  }

  Impl(const Particles& p, const Config& cfg) : c(cfg), N(int(p.size())) {
    validate(c);
    const int G = int(c.devices.size());
    const size_t n = p.size();
    if (N < std::max(2, G)) throw std::invalid_argument("Use at least max(2, devices) particles.");
    if (p.id.size() != n || p.x.size() != n || p.y.size() != n || p.z.size() != n || p.vx.size() != n ||
        p.vy.size() != n || p.vz.size() != n)
      throw std::invalid_argument("The Particles arrays have different sizes.");
    int count = 0;  // The device ids need the CUDA runtime. So check them after the pure checks.
    H4_CUDA(cudaGetDeviceCount(&count));
    for (int id : c.devices)
      if (id < 0 || id >= count)
        bad("devices: id " + std::to_string(id) + " is not in [0, " + std::to_string(count) + ").");
    tick = c.dt_max / std::ldexp(1.0, c.max_level);
    ids = p.id;
    d.resize(size_t(G));
    for (int g = 0; g < G; ++g) {
      Dev& e = d[size_t(g)];
      e.id = c.devices[size_t(g)];
      e.base = int(int64_t(N) * g / G);
      e.n = int(int64_t(N) * (g + 1) / G) - e.base;
      use(e);
      H4_CUDA(cudaDeviceGetAttribute(&e.sms, cudaDevAttrMultiProcessorCount, e.id));
      H4_CUDA(cudaStreamCreate(&e.s));
      H4_CUDA(cudaEventCreateWithFlags(&e.ev_tx, cudaEventDisableTiming));
      H4_CUDA(cudaEventCreateWithFlags(&e.ev_f, cudaEventDisableTiming));
      const size_t nn = size_t(e.n), NN = size_t(N);
      e.x = e.alloc<d4>(nn); e.v = e.alloc<d4>(nn); e.a = e.alloc<d4>(nn); e.j = e.alloc<d4>(nn);
      e.xp = e.alloc<d4>(nn); e.vp = e.alloc<d4>(nn);
      e.t = e.alloc<int64_t>(nn); e.next = e.alloc<int64_t>(nn); e.dmin = e.alloc<int64_t>(1);
      e.level = e.alloc<int>(nn); e.act = e.alloc<int>(nn); e.nsel = e.alloc<int>(1);
      e.status = e.alloc<unsigned>(1);
      e.minr2 = e.alloc<unsigned long long>(1);
      e.tx = e.alloc<d4>(NN); e.tv = e.alloc<d4>(NN); e.tid = e.alloc<int>(NN);
      // At least na * nj for every split with na <= N. See split().
      e.pcap = NN + size_t(c.blocks_per_sm) * size_t(e.sms) * size_t(c.tile);
      e.pa = e.alloc<d4>(e.pcap); e.pj = e.alloc<d4>(e.pcap);
      e.fa = e.alloc<d4>(NN); e.fj = e.alloc<d4>(NN);
      e.ra = e.alloc<d4>(size_t(G) * nn); e.rj = e.alloc<d4>(size_t(G) * nn);
      e.ca = e.alloc<d4>(nn); e.cj = e.alloc<d4>(nn);
      e.phi = e.alloc<double>(NN);
      e.wd = e.alloc<double>(nn);  // Also with Off: n doubles are cheap, and the pointer is then always valid.
      size_t b1 = 0, b2 = 0;
      H4_CUDA(cub::DeviceReduce::Min(nullptr, b1, e.next, e.dmin, e.n));
      H4_CUDA(cub::DeviceSelect::If(nullptr, b2, thrust::counting_iterator<int>(0), e.act, e.nsel, e.n,
                                    IsActive{e.next, 0}));
      e.tmp_bytes = std::max(b1, b2);
      e.tmp = e.alloc<char>(e.tmp_bytes);
      H4_CUDA(cudaMallocHost(&e.h_min, sizeof(int64_t)));
      H4_CUDA(cudaMallocHost(&e.h_nsel, sizeof(int)));
      std::vector<d4> hx(nn), hv(nn);
      for (int k = 0; k < e.n; ++k) {
        const size_t i = size_t(e.base + k);
        hx[size_t(k)] = d4{p.x[i], p.y[i], p.z[i], p.m[i]};
        hv[size_t(k)] = d4{p.vx[i], p.vy[i], p.vz[i], 0.0};
      }
      if (c.fixed_center && g == 0) hv[0] = d4{0, 0, 0, 0};
      H4_CUDA(cudaMemcpy(e.x, hx.data(), nn * sizeof(d4), cudaMemcpyHostToDevice));
      H4_CUDA(cudaMemcpy(e.v, hv.data(), nn * sizeof(d4), cudaMemcpyHostToDevice));
      H4_CUDA(cudaMemset(e.a, 0, nn * sizeof(d4)));
      H4_CUDA(cudaMemset(e.j, 0, nn * sizeof(d4)));
      H4_CUDA(cudaMemset(e.t, 0, nn * sizeof(int64_t)));
      H4_CUDA(cudaMemset(e.next, 0, nn * sizeof(int64_t)));
      H4_CUDA(cudaMemset(e.level, 0, nn * sizeof(int)));
      H4_CUDA(cudaMemset(e.wd, 0, nn * sizeof(double)));
      H4_CUDA(cudaMemset(e.status, 0, sizeof(unsigned)));
      const unsigned long long inf_bits = 0x7FF0000000000000ULL;  // Positive infinity.
      H4_CUDA(cudaMemcpy(e.minr2, &inf_bits, sizeof inf_bits, cudaMemcpyHostToDevice));
    }
    std::set<std::pair<int, int>> done;  // Enable peer access between different devices, where possible.
    for (auto& a : d)
      for (auto& b : d)
        if (a.id != b.id && done.insert({a.id, b.id}).second) {
          int ok = 0;
          H4_CUDA(cudaDeviceCanAccessPeer(&ok, a.id, b.id));
          if (!ok) continue;
          use(a);
          const cudaError_t r = cudaDeviceEnablePeerAccess(b.id, 0);
          if (r != cudaSuccess && r != cudaErrorPeerAccessAlreadyEnabled) ck(r, "cudaDeviceEnablePeerAccess");
          (void)cudaGetLastError();
        }
    step(true);
    sync();
  }

  ~Impl() {
    for (auto& e : d) {
      cudaSetDevice(e.id);
      cudaStreamSynchronize(e.s);
      for (void* m : e.mem) cudaFree(m);
      cudaFreeHost(e.h_min);
      cudaFreeHost(e.h_nsel);
      cudaEventDestroy(e.ev_tx);
      cudaEventDestroy(e.ev_f);
      cudaStreamDestroy(e.s);
    }
  }

  // One block step. See "How a block step works" in the plan.
  // ponytail: two host syncs per block step (about 10 to 30 us). This matters only when NA is very small. Upgrade: CUDA graphs or device-side scheduling (O4).
  void step(bool init) {
    const int G = int(d.size());
    int64_t Tn = 0;
    if (!init) {
      for (auto& e : d) {
        use(e);
        H4_CUDA(cub::DeviceReduce::Min(e.tmp, e.tmp_bytes, e.next, e.dmin, e.n, e.s));
        H4_CUDA(cudaMemcpyAsync(e.h_min, e.dmin, sizeof(int64_t), cudaMemcpyDeviceToHost, e.s));
      }
      Tn = INT64_MAX;
      for (auto& e : d) {
        use(e);
        H4_CUDA(cudaStreamSynchronize(e.s));
        Tn = std::min(Tn, *e.h_min);
      }
    }
    for (auto& e : d) {
      use(e);
      predict_kernel<<<blocks(e.n, 256), 256, 0, e.s>>>(e.n, e.x, e.v, e.a, e.j, e.t, Tn, tick, e.xp, e.vp);
      size_t bytes = e.tmp_bytes;
      H4_CUDA(cub::DeviceSelect::If(e.tmp, bytes, thrust::counting_iterator<int>(0), e.act, e.nsel, e.n,
                                    IsActive{e.next, Tn}, e.s));
      H4_CUDA(cudaMemcpyAsync(e.h_nsel, e.nsel, sizeof(int), cudaMemcpyDeviceToHost, e.s));
    }
    std::vector<int> off(G), na(G);  // Use (G). Do not use (size_t(G)): it parses as a function declaration.
    int NA = 0;
    for (int g = 0; g < G; ++g) {
      use(d[size_t(g)]);
      H4_CUDA(cudaStreamSynchronize(d[size_t(g)].s));
      na[size_t(g)] = *d[size_t(g)].h_nsel;
      off[size_t(g)] = NA;
      NA += na[size_t(g)];
    }
    // All-gather of the active targets.
    for (int g = 0; g < G; ++g) {
      Dev& e = d[size_t(g)];
      const int o = off[size_t(g)], m = na[size_t(g)];
      use(e);
      if (m) gather_kernel<<<blocks(m, 256), 256, 0, e.s>>>(m, e.act, e.xp, e.vp, e.base, e.tx + o, e.tv + o, e.tid + o);
      for (int h = 0; h < G; ++h) {
        if (h == g) continue;
        copy(d[size_t(h)].tx + o, e.tx + o, size_t(m) * sizeof(d4), e.s);
        copy(d[size_t(h)].tv + o, e.tv + o, size_t(m) * sizeof(d4), e.s);
        copy(d[size_t(h)].tid + o, e.tid + o, size_t(m) * sizeof(int), e.s);
      }
      H4_CUDA(cudaEventRecord(e.ev_tx, e.s));
    }
    // Each device computes the partial forces of its sources on all targets. Then the slices go to their owners.
    for (int h = 0; h < G; ++h) {
      Dev& e = d[size_t(h)];
      use(e);
      for (int g = 0; g < G; ++g)
        if (g != h) H4_CUDA(cudaStreamWaitEvent(e.s, d[size_t(g)].ev_tx, 0));
      const Split sp = split(NA, e.n, e.sms, c.blocks_per_sm, c.tile);
      launch_force(c.tile, dim3(unsigned(blocks(NA, c.tile)), unsigned(sp.nj)), e.s, NA, e.tx, e.tv, e.tid, e.n, e.xp,
                   e.vp, e.base, sp.chunk, c.eps2, e.pa, e.pj);
      sum_partials<<<blocks(NA, 256), 256, 0, e.s>>>(NA, sp.nj, e.pa, e.pj, e.fa, e.fj);
      for (int g = 0; g < G; ++g) {
        const size_t m = size_t(na[size_t(g)]), row = size_t(h) * m;
        copy(d[size_t(g)].ra + row, e.fa + off[size_t(g)], m * sizeof(d4), e.s);
        copy(d[size_t(g)].rj + row, e.fj + off[size_t(g)], m * sizeof(d4), e.s);
      }
      H4_CUDA(cudaEventRecord(e.ev_f, e.s));
    }
    // Each owner adds the rows in device order. Then it corrects its particles.
    const StepParams sp = make_params(c, tick, Tn, init);
    for (int g = 0; g < G; ++g) {
      Dev& e = d[size_t(g)];
      const int m = na[size_t(g)];
      use(e);
      for (int h = 0; h < G; ++h)
        if (h != g) H4_CUDA(cudaStreamWaitEvent(e.s, d[size_t(h)].ev_f, 0));
      if (!m) continue;
      sum_partials<<<blocks(m, 256), 256, 0, e.s>>>(m, G, e.ra, e.rj, e.ca, e.cj);
      const int center = (c.fixed_center && g == 0) ? 0 : -1, nodrag = g == 0 ? 0 : -1;
      // Select the dissipation model one time for each launch. The Off instance has no extra arithmetic.
      if (c.dissipation == Dissipation::LinearDrag)
        correct_kernel<Dissipation::LinearDrag><<<blocks(m, 256), 256, 0, e.s>>>(
            m, e.act, e.ca, e.cj, sp, center, nodrag, e.vp, e.x, e.v, e.a, e.j, e.t, e.next, e.level, e.status,
            e.minr2, e.wd);
      else
        correct_kernel<Dissipation::Off><<<blocks(m, 256), 256, 0, e.s>>>(
            m, e.act, e.ca, e.cj, sp, center, nodrag, e.vp, e.x, e.v, e.a, e.j, e.t, e.next, e.level, e.status,
            e.minr2, e.wd);
    }
    H4_CUDA(cudaGetLastError());
    T = Tn;
    ++st.block_steps;
    st.active_total += NA;
  }
};

Simulation::Simulation(const Particles& p, const Config& c) : impl_(std::make_unique<Impl>(p, c)) {}
Simulation::~Simulation() = default;

void Simulation::advance_to(double t) {
  Impl& m = *impl_;
  const double q = t / m.c.dt_max, r = std::nearbyint(q);
  if (std::fabs(q - r) > 1e-9 * std::max(1.0, std::fabs(q)))
    throw std::invalid_argument("advance_to: t must be a multiple of dt_max");
  if (r < 0 || r >= std::ldexp(1.0, 62 - m.c.max_level)) throw std::invalid_argument("advance_to: t out of range");
  const int64_t target = int64_t(r) << m.c.max_level;
  if (target < m.T) throw std::invalid_argument("advance_to: t is before time()");
  while (m.T < target) m.step(false);
  m.sync();
}

double Simulation::time() const { return double(impl_->T) * impl_->tick; }
Stats Simulation::stats() const {
  Impl& m = *impl_;
  m.sync();
  Stats s = m.st;
  for (auto& e : m.d) {
    Impl::use(e);
    unsigned long long b = 0;
    H4_CUDA(cudaMemcpy(&b, e.minr2, sizeof b, cudaMemcpyDeviceToHost));
    double r;
    std::memcpy(&r, &b, sizeof r);
    s.min_r2 = std::min(s.min_r2, r);
  }
  return s;
}

Particles Simulation::state() const {
  Impl& m = *impl_;
  m.sync();
  Particles p;
  p.resize(size_t(m.N));
  p.id = m.ids;
  std::vector<d4> hx, hv;
  for (auto& e : m.d) {
    Impl::use(e);
    hx.resize(size_t(e.n));
    hv.resize(size_t(e.n));
    H4_CUDA(cudaMemcpy(hx.data(), e.x, hx.size() * sizeof(d4), cudaMemcpyDeviceToHost));
    H4_CUDA(cudaMemcpy(hv.data(), e.v, hv.size() * sizeof(d4), cudaMemcpyDeviceToHost));
    for (int k = 0; k < e.n; ++k) {
      const size_t i = size_t(e.base + k);
      const d4 &x = hx[size_t(k)], &v = hv[size_t(k)];
      p.m[i] = x.w; p.x[i] = x.x; p.y[i] = x.y; p.z[i] = x.z;
      p.vx[i] = v.x; p.vy[i] = v.y; p.vz[i] = v.z;
    }
  }
  return p;
}

std::vector<int> Simulation::levels() const {
  Impl& m = *impl_;
  m.sync();
  std::vector<int> out(size_t(m.N));
  for (auto& e : m.d) {
    Impl::use(e);
    H4_CUDA(cudaMemcpy(out.data() + e.base, e.level, size_t(e.n) * sizeof(int), cudaMemcpyDeviceToHost));
  }
  return out;
}

unsigned Simulation::status() const {
  Impl& m = *impl_;
  m.sync();
  unsigned s = 0;
  for (auto& e : m.d) {
    Impl::use(e);
    unsigned v = 0;
    H4_CUDA(cudaMemcpy(&v, e.status, sizeof v, cudaMemcpyDeviceToHost));
    s |= v;
  }
  return s;
}

// Diagnostics run at a sync point, where all particles have t = T. The state is exact, not predicted (D6).
// The GPU computes the potential over unique pairs j > i. The host computes K, P, L and all final sums,
// in a fixed order, with Neumaier summation.
// ponytail: downloads N doubles per device and the state. This is fine at a diagnostic interval. Upgrade: GPU tree reduction.
Diagnostics Simulation::diagnostics() {
  Impl& m = *impl_;
  const Particles p = state();
  const int G = int(m.d.size());
  for (auto& e : m.d) {  // All-gather every position into tx, in global order.
    Impl::use(e);
    for (auto& f : m.d) copy(f.tx + e.base, e.x, size_t(e.n) * sizeof(d4), e.s);
    H4_CUDA(cudaEventRecord(e.ev_tx, e.s));
  }
  std::vector<std::vector<double>> ph(size_t(G), std::vector<double>(size_t(m.N)));
  for (int h = 0; h < G; ++h) {
    Dev& e = m.d[size_t(h)];
    Impl::use(e);
    for (int g = 0; g < G; ++g)
      if (g != h) H4_CUDA(cudaStreamWaitEvent(e.s, m.d[size_t(g)].ev_tx, 0));
    const Split sp = split(m.N, e.n, e.sms, m.c.blocks_per_sm, m.c.tile);
    double* pp = reinterpret_cast<double*>(e.pa);  // N * nj doubles fit in pcap d4 entries.
    launch_potential(m.c.tile, dim3(unsigned(blocks(m.N, m.c.tile)), unsigned(sp.nj)), e.s, m.N, e.tx, e.n, e.base,
                     sp.chunk, m.c.eps2, pp);
    sum_phi<<<blocks(m.N, 256), 256, 0, e.s>>>(m.N, sp.nj, pp, e.phi);
    H4_CUDA(cudaMemcpyAsync(ph[size_t(h)].data(), e.phi, size_t(m.N) * sizeof(double), cudaMemcpyDeviceToHost, e.s));
  }
  m.sync();
  H4_CUDA(cudaGetLastError());
  std::vector<double> wd(size_t(m.N), 0.0);
  if (m.c.dissipation != Dissipation::Off)
    for (auto& e : m.d) {
      Impl::use(e);
      H4_CUDA(cudaMemcpy(wd.data() + e.base, e.wd, size_t(e.n) * sizeof(double), cudaMemcpyDeviceToHost));
    }
  NSum K, U, P[3], L[3], W;
  for (size_t i = 0; i < p.size(); ++i) {
    double phi = 0;
    for (int h = 0; h < G; ++h) phi += ph[size_t(h)][i];
    const double mi = p.m[i];
    U.add(mi * phi);
    K.add(0.5 * mi * (p.vx[i] * p.vx[i] + p.vy[i] * p.vy[i] + p.vz[i] * p.vz[i]));
    P[0].add(mi * p.vx[i]); P[1].add(mi * p.vy[i]); P[2].add(mi * p.vz[i]);
    L[0].add(mi * (p.y[i] * p.vz[i] - p.z[i] * p.vy[i]));
    L[1].add(mi * (p.z[i] * p.vx[i] - p.x[i] * p.vz[i]));
    L[2].add(mi * (p.x[i] * p.vy[i] - p.y[i] * p.vx[i]));
    W.add(wd[i]);
  }
  Diagnostics r;
  r.time = time();
  r.K = K.value();
  r.U = -m.c.G * U.value();
  r.E = r.K + r.U;
  r.W_diss = W.value();
  for (int k = 0; k < 3; ++k) {
    r.P[k] = P[k].value();
    r.L[k] = L[k].value();
  }
  return r;
}

}  // namespace h4nb
