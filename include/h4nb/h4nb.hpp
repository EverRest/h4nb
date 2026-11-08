// h4nb: direct N-body library. It has a 4th-order Hermite integrator, Aarseth block time steps, FP64 and one or more NVIDIA GPUs.
#pragma once
#include <cstdint>
#include <limits>
#include <memory>
#include <string>
#include <vector>

namespace h4nb {

// Host particle set, in structure-of-arrays form. Index 0 is the central body.
struct Particles {
  std::vector<int64_t> id;
  std::vector<double> m, x, y, z, vx, vy, vz;
  size_t size() const { return m.size(); }
  void resize(size_t n) {
    id.resize(n); m.resize(n); x.resize(n); y.resize(n); z.resize(n); vx.resize(n); vy.resize(n); vz.resize(n);
  }
};

enum class StepMode { Block, Fixed };

// Dissipation model (research R7). LinearDrag: a_diss = -(v - drag_vbg) / drag_tau on each particle except particle 0.
enum class Dissipation { Off, LinearDrag };

// Bits returned by Simulation::status(). A bit stays set after it is set once.
enum StatusBits : unsigned {
  kNaN = 1u /* NaN or Inf */,
  kDtUnderflow = 2u,
  kClosePair = 4u,
  kInitStepInvalid = 8u /* first step estimate not finite or not positive: coarsest level used (issue A1) */
};

struct Config {
  double G = 1.0;
  double eps2 = 0.0;          // Plummer softening squared. 0 means Newtonian gravity (default).
  double eta = 0.01;          // Aarseth accuracy parameter
  double eta_init = 0.0;      // first step: Aarseth dt at t = 0 with eta_init. 0 uses eta. No force: level 0.
  double dt_max = 1.0 / 64;   // Step of level 0. The advance_to() times must be multiples of it.
  int max_level = 40;         // dt_min = dt_max / 2^max_level. Allowed: 1 to 50.
  StepMode mode = StepMode::Block;
  int fixed_level = 0;        // Fixed mode: every particle uses dt_max / 2^fixed_level
  bool fixed_center = false;  // Particle 0 does not move. Use this only for tests and comparisons.
  double r2_close = 0.0;      // Set kClosePair when a pair has r^2 < r2_close. 0 turns this off.
  std::vector<int> devices = {0};  // CUDA device ids. A repeated id emulates more GPUs on one card.
  int tile = 128;             // Targets per block in the force and potential kernels. Allowed: 64, 128, 256.
  int blocks_per_sm = 4;      // Target number of blocks per SM for the source split. Allowed: 1 to 16.
  Dissipation dissipation = Dissipation::Off;  // Off gives the same bits as a build without the term.
  double drag_tau = 0;                // LinearDrag: drag time. It must be finite and > 0.
  double drag_vbg[3] = {0, 0, 0};     // LinearDrag: background velocity. It must be finite.
  // Several ranks only (ranks() > 1). A single process ignores these two fields.
  int device_offset = 0;              // GPU of a rank: (local_rank() + device_offset) % device count. It must be >= 0.
  bool mpi_host_staging = false;      // true: copy the MPI buffers through pinned host memory (MPI is not CUDA-aware).
};

struct Diagnostics {
  double time = 0, K = 0, U = 0, E = 0;
  double P[3] = {0, 0, 0}, L[3] = {0, 0, 0};
  double W_diss = 0;  // Work of the dissipative forces since t = 0. 0 when Config::dissipation is Off. E - E0 - W_diss is about 0.
};

struct Stats {
  int64_t block_steps = 0;   // Number of block steps done.
  int64_t active_total = 0;  // Sum of the active particles over all block steps. Pair evaluations = active_total * N.
  double min_r2 = std::numeric_limits<double>::infinity();  // Smallest r^2 between a target and its closest source so far.
};

// Host counters (no GPU cost). They count block steps from the start, or from the last metrics(true).
struct Metrics {
  int64_t block_steps = 0;
  int64_t active_total = 0;
  uint64_t active_hist[64] = {};      // active_hist[log2_bin(NA)]: block steps with NA active particles.
  uint64_t step_level_hist[51] = {};  // step_level_hist[L]: block steps at dt level L, from 0 to 50.
  // Host wall time of the first force pass, with its sync. Set once by the constructor.
  // metrics(true) does not clear it.
  double init_force_s = 0;
  // Host wall time of the initial levels, with its sync. Set once by the constructor. Zero in Fixed mode.
  // metrics(true) does not clear it.
  double init_levels_s = 0;
};

// Local per-rank phase times and traffic (issue MPI-M3). Host clocks at the existing sync points only.
// Timing does not change control flow. profile(true) clears the counters after the copy.
// t_setup and t_init_force are set once by the constructor; profile(true) does not clear them.
// gpu_force_ms stays 0 until profile=2 (cudaEvent) is added.
struct RankProfile {
  int64_t steps = 0;
  int64_t na_total = 0;             // Sum of global NA over block steps on this rank.
  int64_t own_active_total = 0;     // Sum of this rank's (or all local devices') active counts.
  int own_active_max = 0;
  uint64_t na_hist[32] = {};        // na_hist[log2_bin(NA)], capped at bin 31.
  int64_t bytes_sent = 0;
  int64_t bytes_recv = 0;
  int64_t bytes_h2d = 0;
  int64_t bytes_d2h = 0;
  double t_tn = 0;       // Find next block time (min next + sync / Allreduce).
  double t_select = 0;   // Predict + DeviceSelect + sync.
  double t_gather = 0;   // Gather actives + Allgatherv / peer copies of (x,v,id).
  double t_force = 0;    // Force + partial sum.
  double t_xchg = 0;     // Alltoallv / peer copies of forces.
  double t_correct = 0;  // Owner sum + corrector.
  double t_diag = 0;     // Filled by the tool around diagnostics(), not by step().
  double t_state = 0;    // Filled by the tool around state(), not by step().
  double t_setup = 0;    // Constructor wall before the first force (set once).
  double t_init_force = 0;  // Same as Metrics::init_force_s (set once).
  double gpu_force_ms = 0;
};

// floor(log2(n)). It gives 0 for n = 0 and for n = 1.
inline int log2_bin(uint64_t n) {
  int b = 0;
  while (n >>= 1) ++b;
  return b;
}

namespace detail {
// Dt level of a block time tn (in ticks): max_level - ctz(tn), clamped to [0, max_level]. A tn that is a
// multiple of dt_max (ctz >= max_level) gives 0. tn <= 0 gives 0.
inline int block_level(int max_level, int64_t tn) {
  if (tn <= 0) return 0;
  int c = 0;
  while (c < max_level && !((tn >> c) & 1)) ++c;
  return max_level - c;
}
}  // namespace detail

class Simulation {
 public:
  Simulation(const Particles& p, const Config& c);  // Uploads the data. Computes a and j. Selects the first steps.
  ~Simulation();
  Simulation(const Simulation&) = delete;
  Simulation& operator=(const Simulation&) = delete;

