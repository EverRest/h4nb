#include <cub/cub.cuh>
#include <thrust/device_vector.h>
#include <thrust/iterator/counting_iterator.h>
#include <algorithm>
#include <chrono>
#include <climits>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <iterator>
#include <set>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>
#include "h4nb/h4nb.hpp"
#include "io.hpp"
#include "kernels.cuh"
#ifdef H4NB_HAVE_MPI
#include "mpi_comm.hpp"  // MPI-free interface. Only src/mpi_comm.cpp includes mpi.h.
#endif

namespace h4nb {
namespace {

// Throws with the device that was current at the failed call, so that the message names the GPU.
void ck(cudaError_t e, const char* what) {
  if (e == cudaSuccess) return;
  int dev = -1;
  (void)cudaGetDevice(&dev);
  throw std::runtime_error(std::string(what) + ": " + cudaGetErrorString(e) + " (device " + std::to_string(dev) + ")");
}
#define H4_CUDA(call) ck((call), #call)

// Debug mode H4NB_DEBUG_SYNC=1. After a kernel, wait for the stream and check it. The name in the message is the kernel.
// Without the mode this does nothing, so a normal run has no extra sync. Call it with the device of the stream set.
void check_launch(bool debug, cudaStream_t s, const char* kernel) {
  if (!debug) return;
  ck(cudaGetLastError(), kernel);
  ck(cudaStreamSynchronize(s), kernel);
}

// Restores the current CUDA device when the scope ends. It never throws.
struct DeviceGuard {
  int saved = -1;
  DeviceGuard() {
    if (cudaGetDevice(&saved) != cudaSuccess) saved = -1;
  }
  ~DeviceGuard() {
    if (saved >= 0) (void)cudaSetDevice(saved);
  }
  DeviceGuard(const DeviceGuard&) = delete;
  DeviceGuard& operator=(const DeviceGuard&) = delete;
};

// Sets failed when the scope ends by an exception. Set ok on the normal path.
struct FailMark {
  bool& failed;
  bool ok = false;
  ~FailMark() {
    if (!ok) failed = true;
  }
};

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

// The tiles that validate() accepts. Each tile is one instance of the force and potential kernels.
constexpr int kTiles[] = {64, 128, 256};

// Calls f(std::integral_constant<int, tile>) for the tile in kTiles. Throws for another tile. who names the caller.
template <class F, std::size_t... I>
void dispatch_tile_at(int tile, const char* who, F& f, std::index_sequence<I...>) {
  const bool done = ((tile == kTiles[I] && (f(std::integral_constant<int, kTiles[I]>{}), true)) || ...);
  if (!done) throw std::logic_error(std::string(who) + ": tile must be 64, 128 or 256.");
}
template <class F>
void dispatch_tile(int tile, const char* who, F f) {
  dispatch_tile_at(tile, who, f, std::make_index_sequence<std::size(kTiles)>{});
}

// Launch the force_kernel instance for tile.
void launch_force(int tile, dim3 grid, cudaStream_t s, int na, const d4* tx, const d4* tv, const int* tid, int ns,
                  const d4* sx, const d4* sv, int sbase, int chunk, double eps2, d4* pa, d4* pj) {
  dispatch_tile(tile, "launch_force", [&](auto tc) {
    constexpr int T = decltype(tc)::value;
    force_kernel<T><<<grid, T, 0, s>>>(na, tx, tv, tid, ns, sx, sv, sbase, chunk, eps2, pa, pj);
  });
}

// Launch the potential_kernel instance for tile.
void launch_potential(int tile, dim3 grid, cudaStream_t s, int n, const d4* xall, int ns, int sbase, int chunk,
                      double eps2, double* pphi) {
  dispatch_tile(tile, "launch_potential", [&](auto tc) {
    constexpr int T = decltype(tc)::value;
    potential_kernel<T><<<grid, T, 0, s>>>(n, xall, ns, sbase, chunk, eps2, pphi);
  });
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
  if (!std::isfinite(c.eta_init) || !(c.eta_init >= 0)) bad("eta_init must be finite and >= 0 (0 uses eta).");
  int e = 0;
  if (!std::isfinite(c.dt_max) || !(c.dt_max > 0) || std::frexp(c.dt_max, &e) != 0.5)
    bad("dt_max must be finite, > 0 and an exact power of two (for example 1/64).");
  if (c.max_level < 1 || c.max_level > 50) bad("max_level must be in [1, 50].");
  if (c.mode != StepMode::Block && c.mode != StepMode::Fixed) bad("mode must be Block or Fixed.");
  if (c.mode == StepMode::Fixed && (c.fixed_level < 0 || c.fixed_level > c.max_level))
    bad("fixed_level must be in [0, max_level] in Fixed mode.");
  if (!std::isfinite(c.r2_close) || !(c.r2_close >= 0)) bad("r2_close must be finite and >= 0.");
  if (c.devices.empty()) bad("devices must not be empty.");
  if (c.device_offset < 0) bad("device_offset must be >= 0.");
  if (std::find(std::begin(kTiles), std::end(kTiles), c.tile) == std::end(kTiles))
    bad("tile must be 64, 128 or 256.");
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
  // MPI path only (pinned host memory). h_status: status word for the reduce of phase 1.
  // The others: staging buffers for an MPI library that is not CUDA-aware (Config::mpi_host_staging).
  unsigned* h_status = nullptr;
  d4 *h_tx = nullptr, *h_tv = nullptr, *h_fa = nullptr, *h_fj = nullptr, *h_ra = nullptr, *h_rj = nullptr;
  int* h_tid = nullptr;
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
  Metrics mx;                    // Host counters for metrics(). Same block steps as st.
  double init_force_s = 0, init_levels_s = 0;  // Start-up times. metrics() copies them. reset does not clear them.
  // The particle set has P parts [base, base + n). One process: one part for each device, P = devices.size().
  // MPI (several ranks): one part for each rank, P = ranks(). Then d holds one device, the GPU of this rank.
  bool mpi = false;
  int P = 1;
  int part0 = 0;                 // Part of d[0]: 0 for one process, the rank for MPI.
  bool halted = false;           // A device or a rank has set kNaN. advance_to() stops at the next block step.
  std::vector<int> pbase, pn;    // MPI: base and size of each part, in rank order. The counts of the collectives.
  bool failed_ = false;          // Set when advance_to() or diagnostics() throws. See FailMark and require_ok().
  bool debug_sync = false;       // H4NB_DEBUG_SYNC=1, read once in the constructor. See check_launch().

  static void use(const Dev& e) { H4_CUDA(cudaSetDevice(e.id)); }
  void sync() {
    for (auto& e : d) {
      use(e);
      H4_CUDA(cudaStreamSynchronize(e.s));
    }
  }

  // Throws if an earlier advance_to() or diagnostics() failed. The state is then not defined (Q3).
  void require_ok() const {
    if (failed_) throw std::runtime_error("h4nb: a previous call failed; the Simulation state is not defined");
  }

  // Steps to target, then syncs. An exception sets failed_ (Q3).
  void run_to(int64_t target) {
    FailMark fm{failed_};
    while (T < target && !halted) step(false);  // Stops early when a device has set kNaN (A9).
    sync();
    fm.ok = true;
  }

  // D6: N is an int. Reject a larger set before the cast.
  static int particle_count(const Particles& p) {
    if (p.size() > size_t(INT_MAX)) throw std::invalid_argument("Simulation: more than INT_MAX particles.");
    return int(p.size());
  }

  Impl(const Particles& p, const Config& cfg) : c(cfg), N(particle_count(p)) {
    DeviceGuard dev_guard;  // Restores the caller's device (Q2).
    const char* dbg = std::getenv("H4NB_DEBUG_SYNC");
    debug_sync = dbg && std::strcmp(dbg, "1") == 0;
    // Q1: the destructor does not run when a constructor throws. So release the CUDA resources here.
    // release() is safe to call twice: the second call finds d empty.
    try {
#ifdef H4NB_HAVE_MPI
      if (comm::active()) {
        construct_mpi(p);
        return;
      }
#endif
      setup(p);
      init_pass();
    } catch (...) {
      release();
      throw;
    }
  }

#ifdef H4NB_HAVE_MPI
  // MPI constructor (task T034, hybrid error path). The checks and the allocations are local to each rank.
  // An agreement (MPI_MAX of an error code) follows them. Thus an error on one rank throws on all ranks,
  // before the first collective of step(). An error after the agreement stops all ranks (comm::fatal).
  void construct_mpi(const Particles& p) {
    mpi = true;
    P = comm::size();
    part0 = comm::rank();
    // MPI-H3: collective check, so all ranks agree. It runs before any allocation. Thus a throw needs no release.
    const int ca = comm::cuda_aware_all();
    if (ca < 0 && !c.mpi_host_staging && comm::rank() == 0)
      std::fprintf(stderr,
                   "h4nb: warning: cannot check that MPI is CUDA-aware. Set mpi_host_staging=1 if the run fails.\n");
    const std::string why = comm::staging_error(ca, c.mpi_host_staging);
    if (!why.empty()) throw std::invalid_argument(why);
    int code = 0;
    std::exception_ptr err;
    try {
      setup(p);
    } catch (const std::invalid_argument&) {
      code = 2, err = std::current_exception();
    } catch (...) {
      code = 1, err = std::current_exception();
    }
    int all = 0;
    try {
      all = comm::max_int(code);
    } catch (const std::exception& ex) {
      comm::fatal(ex.what());
    }
    if (all) {
      release();
      if (err) std::rethrow_exception(err);
      const std::string why = "Simulation: the setup failed on another rank. See the message of that rank.";
      if (all == 2) throw std::invalid_argument(why);
      throw std::runtime_error(why);
    }
    try {
      init_pass();
    } catch (const std::exception& ex) {
      comm::fatal(ex.what());
    }
  }
#endif

  // Checks the input, selects the devices, allocates and uploads. It does not run a collective.
  void setup(const Particles& p) {
    validate(c);
    const int G = mpi ? 1 : int(c.devices.size());
    if (!mpi) P = G;
    const size_t n = p.size();
    if (N < std::max(2, P)) throw std::invalid_argument("Use at least max(2, devices) particles (MPI: max(2, ranks)).");
    if (p.id.size() != n || p.x.size() != n || p.y.size() != n || p.z.size() != n || p.vx.size() != n ||
        p.vy.size() != n || p.vz.size() != n)
      throw std::invalid_argument("The Particles arrays have different sizes.");
    try {  // D6: m > 0, finite values, unique IDs. O(N).
      validate_particles(p, "Simulation input");
    } catch (const std::runtime_error& ex) {
      throw std::invalid_argument(ex.what());
    }
    int mpi_dev = 0;  // MPI: the GPU of this rank (docs/multi-node-design.md section 3.3). devices is not used.
#ifdef H4NB_HAVE_MPI
    if (mpi) {
      mpi_dev = comm::select_device(c.device_offset);
      for (int k = 0; k < P; ++k) {
        pbase.push_back(int(int64_t(N) * k / P));
        pn.push_back(int(int64_t(N) * (k + 1) / P) - pbase.back());
      }
    }
#endif
    if (!mpi) {
      int count = 0;  // The device ids need the CUDA runtime. So check them after the pure checks.
      H4_CUDA(cudaGetDeviceCount(&count));
      for (int id : c.devices)
        if (id < 0 || id >= count)
          bad("devices: id " + std::to_string(id) + " is not in [0, " + std::to_string(count) + ").");
    }
    tick = c.dt_max / std::ldexp(1.0, c.max_level);
    ids = p.id;
    d.resize(size_t(G));
    for (int g = 0; g < G; ++g) {
      Dev& e = d[size_t(g)];
      const int part = part0 + g;
      e.id = mpi ? mpi_dev : c.devices[size_t(g)];
      e.base = int(int64_t(N) * part / P);
      e.n = int(int64_t(N) * (part + 1) / P) - e.base;
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
      e.ra = e.alloc<d4>(size_t(P) * nn); e.rj = e.alloc<d4>(size_t(P) * nn);  // One row for each part.
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
      H4_CUDA(cudaMallocHost(&e.h_status, sizeof(unsigned)));
      if (mpi) {
        if (c.mpi_host_staging) {
          // ponytail: about N * 132 B + 2 * P * n * 32 B of pinned memory for each rank. Upgrade: buffers of
          // the size of the largest active set, if the pinned memory is measured as a problem.
          H4_CUDA(cudaMallocHost(&e.h_tx, NN * sizeof(d4)));
          H4_CUDA(cudaMallocHost(&e.h_tv, NN * sizeof(d4)));
          H4_CUDA(cudaMallocHost(&e.h_tid, NN * sizeof(int)));
          H4_CUDA(cudaMallocHost(&e.h_fa, NN * sizeof(d4)));
          H4_CUDA(cudaMallocHost(&e.h_fj, NN * sizeof(d4)));
          H4_CUDA(cudaMallocHost(&e.h_ra, size_t(P) * nn * sizeof(d4)));
          H4_CUDA(cudaMallocHost(&e.h_rj, size_t(P) * nn * sizeof(d4)));
        }
      }
      std::vector<d4> hx(nn), hv(nn);
      for (int k = 0; k < e.n; ++k) {
        const size_t i = size_t(e.base + k);
        hx[size_t(k)] = d4{p.x[i], p.y[i], p.z[i], p.m[i]};
        hv[size_t(k)] = d4{p.vx[i], p.vy[i], p.vz[i], 0.0};
      }
      if (c.fixed_center && part == 0) hv[0] = d4{0, 0, 0, 0};
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
  }

  ~Impl() { release(); }

  // Frees the device and host memory. It does not throw. A second call does nothing.
  void release() {
    for (auto& e : d) {
      cudaSetDevice(e.id);
      if (e.s) cudaStreamSynchronize(e.s);
      for (void* m : e.mem) cudaFree(m);
      e.mem.clear();
      for (void* h : {(void*)e.h_min, (void*)e.h_nsel, (void*)e.h_status, (void*)e.h_tx, (void*)e.h_tv,
                      (void*)e.h_tid, (void*)e.h_fa, (void*)e.h_fj, (void*)e.h_ra, (void*)e.h_rj})
        if (h) cudaFreeHost(h);
      if (e.ev_tx) cudaEventDestroy(e.ev_tx);
      if (e.ev_f) cudaEventDestroy(e.ev_f);
      if (e.s) cudaStreamDestroy(e.s);
      e = Dev{};
    }
    d.clear();
    cudaGetLastError();
  }

  // MPI: runs f. An exception on one rank can leave the other ranks in a collective. Thus it stops all ranks
  // (comm::fatal, MPI_Abort). One process: runs f and lets an exception pass.
  template <class F>
  auto guard(F&& f) -> decltype(f()) {
#ifdef H4NB_HAVE_MPI
    if (mpi) {
      try {
        return f();
      } catch (const std::exception& ex) {
        comm::fatal(ex.what());
      }
    }
#endif
    return f();
  }

  // Cold start (issue A1). The first levels use the full Aarseth estimate at t = 0. Snap and crackle need all sources,
  // so the state (x, v, a, j) of all particles is gathered on the host. Then each device sets the levels of its
  // owned particles. Fixed mode keeps fixed_level. The center (fixed_center) keeps the level of the update.
  // ponytail: host gather of 4 N vectors, once at start-up. Upgrade: device all-gather, as in step().
  void init_levels() {
    if (c.mode == StepMode::Fixed) return;
    sync();
    std::vector<d4> h[4];
    for (auto& v : h) v.resize(size_t(N));
    for (auto& e : d) {
      use(e);
      const d4* src[4] = {e.x, e.v, e.a, e.j};
      for (int k = 0; k < 4; ++k)
        H4_CUDA(cudaMemcpy(h[k].data() + e.base, src[k], size_t(e.n) * sizeof(d4), cudaMemcpyDeviceToHost));
    }
#ifdef H4NB_HAVE_MPI
    if (mpi) {  // Each rank has its own part. The allgather only copies the other parts (no floating-point sum).
      std::vector<int> cnt(P), dsp(P);  // Use (P). Do not use (size_t(P)): see step().
      comm::allgather_int(d[0].n, cnt.data());
      comm::allgather_int(d[0].base, dsp.data());
      for (auto& v : h) comm::allgatherv_d4(v.data(), cnt.data(), dsp.data());
    }
#endif
    // Full copies on each device. The vectors live until the kernels end (sync below).
    std::vector<thrust::device_vector<d4>> f[4];
    for (auto& e : d) {
      use(e);
      for (int k = 0; k < 4; ++k) f[k].emplace_back(h[k]);
    }
    const StepParams p = make_params(c, tick, 0, true);
    for (size_t g = 0; g < d.size(); ++g) {
      Dev& e = d[g];
      use(e);
      const int center = (c.fixed_center && e.base == 0) ? 0 : -1;
      if (e.n)
        init_level_kernel<<<blocks(e.n, 256), 256, 0, e.s>>>(e.n, e.base, N, f[0][g].data().get(), f[1][g].data().get(),
                                                              f[2][g].data().get(), f[3][g].data().get(), p, c.eps2,
                                                              c.dissipation == Dissipation::LinearDrag, center, e.level,
                                                              e.next, e.status);
      check_launch(debug_sync, e.s, "init_level_kernel");
    }
    sync();
    H4_CUDA(cudaGetLastError());
  }

  // Start-up: the first force pass, then the initial levels. Each part is timed on the host, with its sync.
  void init_pass() {
    using Clock = std::chrono::steady_clock;
    const auto t0 = Clock::now();
    step(true);
    sync();
    const auto t1 = Clock::now();
    init_levels();
    const auto t2 = Clock::now();
    init_force_s = std::chrono::duration<double>(t1 - t0).count();
    init_levels_s = std::chrono::duration<double>(t2 - t1).count();
  }

  // One block step. See "How a block step works" in the plan.
  // ponytail: two host syncs per block step (about 10 to 30 us). This matters only when NA is very small. Upgrade: CUDA graphs or device-side scheduling (O4).
  void step(bool init) {
#ifdef H4NB_HAVE_MPI
    if (mpi) {
      step_mpi(init);
      return;
    }
#endif
    const int G = int(d.size());
    int64_t Tn = 0;
    if (!init) {
      for (auto& e : d) {
        use(e);
        H4_CUDA(cub::DeviceReduce::Min(e.tmp, e.tmp_bytes, e.next, e.dmin, e.n, e.s));
        H4_CUDA(cudaMemcpyAsync(e.h_min, e.dmin, sizeof(int64_t), cudaMemcpyDeviceToHost, e.s));
        H4_CUDA(cudaMemcpyAsync(e.h_status, e.status, sizeof(unsigned), cudaMemcpyDeviceToHost, e.s));
      }
      Tn = INT64_MAX;
      unsigned flags = 0;
      for (auto& e : d) {
        use(e);
        H4_CUDA(cudaStreamSynchronize(e.s));
        Tn = std::min(Tn, *e.h_min);
        flags |= *e.h_status;
      }
      // A9 (MPI-M6): stop at this block step when a device has set kNaN. The MPI path does the same.
      if (flags & kNaN) {
        halted = true;
        return;
      }
    }
    for (auto& e : d) {
      use(e);
      predict_kernel<<<blocks(e.n, 256), 256, 0, e.s>>>(e.n, e.x, e.v, e.a, e.j, e.t, Tn, tick, e.xp, e.vp);
      check_launch(debug_sync, e.s, "predict_kernel");
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
    mx.active_hist[log2_bin(uint64_t(NA))]++;
    // All-gather of the active targets.
    for (int g = 0; g < G; ++g) {
      Dev& e = d[size_t(g)];
      const int o = off[size_t(g)], m = na[size_t(g)];
      use(e);
      if (m) gather_kernel<<<blocks(m, 256), 256, 0, e.s>>>(m, e.act, e.xp, e.vp, e.base, e.tx + o, e.tv + o, e.tid + o);
      check_launch(debug_sync, e.s, "gather_kernel");
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
      check_launch(debug_sync, e.s, "force_kernel");
      sum_partials<<<blocks(NA, 256), 256, 0, e.s>>>(NA, sp.nj, e.pa, e.pj, e.fa, e.fj);
      check_launch(debug_sync, e.s, "sum_partials");
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
      check_launch(debug_sync, e.s, "sum_partials");
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
      check_launch(debug_sync, e.s, "correct_kernel");
    }
    H4_CUDA(cudaGetLastError());
    T = Tn;
    ++st.block_steps;
    st.active_total += NA;
    ++mx.block_steps;
    mx.active_total += NA;
    mx.step_level_hist[detail::block_level(c.max_level, Tn)]++;
  }

#ifdef H4NB_HAVE_MPI
  // One block step on several ranks (task T031, docs/multi-node-design.md section 1.1). Each rank has one device
  // and owns the part [base, base + n). The four collective phases replace the peer copies of step():
  //   1. MPI_Allreduce (MIN) of {Tn, no-NaN flag}. Both values are integers, so the result does not depend on the order.
  //   2. MPI_Allgather of the active counts, then MPI_Allgatherv of the active targets. Block r goes to the offset
  //      off[r], the sum of the counts of the ranks before r. So the target list is in rank order, as in step().
  //   3. Each rank computes the force of its sources on all NA targets. MPI_Alltoallv sends the slice of each
  //      owner. Row h of ra and rj on the owner comes from rank h.
  //   4. sum_partials adds the rows 0, 1, ..., P-1 in this order. Then correct_kernel runs.
  // No floating-point value is added by MPI. The sums are those of step() with the rank in place of the device.
  // Thus one process with devices={0,1} and two ranks can give the same bits (same split, same device model).
  // Without Config::mpi_host_staging, MPI gets device pointers (CUDA-aware MPI). The stream is synchronized first.
  // ponytail: three host syncs and five collectives for each block step. Upgrade: gated O4 (CUDA graphs) after a
  // measurement on the cluster.
  void step_mpi(bool init) {
    Dev& e = d[0];
    const int r = part0;
    const bool stage = c.mpi_host_staging;
    use(e);
    int64_t Tn = 0;
    if (!init) {
      H4_CUDA(cub::DeviceReduce::Min(e.tmp, e.tmp_bytes, e.next, e.dmin, e.n, e.s));
      H4_CUDA(cudaMemcpyAsync(e.h_min, e.dmin, sizeof(int64_t), cudaMemcpyDeviceToHost, e.s));
      H4_CUDA(cudaMemcpyAsync(e.h_status, e.status, sizeof(unsigned), cudaMemcpyDeviceToHost, e.s));
      H4_CUDA(cudaStreamSynchronize(e.s));
      // Phase 1 also carries the error flag (task T034): v[1] is 0 on a rank with kNaN. MIN gives 0 on all ranks.
      int64_t v[2] = {*e.h_min, (*e.h_status & kNaN) ? 0 : 1};
      comm::min_i64(v, 2);
      if (v[1] == 0) {  // All ranks see the same value. All ranks stop at the same block step.
        halted = true;
        return;
      }
      Tn = v[0];
    }
    predict_kernel<<<blocks(e.n, 256), 256, 0, e.s>>>(e.n, e.x, e.v, e.a, e.j, e.t, Tn, tick, e.xp, e.vp);
    check_launch(debug_sync, e.s, "predict_kernel");
    size_t bytes = e.tmp_bytes;
    H4_CUDA(cub::DeviceSelect::If(e.tmp, bytes, thrust::counting_iterator<int>(0), e.act, e.nsel, e.n,
                                  IsActive{e.next, Tn}, e.s));
    H4_CUDA(cudaMemcpyAsync(e.h_nsel, e.nsel, sizeof(int), cudaMemcpyDeviceToHost, e.s));
    H4_CUDA(cudaStreamSynchronize(e.s));
    // Phase 2: the counts, then the targets in rank order.
    std::vector<int> na(P), off(P), rc(P), rd(P);  // Use (P). Do not use (size_t(P)): see step().
    comm::allgather_int(*e.h_nsel, na.data());
    int NA = 0;
    for (int h = 0; h < P; ++h) off[size_t(h)] = NA, NA += na[size_t(h)];
    mx.active_hist[log2_bin(uint64_t(NA))]++;
    const int m = na[size_t(r)], o = off[size_t(r)];
    if (m) gather_kernel<<<blocks(m, 256), 256, 0, e.s>>>(m, e.act, e.xp, e.vp, e.base, e.tx + o, e.tv + o, e.tid + o);
    check_launch(debug_sync, e.s, "gather_kernel");
    if (stage) {
      copy(e.h_tx + o, e.tx + o, size_t(m) * sizeof(d4), e.s);
      copy(e.h_tv + o, e.tv + o, size_t(m) * sizeof(d4), e.s);
      copy(e.h_tid + o, e.tid + o, size_t(m) * sizeof(int), e.s);
    }
    H4_CUDA(cudaStreamSynchronize(e.s));
    H4_CUDA(cudaGetLastError());
    comm::allgatherv_d4(stage ? (void*)e.h_tx : (void*)e.tx, na.data(), off.data());
    comm::allgatherv_d4(stage ? (void*)e.h_tv : (void*)e.tv, na.data(), off.data());
    comm::allgatherv_int(stage ? e.h_tid : e.tid, na.data(), off.data());
    if (stage) {
      copy(e.tx, e.h_tx, size_t(NA) * sizeof(d4), e.s);
      copy(e.tv, e.h_tv, size_t(NA) * sizeof(d4), e.s);
      copy(e.tid, e.h_tid, size_t(NA) * sizeof(int), e.s);
    }
    // Phase 3: the force of the own sources on all targets, then the slice of each owner.
    const Split sp = split(NA, e.n, e.sms, c.blocks_per_sm, c.tile);
    launch_force(c.tile, dim3(unsigned(blocks(NA, c.tile)), unsigned(sp.nj)), e.s, NA, e.tx, e.tv, e.tid, e.n, e.xp,
                 e.vp, e.base, sp.chunk, c.eps2, e.pa, e.pj);
    check_launch(debug_sync, e.s, "force_kernel");
    sum_partials<<<blocks(NA, 256), 256, 0, e.s>>>(NA, sp.nj, e.pa, e.pj, e.fa, e.fj);
    check_launch(debug_sync, e.s, "sum_partials");
    if (stage) {
      copy(e.h_fa, e.fa, size_t(NA) * sizeof(d4), e.s);
      copy(e.h_fj, e.fj, size_t(NA) * sizeof(d4), e.s);
    }
    H4_CUDA(cudaStreamSynchronize(e.s));
    H4_CUDA(cudaGetLastError());
    for (int h = 0; h < P; ++h) rc[size_t(h)] = m, rd[size_t(h)] = h * m;  // Row h comes from rank h.
    comm::alltoallv_d4(stage ? (void*)e.h_fa : (void*)e.fa, na.data(), off.data(), stage ? (void*)e.h_ra : (void*)e.ra,
                       rc.data(), rd.data());
    comm::alltoallv_d4(stage ? (void*)e.h_fj : (void*)e.fj, na.data(), off.data(), stage ? (void*)e.h_rj : (void*)e.rj,
                       rc.data(), rd.data());
    // Phase 4: the owner adds the rows in rank order. Then it corrects its particles.
    if (m) {
      if (stage) {
        copy(e.ra, e.h_ra, size_t(P) * size_t(m) * sizeof(d4), e.s);
        copy(e.rj, e.h_rj, size_t(P) * size_t(m) * sizeof(d4), e.s);
      }
      const StepParams prm = make_params(c, tick, Tn, init);
      sum_partials<<<blocks(m, 256), 256, 0, e.s>>>(m, P, e.ra, e.rj, e.ca, e.cj);
      check_launch(debug_sync, e.s, "sum_partials");
      const int center = (c.fixed_center && r == 0) ? 0 : -1, nodrag = r == 0 ? 0 : -1;
      if (c.dissipation == Dissipation::LinearDrag)
        correct_kernel<Dissipation::LinearDrag><<<blocks(m, 256), 256, 0, e.s>>>(
            m, e.act, e.ca, e.cj, prm, center, nodrag, e.vp, e.x, e.v, e.a, e.j, e.t, e.next, e.level, e.status,
            e.minr2, e.wd);
      else
        correct_kernel<Dissipation::Off><<<blocks(m, 256), 256, 0, e.s>>>(
            m, e.act, e.ca, e.cj, prm, center, nodrag, e.vp, e.x, e.v, e.a, e.j, e.t, e.next, e.level, e.status,
            e.minr2, e.wd);
      check_launch(debug_sync, e.s, "correct_kernel");
    }
    H4_CUDA(cudaGetLastError());
    T = Tn;
    ++st.block_steps;
    st.active_total += NA;
    ++mx.block_steps;
    mx.active_total += NA;
    mx.step_level_hist[detail::block_level(c.max_level, Tn)]++;
  }

  Particles state_mpi();          // Below. Collective.
  Diagnostics diagnostics_mpi();  // Below. Collective.
#endif
};

Simulation::Simulation(const Particles& p, const Config& c) : impl_(std::make_unique<Impl>(p, c)) {}
Simulation::~Simulation() {
  DeviceGuard dev_guard;
  impl_.reset();  // Frees the memory on the devices of this Simulation.
}

void Simulation::advance_to(double t) {
  DeviceGuard dev_guard;
  Impl& m = *impl_;
  m.require_ok();
  if (!std::isfinite(t)) throw std::invalid_argument("advance_to: t must be finite");  // L7: before the int64 cast.
  const double q = t / m.c.dt_max, r = std::nearbyint(q);
  if (std::fabs(q - r) > 1e-9 * std::max(1.0, std::fabs(q)))
    throw std::invalid_argument("advance_to: t must be a multiple of dt_max");
  if (r < 0 || r >= std::ldexp(1.0, 62 - m.c.max_level)) throw std::invalid_argument("advance_to: t out of range");
  const int64_t target = int64_t(r) << m.c.max_level;
  if (target < m.T) throw std::invalid_argument("advance_to: t is before time()");
#ifdef H4NB_HAVE_MPI
  if (m.mpi) {  // The checks above give the same result on all ranks. So they throw on all ranks or on none.
    m.guard([&] { m.run_to(target); });  // Stops early when a rank has set kNaN (task T034).
    return;
  }
#endif
  m.run_to(target);  // Stops early when a device has set kNaN (A9).
}

double Simulation::time() const { return double(impl_->T) * impl_->tick; }
Metrics Simulation::metrics(bool reset) {
  Impl& m = *impl_;
  Metrics out = m.mx;  // Host data only. No sync is needed: NA is the same on all ranks.
  out.init_force_s = m.init_force_s;
  out.init_levels_s = m.init_levels_s;
  if (reset) m.mx = Metrics{};
  return out;
}

Stats Simulation::stats() const {
  DeviceGuard dev_guard;
  Impl& m = *impl_;
  m.require_ok();
#ifdef H4NB_HAVE_MPI
  if (m.mpi)  // The counts are the same on all ranks (NA is global). min_r2: MIN over the ranks, exact.
    return m.guard([&] {
      m.sync();
      Stats s = m.st;
      unsigned long long b = 0;
      H4_CUDA(cudaMemcpy(&b, m.d[0].minr2, sizeof b, cudaMemcpyDeviceToHost));
      std::memcpy(&s.min_r2, &b, sizeof b);
      s.min_r2 = comm::min_double(s.min_r2);
      return s;
    });
#endif
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
  DeviceGuard dev_guard;
  Impl& m = *impl_;
  m.require_ok();
#ifdef H4NB_HAVE_MPI
  // MPI: each rank downloads its part. MPI_Allgatherv gives every rank the full set in global order.
  // ponytail: N * 64 B to every rank. Upgrade: MPI_Gatherv to rank 0 only, if a measurement needs it.
  if (m.mpi) return m.guard([&] { return m.state_mpi(); });
#endif
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
  DeviceGuard dev_guard;
  Impl& m = *impl_;
  m.require_ok();
#ifdef H4NB_HAVE_MPI
  if (m.mpi)  // Every rank gets all levels in global order (MPI_Allgatherv).
    return m.guard([&] {
      m.sync();
      const Dev& e = m.d[0];
      Impl::use(e);
      const size_t NN = size_t(m.N);
      std::vector<int> out(NN);
      H4_CUDA(cudaMemcpy(out.data() + e.base, e.level, size_t(e.n) * sizeof(int), cudaMemcpyDeviceToHost));
      comm::allgatherv_int(out.data(), m.pn.data(), m.pbase.data());
      return out;
    });
#endif
  m.sync();
  std::vector<int> out(size_t(m.N));
  for (auto& e : m.d) {
    Impl::use(e);
    H4_CUDA(cudaMemcpy(out.data() + e.base, e.level, size_t(e.n) * sizeof(int), cudaMemcpyDeviceToHost));
  }
  return out;
}

unsigned Simulation::status() const {
  DeviceGuard dev_guard;
  Impl& m = *impl_;
  m.require_ok();
#ifdef H4NB_HAVE_MPI
  if (m.mpi)  // MPI_BOR over the ranks: every rank gets the same bits.
    return m.guard([&] {
      m.sync();
      unsigned v = 0;
      Impl::use(m.d[0]);
      H4_CUDA(cudaMemcpy(&v, m.d[0].status, sizeof v, cudaMemcpyDeviceToHost));
      return comm::bor(v);
    });
#endif
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
  DeviceGuard dev_guard;
  Impl& m = *impl_;
  m.require_ok();
  FailMark fm{m.failed_};
#ifdef H4NB_HAVE_MPI
  if (m.mpi) {
    Diagnostics r = m.guard([&] { return m.diagnostics_mpi(); });
    fm.ok = true;
    return r;
  }
#endif
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
    check_launch(m.debug_sync, e.s, "potential_kernel");
    sum_phi<<<blocks(m.N, 256), 256, 0, e.s>>>(m.N, sp.nj, pp, e.phi);
    check_launch(m.debug_sync, e.s, "sum_phi");
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
  fm.ok = true;
  return r;
}

#ifdef H4NB_HAVE_MPI
// Diagnostics on several ranks (task T033, docs/multi-node-design.md section 4.1).
// 1. state() gives every rank all positions (MPI_Allgatherv). Each rank uploads them to tx in global order.
// 2. Each rank runs the potential kernel of the one-process path for its own sources: phi_r(i) is the sum over the
//    sources j > i of this rank. The work of rank r is about N * n_r - n_r^2 / 2 pairs, at most N^2 / P pairs.
//    This is within the bound of the design (N^2 / P for each rank), with the same kernel as one process.
// 3. Each rank computes Neumaier partial sums in index order: U_r = sum_i m_i phi_r(i) over all i, and K, P, L
//    and W_diss over its own particles.
// 4. MPI_Allgather gives every rank the 9 partials of all ranks. Each rank adds them in rank order (Neumaier).
//    Thus all ranks get the same bits, and the sum order is fixed. MPI does not add the values.
// The values differ from the one-process values in the last bits, because the sum order differs
// (docs/multi-node-design.md section 2.3: tolerance 1e-12).
Particles Simulation::Impl::state_mpi() {
  sync();
  const Dev& e = d[0];
  use(e);
  const size_t NN = size_t(N);
  std::vector<d4> hx(NN), hv(NN);  // Do not write hx(size_t(N)): it parses as a function declaration.
  H4_CUDA(cudaMemcpy(hx.data() + e.base, e.x, size_t(e.n) * sizeof(d4), cudaMemcpyDeviceToHost));
  H4_CUDA(cudaMemcpy(hv.data() + e.base, e.v, size_t(e.n) * sizeof(d4), cudaMemcpyDeviceToHost));
  comm::allgatherv_d4(hx.data(), pn.data(), pbase.data());
  comm::allgatherv_d4(hv.data(), pn.data(), pbase.data());
  Particles p;
  p.resize(size_t(N));
  p.id = ids;
  for (size_t i = 0; i < NN; ++i) {
    const d4 &x = hx[i], &v = hv[i];
    p.m[i] = x.w; p.x[i] = x.x; p.y[i] = x.y; p.z[i] = x.z;
    p.vx[i] = v.x; p.vy[i] = v.y; p.vz[i] = v.z;
  }
  return p;
}

Diagnostics Simulation::Impl::diagnostics_mpi() {
  Impl& m = *this;
  const Particles p = state_mpi();
  Dev& e = m.d[0];
  Impl::use(e);
  const size_t NN = size_t(m.N);
  std::vector<d4> hx(NN);
  for (size_t i = 0; i < NN; ++i) hx[i] = d4{p.x[i], p.y[i], p.z[i], p.m[i]};
  H4_CUDA(cudaMemcpyAsync(e.tx, hx.data(), NN * sizeof(d4), cudaMemcpyHostToDevice, e.s));
  const Split sp = split(m.N, e.n, e.sms, m.c.blocks_per_sm, m.c.tile);
  double* pp = reinterpret_cast<double*>(e.pa);  // N * nj doubles fit in pcap d4 entries.
  launch_potential(m.c.tile, dim3(unsigned(blocks(m.N, m.c.tile)), unsigned(sp.nj)), e.s, m.N, e.tx, e.n, e.base,
                   sp.chunk, m.c.eps2, pp);
  check_launch(m.debug_sync, e.s, "potential_kernel");
  sum_phi<<<blocks(m.N, 256), 256, 0, e.s>>>(m.N, sp.nj, pp, e.phi);
  check_launch(m.debug_sync, e.s, "sum_phi");
  std::vector<double> ph(NN), wd(size_t(e.n), 0.0);
  H4_CUDA(cudaMemcpyAsync(ph.data(), e.phi, NN * sizeof(double), cudaMemcpyDeviceToHost, e.s));
  if (m.c.dissipation != Dissipation::Off)
    H4_CUDA(cudaMemcpyAsync(wd.data(), e.wd, size_t(e.n) * sizeof(double), cudaMemcpyDeviceToHost, e.s));
  H4_CUDA(cudaStreamSynchronize(e.s));
  H4_CUDA(cudaGetLastError());
  NSum K, U, P[3], L[3], W;
  for (size_t i = 0; i < NN; ++i) U.add(p.m[i] * ph[i]);
  for (int k = 0; k < e.n; ++k) {
    const size_t i = size_t(e.base + k);
    const double mi = p.m[i];
    K.add(0.5 * mi * (p.vx[i] * p.vx[i] + p.vy[i] * p.vy[i] + p.vz[i] * p.vz[i]));
    P[0].add(mi * p.vx[i]); P[1].add(mi * p.vy[i]); P[2].add(mi * p.vz[i]);
    L[0].add(mi * (p.y[i] * p.vz[i] - p.z[i] * p.vy[i]));
    L[1].add(mi * (p.z[i] * p.vx[i] - p.x[i] * p.vz[i]));
    L[2].add(mi * (p.x[i] * p.vy[i] - p.y[i] * p.vx[i]));
    W.add(wd[size_t(k)]);
  }
  constexpr int kParts = 9;  // K, U, P[3], L[3], W.
  const double mine[kParts] = {K.value(), U.value(), P[0].value(), P[1].value(), P[2].value(),
                               L[0].value(), L[1].value(), L[2].value(), W.value()};
  std::vector<double> all(size_t(kParts) * size_t(m.P));
  comm::allgather_double(mine, kParts, all.data());
  NSum tot[kParts];
  for (int h = 0; h < m.P; ++h)  // Rank order.
    for (int q = 0; q < kParts; ++q) tot[q].add(all[size_t(h) * kParts + size_t(q)]);
  Diagnostics r;
  r.time = double(m.T) * m.tick;
  r.K = tot[0].value();
  r.U = -m.c.G * tot[1].value();
  r.E = r.K + r.U;
  for (int k = 0; k < 3; ++k) {
    r.P[k] = tot[2 + k].value();
    r.L[k] = tot[5 + k].value();
  }
  r.W_diss = tot[8].value();
  return r;
}
#endif

}  // namespace h4nb
