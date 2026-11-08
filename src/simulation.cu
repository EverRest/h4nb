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
#include "diag_sum.hpp"
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

  // Launch correct_kernel for one active set. Dissipation::Off has no extra arithmetic.
  void launch_correct(Dev& e, int m, const StepParams& prm, int part) {
    const int center = (c.fixed_center && part == 0) ? 0 : -1, nodrag = part == 0 ? 0 : -1;
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

  // One block step (T031). Single process: peer copies between devices, sums in device order.
  // MPI (several ranks): the same phases with collectives; each rank owns one part; sums in rank order.
  // No floating-point value is added by MPI. One process with devices={0,1} and two ranks can give the same bits.
  // ponytail: two host syncs (one process) or three syncs and five collectives (MPI) per block step. Upgrade: O4.
  void step(bool init) {
    const int G = int(d.size());  // Local devices. Under MPI, G is 1.
    int64_t Tn = 0;
    if (!init) {
      for (auto& e : d) {
        use(e);
        H4_CUDA(cub::DeviceReduce::Min(e.tmp, e.tmp_bytes, e.next, e.dmin, e.n, e.s));
        H4_CUDA(cudaMemcpyAsync(e.h_min, e.dmin, sizeof(int64_t), cudaMemcpyDeviceToHost, e.s));
        H4_CUDA(cudaMemcpyAsync(e.h_status, e.status, sizeof(unsigned), cudaMemcpyDeviceToHost, e.s));
      }
      for (auto& e : d) {
        use(e);
        H4_CUDA(cudaStreamSynchronize(e.s));
      }
#ifdef H4NB_HAVE_MPI
      if (mpi) {
        // Phase 1 also carries the error flag (T034): v[1] is 0 on a rank with kNaN. MIN gives 0 on all ranks.
        int64_t v[2] = {*d[0].h_min, (*d[0].h_status & kNaN) ? 0 : 1};
        comm::min_i64(v, 2);
        if (v[1] == 0) {
          halted = true;
          return;
        }
        Tn = v[0];
      } else
#endif
      {
        Tn = INT64_MAX;
        unsigned flags = 0;
        for (auto& e : d) {
          Tn = std::min(Tn, *e.h_min);
          flags |= *e.h_status;
        }
        // A9 (MPI-M6): stop at this block step when a device has set kNaN.
        if (flags & kNaN) {
          halted = true;
          return;
        }
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
    for (auto& e : d) {
      use(e);
      H4_CUDA(cudaStreamSynchronize(e.s));
    }

    std::vector<int> na(P), off(P);  // Use (P). Do not use (size_t(P)): most vexing parse.
    int NA = 0;
#ifdef H4NB_HAVE_MPI
    if (mpi) {
      comm::allgather_int(*d[0].h_nsel, na.data());
      for (int h = 0; h < P; ++h) off[size_t(h)] = NA, NA += na[size_t(h)];
    } else
#endif
    {
      for (int g = 0; g < G; ++g) {
        na[size_t(g)] = *d[size_t(g)].h_nsel;
        off[size_t(g)] = NA;
        NA += na[size_t(g)];
      }
    }
    mx.active_hist[log2_bin(uint64_t(NA))]++;

#ifdef H4NB_HAVE_MPI
    if (mpi) {
      // MPI exchange (docs/multi-node-design.md §1.1). Without mpi_host_staging, MPI gets device pointers.
      Dev& e = d[0];
      const int r = part0;
      const bool stage = c.mpi_host_staging;
      const int m = na[size_t(r)], o = off[size_t(r)];
      use(e);
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
      std::vector<int> rc(P), rd(P);
      for (int h = 0; h < P; ++h) rc[size_t(h)] = m, rd[size_t(h)] = h * m;  // Row h comes from rank h.
      comm::alltoallv_d4(stage ? (void*)e.h_fa : (void*)e.fa, na.data(), off.data(), stage ? (void*)e.h_ra : (void*)e.ra,
                         rc.data(), rd.data());
      comm::alltoallv_d4(stage ? (void*)e.h_fj : (void*)e.fj, na.data(), off.data(), stage ? (void*)e.h_rj : (void*)e.rj,
                         rc.data(), rd.data());
      if (m) {
        if (stage) {
          copy(e.ra, e.h_ra, size_t(P) * size_t(m) * sizeof(d4), e.s);
          copy(e.rj, e.h_rj, size_t(P) * size_t(m) * sizeof(d4), e.s);
        }
        const StepParams prm = make_params(c, tick, Tn, init);
        sum_partials<<<blocks(m, 256), 256, 0, e.s>>>(m, P, e.ra, e.rj, e.ca, e.cj);
        check_launch(debug_sync, e.s, "sum_partials");
        launch_correct(e, m, prm, r);
      }
    } else
#endif
    {
      // Peer-copy exchange between local devices. Parts are the devices; order is device order.
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
      const StepParams prm = make_params(c, tick, Tn, init);
      for (int g = 0; g < G; ++g) {
        Dev& e = d[size_t(g)];
        const int m = na[size_t(g)];
        use(e);
        for (int h = 0; h < G; ++h)
          if (h != g) H4_CUDA(cudaStreamWaitEvent(e.s, d[size_t(h)].ev_f, 0));
        if (!m) continue;
        sum_partials<<<blocks(m, 256), 256, 0, e.s>>>(m, G, e.ra, e.rj, e.ca, e.cj);
        check_launch(debug_sync, e.s, "sum_partials");
        launch_correct(e, m, prm, g);
      }
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
  std::vector<double> ph(size_t(G) * size_t(m.N));  // Row h (device h) at h * N. The layout of diag_sum().
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
    H4_CUDA(cudaMemcpyAsync(ph.data() + size_t(h) * size_t(m.N), e.phi, size_t(m.N) * sizeof(double), cudaMemcpyDeviceToHost, e.s));
  }
  m.sync();
  H4_CUDA(cudaGetLastError());
  std::vector<double> wd(size_t(m.N), 0.0);
  if (m.c.dissipation != Dissipation::Off)
    for (auto& e : m.d) {
      Impl::use(e);
      H4_CUDA(cudaMemcpy(wd.data() + e.base, e.wd, size_t(e.n) * sizeof(double), cudaMemcpyDeviceToHost));
    }
  Diagnostics r = diag_sum(p, ph.data(), G, wd.data(), m.c.G);
  r.time = time();
  fm.ok = true;
  return r;
}

#ifdef H4NB_HAVE_MPI
// Diagnostics on several ranks (task T033, docs/multi-node-design.md section 4.1, MPI-M1).
// The result has the same bits as one process with the same parts on devices {0, ..., P-1}: rank h plays device h.
// 1. state_mpi() gives every rank all positions and velocities (MPI_Allgatherv). Each rank uploads them to tx.
// 2. Each rank runs the potential kernel of the one-process path for its own sources: row phi_r(i) is the sum over
//    the sources j > i of this rank, for all i. The kernel and the split are the same as for device r of one process.
// 3. MPI_Gather sends the rows to rank 0 in rank order (N doubles from each rank). MPI_Gatherv sends wd in global
//    order. Rank 0 calls diag_sum(), the host function of the one-process path. MPI does not add the values.
// 4. MPI_Bcast copies the result from rank 0 to all ranks. Thus all ranks get the same bits.
// ponytail: 8 * N * P bytes to rank 0 at each diag point. Upgrade: a GPU reduction of the rows in rank order.
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
  // All ranks call the same collectives in the same order. Only rank 0 needs the receive buffers.
  const bool root = comm::rank() == 0;
  std::vector<double> rows(root ? size_t(m.P) * NN : 0), wall(root ? NN : 0, 0.0);
  comm::gather_double(ph.data(), m.N, rows.data());
  if (m.c.dissipation != Dissipation::Off)  // The same on all ranks. Off: wd is 0, as in one process.
    comm::gatherv_double(wd.data(), e.n, wall.data(), m.pn.data(), m.pbase.data());
  constexpr int kOut = 10;  // K, U, E, P[3], L[3], W_diss.
  double out[kOut] = {};
  if (root) {
    const Diagnostics q = diag_sum(p, rows.data(), m.P, wall.data(), m.c.G);
    const double v[kOut] = {q.K, q.U, q.E, q.P[0], q.P[1], q.P[2], q.L[0], q.L[1], q.L[2], q.W_diss};
    std::copy(v, v + kOut, out);
  }
  comm::bcast_double(out, kOut);
  Diagnostics r;
  r.time = double(m.T) * m.tick;
  r.K = out[0]; r.U = out[1]; r.E = out[2];
  for (int k = 0; k < 3; ++k) r.P[k] = out[3 + k], r.L[k] = out[6 + k];
  r.W_diss = out[9];
  return r;
}
#endif

}  // namespace h4nb