  void advance_to(double t);        // t: a multiple of dt_max, not less than time(). All particles are synchronized at t on return.
  double time() const;
  Particles state() const;          // Positions and velocities at time().
  std::vector<int> levels() const;  // Block level of each particle.
  Diagnostics diagnostics();        // K, U, E, P and L at time(). U costs N^2/2 pair evaluations.
  unsigned status() const;          // StatusBits
  Stats stats() const;
  Metrics metrics(bool reset = false);  // Host counters. reset = true sets them to 0 after the copy.
  RankProfile profile(bool reset = false);  // Phase times and bytes (MPI-M3). reset clears step counters only.

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

Particles load_text(const std::string& path);  // Lines "id m x y z vx vy vz". A line that starts with '#' is a comment.
void write_snapshot(const std::string& path, const Particles& p, double time);
// Renames tmp to path. On error it removes tmp and throws std::runtime_error. Use it after a checked close of tmp.
void publish_file(const std::string& tmp, const std::string& path);
Particles read_snapshot(const std::string& path, double* time = nullptr);
std::string build_info();  // "key: value" lines: commit, build type, architectures, CUDA versions, compiler. It does not throw.

// Several processes (contracts/public-api.md, section "Ranks"). The types are plain C++. The header has no MPI type.
// A build with H4NB_MPI=ON uses MPI when MPI is initialized and the process count is more than 1. Then each rank
// is one GPU, and a Simulation is collective: all ranks construct it with the same Particles and Config, and all
// ranks call each member function in the same order. In all other cases there is one rank: rank() = 0, ranks() = 1.
class RankScope {
 public:
  RankScope(int& argc, char**& argv);  // H4NB_MPI build: calls MPI_Init if MPI is not initialized. Other builds: no-op.
  ~RankScope();                        // Calls MPI_Finalize if this object called MPI_Init.
  RankScope(const RankScope&) = delete;
  RankScope& operator=(const RankScope&) = delete;

 private:
  bool owner_ = false;
};
int rank();                    // This process. 0 for one rank.
int ranks();                   // Number of processes. 1 for one rank.
int local_rank();              // Rank among the processes on this node. 0 for one rank.
int max_over_ranks(int value); // Collective. The largest value of all ranks, on every rank. Use it to agree on an error.
// Collective. One line for each rank, in rank order: host, local rank and the GPU that a Simulation will use
// (device_offset as in Config). Rank 0 gets all lines. The other ranks get an empty string. One rank: "".
std::string rank_table(int device_offset);
// Flushes all open C output streams, prints what, the rank and the rank count to stderr, and stops all ranks
// (MPI_Abort with code). Build without MPI: it calls std::exit(code). Use it for an error after which the ranks
// cannot agree (for example an exception on one rank only).
[[noreturn]] void abort_ranks(int code, const std::string& what);
// Sets a function that abort_ranks() and the MPI abort path of the library call before they stop the ranks.
// Use it to publish partial files. Null: no hook.
void set_abort_hook(void (*hook)());

}  // namespace h4nb
