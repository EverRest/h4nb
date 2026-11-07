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
enum StatusBits : unsigned { kNaN = 1u /* NaN or Inf */, kDtUnderflow = 2u, kClosePair = 4u };

struct Config {
  double G = 1.0;
  double eps2 = 0.0;          // Plummer softening squared. 0 means Newtonian gravity (default).
  double eta = 0.01;          // Aarseth accuracy parameter
  double eta_init = 0.01;     // first step: dt = eta_init * |a| / |j|
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

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

Particles load_text(const std::string& path);  // Lines "id m x y z vx vy vz". A line that starts with '#' is a comment.
void write_snapshot(const std::string& path, const Particles& p, double time);
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

}  // namespace h4nb
