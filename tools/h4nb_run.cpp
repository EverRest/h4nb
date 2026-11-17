// h4nb_run: runs a simulation. It writes the energy, momentum, timesteps and performance .dat files, and the snapshots.
// Usage: h4nb_run [config=<file>] ic=<file.txt|file.snap> out=<dir> t_end=<t> [key=value ...]
// "h4nb_run help=1" prints all keys with their defaults and ranges (contracts/run-config.md).
// t_end, diag, snap and each snap_times entry must be multiples of dt_max. t_end, snap and each snap_times entry
// must also be multiples of diag.
//
// Several ranks (MPI build, tasks T034 and T035): start it with mpirun or srun. The keys do not change.
// All ranks read the settings and the input. Only rank 0 writes files and prints the report.
// Error path ("hybrid", Pavlo, 2026-11-07):
//   - Settings, input and file errors: the ranks agree at fixed points (h4nb::max_over_ranks), and all ranks
//     return the same exit code (1 runtime, 2 settings or input, 3 NaN). The Simulation constructor and the
//     kNaN check of each block step are collective in the library.
//   - An error after which the ranks cannot agree (a CUDA error, an MPI error, an exception on one rank only):
//     flush the files, print the message with the rank, and stop all ranks (h4nb::abort_ranks, MPI_Abort).
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iterator>
#include <memory>
#include <string>
#include <vector>
#include "disk.hpp"
#include "energy_norm.hpp"
#include "h4nb/h4nb.hpp"
#include "run_info.hpp"
#include "input.hpp"
#include "settings.hpp"

using Clock = std::chrono::steady_clock;
static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

// std::max drops a NaN. This keeps it, so a NaN error stays visible in the verdict (review D8).
static double max_keep_nan(double a, double b) { return std::isnan(a) || std::isnan(b) ? NAN : std::max(a, b); }

// Energy verdict over the reference period T (task T014, FR-012, SC-001). It does not use the Simulation.
// Period k (k = 1, 2, ...) holds the diag points with time in ((k-1)T, kT]. The point at t = 0 is in no period.
// A time within a relative tolerance of 1e-12 of kT belongs to period k.
// The max is over the diag samples only. Diag points seldom land exactly on kT, and the error between two
// diag points is not seen. A smaller diag gives a finer sample.
struct PeriodTracker {
  struct Row {
    double max = 0, sum = 0;
    long n = 0;  // Diag points in the period. 0: the period has no sample, and max and mean are nan.
    bool complete = false;
  };
  double T;
  std::vector<Row> rows;  // rows[k-1] is period k.

  explicit PeriodTracker(double period) : T(period) {}
  // The period that holds time t. 0 for t = 0.
  long long index(double t) const {
    const double q = t / T, r = std::nearbyint(q);
    if (std::fabs(q - r) <= 1e-12 * std::fmax(1.0, q)) return (long long)r;
    return (long long)std::ceil(q);
  }
  void add(double t, double err) {
    const long long k = index(t);
    if (k < 1) return;
    if (rows.size() < size_t(k)) rows.resize(size_t(k));
    Row& r = rows[size_t(k - 1)];
    r.max = max_keep_nan(r.max, err);
    r.sum += err;
    ++r.n;
  }
  // Adds a row for each period that [0, t_end] touches. Period k is complete when kT <= t_end (tolerance 1e-12).
  void finish(double t_end) {
    const long long touched = index(t_end);
    if (rows.size() < size_t(touched)) rows.resize(size_t(touched));
    const double q = t_end / T, r = std::nearbyint(q);
    const long long done = std::fabs(q - r) <= 1e-12 * std::fmax(1.0, q) ? (long long)r : (long long)std::floor(q);
    for (size_t k = 1; k <= rows.size(); ++k) rows[k - 1].complete = (long long)k <= done;
  }
  void write(FILE* f) const {
    std::fprintf(f, "# period t_start t_end max_rel_err mean_rel_err complete\n");
    for (size_t k = 1; k <= rows.size(); ++k) {
      const Row& r = rows[k - 1];
      const double mx = r.n ? r.max : NAN, mean = r.n ? r.sum / double(r.n) : NAN;
      std::fprintf(f, "%zu %.17g %.17g %.6e %.6e %d\n", k, double(k - 1) * T, double(k) * T, mx, mean, r.complete ? 1 : 0);
    }
  }
  // One line that starts with "energy verdict:". PASS or FAIL needs a complete period 1 with a sample.
  std::string verdict(double tol, const std::string& src, double eps, double t_end) const {
    char b[512];
    std::string line;
    const Row* p1 = rows.empty() ? nullptr : &rows[0];
    if (!p1 || !p1->complete || p1->n == 0) {
      if (p1 && p1->n)
        std::snprintf(b, sizeof b, "energy verdict: INCOMPLETE max_rel_err=%.3e in (0, t_end=%.17g], energy_tol=%g, T=%.17g (%s), eps=%g. t_end must be >= period",
                      p1->max, t_end, tol, T, src.c_str(), eps);
      else
        std::snprintf(b, sizeof b, "energy verdict: INCOMPLETE no diag point in (0, T], energy_tol=%g, T=%.17g (%s), eps=%g. Set t_end >= period and diag <= period",
                      tol, T, src.c_str(), eps);
      line = b;
    } else {
      std::snprintf(b, sizeof b, "energy verdict: %s max_rel_err(period 1)=%.3e energy_tol=%g T=%.17g (%s) eps=%g",
                    p1->max <= tol ? "PASS" : "FAIL", p1->max, tol, T, src.c_str(), eps);
      line = b;
      // Runs with two or more complete periods: the max over the complete periods, and the drift.
      // drift = max_rel_err of the last complete period with a sample minus max_rel_err of period 1.
      double all = 0, last = p1->max;
      int complete = 0;
      for (const Row& r : rows)
        if (r.complete) {
          ++complete;
          if (r.n) all = max_keep_nan(all, r.max), last = r.max;
        }
      if (complete >= 2) {
        std::snprintf(b, sizeof b, " periods=%d max_rel_err(complete periods)=%.3e drift=%.3e", complete, all, last - p1->max);
        line += b;
      }
    }
    if (eps > 0) {
      std::snprintf(b, sizeof b, " (softened model, eps=%g; the 1e-8 criterion of the spec applies to the unsoftened model)", eps);
      line += b;
    }
    return line;
  }
};

// Declares the keys of h4nb_run (contracts/run-config.md section 5).
static void declare(Settings& s) {
  using T = Setting;
  s.add("ic", T::String, "", "Initial conditions. .snap is binary. Other names are text \"id m x y z vx vy vz\".").required = true;
  s.add("n", T::Int, "0", "Expected particle count, central body included. 0 turns the check off.", Range::ge(0));
  s.add("central_id", T::Int, "0", "The ID that record 0 must have.");
  s.add("out", T::String, "", "Output directory.").required = true;
  s.add("t_end", T::Real, "", "End time. A multiple of dt_max and of diag.", Range::gt(0)).required = true;
  s.add("period", T::Real, "0", "Reference orbital period for the energy verdict. 0: estimate from the initial state.",
        Range::ge(0));
  s.add("period_kind", T::Enum, "mean", "The estimate used when period=0.", Range::one_of({"mean", "median", "mass_weighted"}));
  s.add_preset();
  s.add("G", T::Real, "1", "Gravitational constant.", Range::gt(0));
  s.add("eps", T::Real, "0", "Plummer softening length. The library receives eps^2.", Range::ge(0));
  s.add("fixed_center", T::Bool, "0", "Particle 0 does not move. Tests and comparisons only.");
  s.add("dissipation", T::Enum, "off", "Dissipation model. linear_drag: a_diss = -(v - drag_vbg) / drag_tau, not on particle 0.",
        Range::one_of({"off", "linear_drag"}));
  s.add("drag_tau", T::Real, "0", "Drag time scale. Must be > 0 with dissipation=linear_drag.", Range::ge(0));
  s.add("drag_vbg", T::RealList, "0,0,0", "Background velocity vx,vy,vz of the drag.", Range().size(3));
  s.add("mode", T::Enum, "block", "Block steps or one shared step.", Range::one_of({"block", "fixed"}));
  s.add("eta", T::Real, "0.01", "Aarseth accuracy parameter.", Range::gt(0));
  s.add("eta_init", T::Real, "0", "First step: Aarseth dt at t = 0 with eta_init. 0 (default) uses eta.", Range::ge(0));
  s.add("dt_max", T::Real, "0.015625", "Step of level 0.", Range::gt(0).power_of_two());
  s.add("max_level", T::Int, "40", "dt_min = dt_max / 2^max_level.", Range::between(1, 50));
  s.add("fixed_level", T::Int, "0", "Level of all particles in fixed mode. Not more than max_level.", Range::ge(0));
  s.add("r_close", T::Real, "-1", "Close-pair radius. -1: 0.1 of the mean spacing R_rms/N^(1/3). 0: off.",
        Range::ge(0).or_value(-1));
  s.add("devices", T::IntList, "0", "CUDA device IDs. A repeated ID emulates more GPUs on one card.", Range::ge(0));
  s.add("tile", T::Int, "128", "Targets per block in the force and potential kernels.", Range::one_of({"64", "128", "256"}));
  s.add("blocks_per_sm", T::Int, "4", "Target blocks per SM for the source split.", Range::between(1, 16));
  s.add("device_offset", T::Int, "0", "MPI only. GPU of a rank: (local rank + device_offset) % device count.",
        Range::ge(0));
  s.add("mpi_host_staging", T::Bool, "0", "MPI only. 1: copy the MPI buffers through pinned host memory (MPI is not CUDA-aware).");
  s.add("diag", T::Real, "", "Interval of the energy and momentum records. No value: dt_max.", Range::gt(0));
  s.add("snap", T::Real, "0", "Snapshot interval, a multiple of diag. 0 and no snap_times: only the final snapshot.", Range::ge(0));
  s.add("snap_times", T::RealList, "", "Explicit snapshot times, multiples of diag. Do not set it with snap.", Range::ge(0));
  s.add("energy_tol", T::Real, "1e-8", "Threshold for the energy verdict. It does not change the integration.", Range::gt(0));
  s.add("energy_norm", T::Enum, "e0", "Relative energy error. e0: divide by |E0|. ku: divide by |K0|+|U0|.",
        Range::one_of({"e0", "ku"}));
  s.add("perf", T::Bool, "1", "Write performance.dat.");
}

// The point that the run has reached. main() uses it to select the error path of a rank.
enum class Phase { Setup, Files, Run };
static Phase g_phase = Phase::Setup;

// Rank 0 records the first error of a file write here. The ranks agree on it at the next diag point.
static int g_file_error = 0;
static void file_error(const std::string& what) {
  if (!g_file_error) std::fprintf(stderr, "h4nb_run: error: %s\n", what.c_str());
  g_file_error = 1;
}

// The .dat files are written to name.tmp. They get their final name after a checked close (D1). On an early exit,
// the partial files get their final name too. Only a close error removes them. run() sets g_publish to close_all.
static const char* const kDatNames[5] = {"energy.dat", "momentum.dat", "timesteps.dat", "performance.dat",
                                         "energy_periods.dat"};
static std::function<void()> g_publish;

// The generic error that the constructor throws on a rank without an error of its own (src/simulation.cu).
// The text is the same as in construct_mpi(). Such a rank does not print it. The rank with the local error prints.
static bool remote_setup_error(const std::exception& e) {
  return std::string(e.what()).rfind("Simulation: the setup failed on another rank", 0) == 0;
}

// Agreement of the ranks on a setup error (the settings and input checks). All ranks call it at the same point:
// the ranks without an error from run(), a rank with an error from main() or from run(). code: 0, or the exit code of
// this rank. It returns the largest code of all ranks. A local error is printed by rank 0, or by the failed ranks when
// rank 0 has no local error. Thus a settings error that all ranks see is printed one time.
static int agree_setup(int code, const std::exception* e) {
  const int all = h4nb::max_over_ranks(code);
  if (!all) return 0;
  const bool local = e && !remote_setup_error(*e);
  const int root_code = h4nb::max_over_ranks(h4nb::rank() == 0 && local ? code : 0);  // Second collective, only on error.
  if (local && (h4nb::rank() == 0 || root_code == 0)) {
    if (h4nb::ranks() > 1) std::fprintf(stderr, "h4nb_run: rank %d of %d:\n", h4nb::rank(), h4nb::ranks());
    settings_main_error("h4nb_run", *e);
  }
  return all;
}

// Input fingerprint (MPI-H1). Each rank computes it from its own settings and input file. The ranks compare it
// before the first collective of the run. The entries are "name=text". The text of a number is its value.
struct InputEntry {
  std::string name, text;
};

// FNV-1a 64-bit hash of n bytes. h continues a hash. The default is the offset basis.
static uint64_t fnv1a(const void* data, size_t n, uint64_t h = 0xcbf29ce484222325ULL) {
  const unsigned char* b = static_cast<const unsigned char*>(data);
  for (size_t i = 0; i < n; ++i) h = (h ^ b[i]) * 0x100000001b3ULL;
  return h;
}

static std::string hex64(uint64_t v) {
  char b[17];
  std::snprintf(b, sizeof b, "%016llx", static_cast<unsigned long long>(v));
  return b;
}

// The entries in a fixed order: one per declared key, then "help" and "ic bytes". The entry count is the same on all
// ranks. help=1 reads no input, so "ic bytes" is "-" then. An unreadable file has the text "unreadable".
// The error of an unreadable file comes later, from load_input().
static std::vector<InputEntry> input_entries(const Settings& s, bool help) {
  std::vector<InputEntry> out;
  for (const Setting& k : s.keys()) {
    if (k.name == "out") continue;  // Only rank 0 writes files. A rank-local out directory is not a mismatch.
    std::string text = k.value;  // The value as the source gave it.
    if (!k.value.empty() && k.type == Setting::Real) {
      char b[32];
      std::snprintf(b, sizeof b, "%.17g", s.real(k.name));  // "1e-2" and "0.01" give the same text.
      text = b;
    } else if (!k.value.empty() && k.type == Setting::Int) {
      text = std::to_string(s.integer(k.name));
    }
    out.push_back({k.name, text});
  }
  out.push_back({"help", help ? "1" : "0"});
  std::string ic = "-";
  if (!help) {
    std::ifstream f(s.str("ic"), std::ios::binary);
    if (f) {
      const std::string bytes((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
      ic = hex64(fnv1a(bytes.data(), bytes.size()));
    } else {
      ic = "unreadable";
    }
  }
  out.push_back({"ic bytes", ic});
  return out;
}

// The fingerprint of all entries. The field separators keep "a=b" and "ab=" apart.
static uint64_t entries_digest(const std::vector<InputEntry>& entries) {
  uint64_t h = fnv1a(nullptr, 0);
  for (const InputEntry& x : entries) {
    const std::string line = x.name + "=" + x.text + "\n";
    h = fnv1a(line.data(), line.size(), h);
  }
  return h;
}

// True when v has the same value on all ranks. It uses max_over_ranks() only, so it links in both builds.
// The min of a 16-bit chunk c is 0xffff - max(0xffff - c). Four chunks cover the 64 bits.
static bool same_on_all(uint64_t v) {
  bool same = true;
  for (int shift = 0; shift < 64; shift += 16) {
    const int c = int((v >> shift) & 0xffff);
    const int hi = h4nb::max_over_ranks(c), lo = 0xffff - h4nb::max_over_ranks(0xffff - c);
    if (hi != lo) same = false;
  }
  return same;
}

// Agreement point 0 (MPI-H1). All ranks call it once, in the same order, before the help return. It returns 0 when
// all ranks have the same input fingerprint and no error. Otherwise it returns the exit code. A rank with a parse error
// comes to agree_setup() from main() instead. That call makes the same collective. On a mismatch, each rank prints
// the entries that differ, with its own text.
static int agree_inputs(const Settings& s, bool help) {
  const std::vector<InputEntry> entries = input_entries(s, help);
  if (const int code = agree_setup(0, nullptr)) return code;
  if (same_on_all(entries_digest(entries))) return 0;
  for (const InputEntry& x : entries)
    if (!same_on_all(fnv1a(x.text.data(), x.text.size())))
      std::fprintf(stderr, "h4nb_run: rank %d of %d: the value of %s differs between the ranks (this rank: %s)\n",
                   h4nb::rank(), h4nb::ranks(), x.name.c_str(), x.text.c_str());
  return 2;
}

static int run(int argc, char** argv) {
  const bool root = h4nb::rank() == 0;  // Only rank 0 writes files and prints.
  Settings s;
  declare(s);
  s.parse(argc, argv);
  // Agreement point 0 (MPI-H1). It comes before the help return, so help=1 must be the same on all ranks.
  if (const int code = agree_inputs(s, s.help())) return code;
  if (s.help()) {
    if (root) s.print_help(stdout, "h4nb_run");
    return 0;
  }
  // Checks across keys. Each error names the key, its value and its source.
  // snap=0 means "no interval". It does not conflict with snap_times.
  if (s.real("snap") > 0 && s.has_value("snap_times")) s.fail("snap_times", "do not set it with snap");
  if (s.integer("fixed_level") > s.integer("max_level")) s.fail("fixed_level", "more than max_level");
  const bool drag = s.str("dissipation") == "linear_drag";
  if (drag && !(s.real("drag_tau") > 0)) s.fail("drag_tau", "must be > 0 with dissipation=linear_drag");
  const double dt_max = s.real("dt_max");
  const double t_end = s.real("t_end"), diag = s.has_value("diag") ? s.real("diag") : dt_max, snap = s.real("snap");
  // The value v of key k must be n * step with an integer n >= 1 (n >= 0 when zero_ok). The tool does not round it.
  auto need_multiple = [&](const char* k, double v, double step, const char* step_name, bool zero_ok) {
    if (!is_multiple(v, step) || (!zero_ok && std::llround(v / step) < 1)) {
      char why[128];
      std::snprintf(why, sizeof why, "not a multiple of %s=%.17g", step_name, step);
      s.fail(k, why);
    }
  };
  need_multiple("t_end", t_end, dt_max, "dt_max", false);
  if (s.has_value("diag")) need_multiple("diag", diag, dt_max, "dt_max", false);
  need_multiple("t_end", t_end, diag, "diag", false);
  if (snap > 0) {
    need_multiple("snap", snap, dt_max, "dt_max", false);
    need_multiple("snap", snap, diag, "diag", false);
  }
  // The runner stops only at the diag times. Thus it can write a snapshot only at a diag time.
  // Each snap_times entry must be a multiple of dt_max and of diag, and not more than t_end.
  // snap_index holds the diag segment index of each snapshot time, in increasing order.
  std::vector<long long> snap_index;
  for (double t : s.reals("snap_times")) {
    need_multiple("snap_times", t, dt_max, "dt_max", true);
    need_multiple("snap_times", t, diag, "diag", true);
    if (t > t_end) s.fail("snap_times", "a time is more than t_end");
    snap_index.push_back(std::llround(t / diag));
  }
  std::sort(snap_index.begin(), snap_index.end());
  if (std::adjacent_find(snap_index.begin(), snap_index.end()) != snap_index.end()) s.fail("snap_times", "a time is repeated");

  h4nb::Config c;
  c.G = s.real("G");
  c.eps2 = std::pow(s.real("eps"), 2);  // The tool takes eps. The library takes eps^2.
  c.eta = s.real("eta");
  c.eta_init = s.real("eta_init");
  c.dt_max = dt_max;
  c.max_level = s.integer("max_level");
  c.mode = s.str("mode") == "fixed" ? h4nb::StepMode::Fixed : h4nb::StepMode::Block;
  c.fixed_level = s.integer("fixed_level");
  c.fixed_center = s.boolean("fixed_center");
  c.dissipation = drag ? h4nb::Dissipation::LinearDrag : h4nb::Dissipation::Off;
  c.drag_tau = s.real("drag_tau");
  for (int k = 0; k < 3; ++k) c.drag_vbg[k] = s.reals("drag_vbg")[k];
  c.devices = s.ints("devices");
  c.tile = s.integer("tile");
  c.blocks_per_sm = s.integer("blocks_per_sm");
  c.device_offset = s.integer("device_offset");
  c.mpi_host_staging = s.boolean("mpi_host_staging");
  const int nranks = h4nb::ranks();
  const bool perf = s.boolean("perf");
  const double energy_tol = s.real("energy_tol");
  const std::string ic = s.str("ic"), out = s.str("out");
  const h4nb::Particles p = load_input(ic);
  if (s.integer("n") > 0 && p.size() != size_t(s.integer("n")))
    s.fail("n", "the file " + ic + " has " + std::to_string(p.size()) + " particles");
  if (p.size() == 0 || p.id[0] != s.integer("central_id"))
    s.fail("central_id", "record 0 must be the central body with id " + std::to_string(s.integer("central_id")) +
                             (p.size() ? ", but it has id " + std::to_string(p.id[0]) : ", but the file has no records"));
  // Reference period for the energy verdict (task T014): the value of period, or the estimate of period_kind.
  double period = s.real("period");
  std::string period_src = "period, " + s.source("period");
  if (!(period > 0)) {
    // ponytail: periods() uses G = 1. Set period when G is not 1.
    if (c.G != 1.0) s.fail("period", "the period estimate needs G=1. Set period");
    const Periods est = periods(p);
    const std::string& kind = s.str("period_kind");
    period = kind == "median" ? est.median : kind == "mass_weighted" ? est.mass_weighted : est.mean;
    if (!(period > 0)) s.fail("period", "no particle is bound to record 0, thus no period estimate. Set period");
    period_src = "estimate " + kind + " of the initial state";
  }
  const double N = double(p.size());
  double R2 = 0;
  for (size_t i = 0; i < p.size(); ++i) R2 += p.x[i] * p.x[i] + p.y[i] * p.y[i] + p.z[i] * p.z[i];
  // Default close-pair radius: 0.1 times the mean spacing R_rms / N^(1/3) of the initial state.
  // ponytail: a rough guess for a disk. Set r_close explicitly when the system has another scale.
  const double r_close_arg = s.real("r_close");
  const double r_close = r_close_arg >= 0 ? r_close_arg : 0.1 * std::sqrt(R2 / N) / std::cbrt(N);
  c.r2_close = r_close * r_close;
  // Agreement point 1: all ranks passed the settings and input checks. A rank that failed is in main(),
  // and it calls h4nb::max_over_ranks() with its exit code. Thus all ranks return the same code.
  if (const int code = agree_setup(0, nullptr)) return code;
  g_phase = Phase::Files;
  const std::string rank_lines = h4nb::rank_table(c.device_offset);  // Collective. Empty for one rank.
  FILE *fe = nullptr, *fm = nullptr, *ft = nullptr, *fp = nullptr, *fv = nullptr;
  if (root) {
    try {
      std::printf("h4nb_run: preset=%s eps2=%g eta=%g dt_max=%g period=%.17g (%s) energy_tol=%g\n", s.str("preset").c_str(),
                  c.eps2, c.eta, c.dt_max, period, period_src.c_str(), energy_tol);
      if (nranks > 1 && s.is_set("devices"))
        std::printf("h4nb_run: ranks=%d. The devices key is ignored. Each rank uses one GPU (device_offset=%d).\n",
                    nranks, c.device_offset);
      std::fflush(stdout);
      std::filesystem::create_directories(out);
      s.write_used(out + "/config.used", "h4nb_run");
      write_run_info(out + "/run_info.txt", "h4nb_run", c.devices, argc, argv, rank_lines);
      fe = std::fopen((out + "/energy.dat.tmp").c_str(), "w");
      fm = std::fopen((out + "/momentum.dat.tmp").c_str(), "w");
      ft = std::fopen((out + "/timesteps.dat.tmp").c_str(), "w");
      fp = perf ? std::fopen((out + "/performance.dat.tmp").c_str(), "w") : nullptr;
      fv = std::fopen((out + "/energy_periods.dat.tmp").c_str(), "w");
      if (!fe || !fm || !ft || !fv || (perf && !fp)) throw std::runtime_error("cannot write into " + out);
      // rel_err = |E - E0 - W_diss| / D, D = |E0| (energy_norm=e0) or |K0| + |U0| (ku). W_diss is the work of the dissipative force since t = 0 (0 with dissipation=off).
      std::fprintf(fe, "# time K U E rel_err max_rel_err mean_rel_err W_diss\n");
      std::fprintf(fm, "# time Px Py Pz Lx Ly Lz dP_rel dL_rel  (changes divided by sum m|v| and sum m|r x v| of the initial state, TZ 7.3)\n");
      std::fprintf(ft, "# time dt_min dt_max dt_mean mean_active_per_block_step r_min\n");
      // Schema 2 (MPI-M3): old columns first, then phase summary from RankProfile on this rank (rank 0).
      if (fp)
        std::fprintf(fp,
                     "# time wall_s block_steps active pairs_per_s wall_max wall_min compute_imb comm_frac "
                     "t_diag_max bytes_max t_tn t_select t_gather t_force t_xchg t_correct\n");
    } catch (const std::exception& e) {
      file_error(e.what());
    }
  }
  // Closes the open .dat files. A file that closed without error gets its final name. Otherwise, its .tmp file is
  // removed. A publish error sets the file error on rank 0. Each call publishes the partial records of a run that ends early.
  auto close_all = [&]() {
    FILE** slots[5] = {&fe, &fm, &ft, &fp, &fv};
    for (int i = 0; i < 5; ++i) {
      if (!*slots[i]) continue;
      const bool write_err = std::ferror(*slots[i]) != 0;  // Read before fclose: the stream is invalid after it (L3).
      const bool ok = std::fclose(*slots[i]) == 0 && !write_err;
      *slots[i] = nullptr;
      const std::string tmp = out + "/" + kDatNames[i] + ".tmp";
      if (!ok) file_error("cannot write the .dat files in " + out);
      if (ok && !g_file_error) {
        try {
          h4nb::publish_file(tmp, out + "/" + kDatNames[i]);
        } catch (const std::exception& e) {
          file_error(e.what());
        }
      } else {
        std::remove(tmp.c_str());
      }
    }
  };
  // The exit guard and the abort hook (main) call close_all. They run after an exception and before fatal() stops.
  g_publish = [&] { close_all(); };
  struct PublishOnExit {
    ~PublishOnExit() {
      if (g_publish) g_publish();
      g_publish = nullptr;
    }
  } publish_on_exit;
  // Agreement point 2: rank 0 could write the first files.
  if (const int code = h4nb::max_over_ranks(g_file_error)) {
    close_all();
    return code;
  }

  // The constructor is collective: an error in its checks throws on all ranks (library, task T034).
  std::unique_ptr<h4nb::Simulation> simp;
  try {
    simp = make_simulation(p, c);
  } catch (const std::exception& e) {
    close_all();
    if (nranks == 1) return settings_main_error("h4nb_run", e);
    // The constructor throws on all ranks, so all ranks call the agreement. It prints the local error of each rank.
    return agree_setup(dynamic_cast<const SettingsError*>(&e) ? 2 : 1, &e);
  }
  // status() is collective: all ranks call it, and they get the same bits.
  const unsigned init_status = simp->status();
  if (init_status & h4nb::kNaN) {
    // A non-finite first force. With eps = 0, two particles at one point give this (review D5). It is an input error.
    close_all();
    if (root)
      std::fprintf(stderr, "h4nb_run: error: the initial state gives a non-finite force (NaN or Inf). Check for two "
                           "particles at the same position. With eps = 0, set eps > 0 or remove one particle.\n");
    return 2;
  }
  if (root && (init_status & h4nb::kInitStepInvalid))
    std::fprintf(stderr, "warning: the first step estimate is not finite. The coarsest level (dt_max) is used.\n");
  g_phase = Phase::Run;
  h4nb::Simulation& sim = *simp;
  const h4nb::Metrics mx0 = sim.metrics();  // Start-up times. metrics(true) does not clear them.
  if (root) {
    if (nranks > 1)
      std::printf("N=%zu ranks=%d: init (one full force pass) %.3f s, %.3e pairs/s\n", p.size(), nranks, mx0.init_force_s,
                  N * (N - 1) / mx0.init_force_s);
    else
      std::printf("N=%zu devices=%zu: init (one full force pass) %.3f s, %.3e pairs/s\n", p.size(), c.devices.size(),
                  mx0.init_force_s, N * (N - 1) / mx0.init_force_s);
    std::printf("init (initial levels) %.3f s\n", mx0.init_levels_s);
  }
  char dissipation_text[160] = "dissipation=off";
  if (drag)
    std::snprintf(dissipation_text, sizeof dissipation_text, "dissipation=linear_drag drag_tau=%g drag_vbg=%g,%g,%g",
                  c.drag_tau, c.drag_vbg[0], c.drag_vbg[1], c.drag_vbg[2]);
  if (root) std::printf("%s\n", dissipation_text);
  const h4nb::Diagnostics d0 = sim.diagnostics();
  const std::string energy_norm = s.str("energy_norm");
  if (const std::string msg = energy_norm_error(energy_norm, d0.E); !msg.empty()) {
    close_all();
    if (root) std::fprintf(stderr, "h4nb_run: error: %s\n", msg.c_str());
    return 2;
  }
  bool close_warned = false;
  double max_err = 0, err_sum = 0;
  bool nonfinite_err = false;  // A relative error is not finite. The run then fails with exit code 3 (review D8).
  long err_n = 0;
  PeriodTracker tracker(period);
  double p_scale = 0, l_scale = 0;  // Scales from the initial state. Set to 1 when zero, to avoid division by zero.
  for (size_t i = 0; i < p.size(); ++i) {
    p_scale += p.m[i] * std::sqrt(p.vx[i] * p.vx[i] + p.vy[i] * p.vy[i] + p.vz[i] * p.vz[i]);
    const double lx = p.y[i] * p.vz[i] - p.z[i] * p.vy[i], ly = p.z[i] * p.vx[i] - p.x[i] * p.vz[i],
                 lz = p.x[i] * p.vy[i] - p.y[i] * p.vx[i];
    l_scale += p.m[i] * std::sqrt(lx * lx + ly * ly + lz * lz);
  }
  if (!(p_scale > 0)) p_scale = 1;
  if (!(l_scale > 0)) l_scale = 1;
  auto write_diag = [&](const h4nb::Diagnostics& d) {
    const double err = rel_energy_error(d.E, d0.E, d.W_diss, d0.K, d0.U, energy_norm);
    if (!std::isfinite(err)) nonfinite_err = true;
    max_err = max_keep_nan(max_err, err);
    err_sum += err;
    ++err_n;
    tracker.add(d.time, err);
    if (!root) return;
    const double dP = std::sqrt(std::pow(d.P[0] - d0.P[0], 2) + std::pow(d.P[1] - d0.P[1], 2) + std::pow(d.P[2] - d0.P[2], 2));
    const double dL = std::sqrt(std::pow(d.L[0] - d0.L[0], 2) + std::pow(d.L[1] - d0.L[1], 2) + std::pow(d.L[2] - d0.L[2], 2));
    std::fprintf(fe, "%.17g %.17g %.17g %.17g %.6e %.6e %.6e %.17g\n", d.time, d.K, d.U, d.E, err, max_err,
                 err_sum / double(err_n), d.W_diss);
    std::fprintf(fm, "%.17g %.17g %.17g %.17g %.17g %.17g %.17g %.6e %.6e\n", d.time, d.P[0], d.P[1], d.P[2], d.L[0],
                 d.L[1], d.L[2], dP / p_scale, dL / l_scale);
  };
  write_diag(d0);
  const long long nseg = std::llround(t_end / diag), snap_every = snap > 0 ? std::llround(snap / diag) : 0;
  // snap: the file index is k / snap_every. snap_times: the file index counts the listed times from 0.
  size_t next_snap = 0;
  auto write_snap = [&](long long k) {
    long long index = -1;
    if (snap_every && k % snap_every == 0) index = k / snap_every;
    if (next_snap < snap_index.size() && snap_index[next_snap] == k) index = (long long)next_snap++;
    if (index < 0) return;
    char name[64];
    std::snprintf(name, sizeof name, "/snap_%06lld.snap", index);
    const h4nb::Particles st = sim.state();  // Collective: every rank gets the full set (MPI_Allgatherv).
    if (root && !g_file_error) try {
        h4nb::write_snapshot(out + name, st, sim.time());
      } catch (const std::exception& e) {
        file_error(e.what());
      }
  };
  write_snap(0);
  for (long long k = 1; k <= nseg; ++k) {
    const h4nb::Stats s0 = sim.stats();
    (void)sim.profile(true);  // Clear phase counters for this diag segment (MPI-M3).
    const auto w0 = Clock::now();
    sim.advance_to(double(k) * diag);
    const double wall = since(w0);
    const h4nb::Stats s1 = sim.stats();
    const h4nb::RankProfile pr = sim.profile(true);
    const long long steps = s1.block_steps - s0.block_steps, active = s1.active_total - s0.active_total;
    if (fp) {
      const double compute = pr.t_select + pr.t_force + pr.t_correct;
      const double comm = pr.t_gather + pr.t_xchg;
      const double phases = compute + comm + pr.t_tn;
      const double compute_imb = 1.0;  // One rank here; multi-rank gather is a later MPI-M3 slice.
      const double comm_frac = phases > 0 ? comm / phases : 0.0;
      const double bytes_max = double(pr.bytes_sent > pr.bytes_recv ? pr.bytes_sent : pr.bytes_recv);
      std::fprintf(fp,
                   "%.17g %.6f %lld %lld %.6e %.6f %.6f %.6f %.6f %.6f %.6e %.6e %.6e %.6e %.6e %.6e %.6e\n",
                   sim.time(), wall, steps, active, double(active) * N / wall, wall, wall, compute_imb, comm_frac, 0.0,
                   bytes_max, pr.t_tn, pr.t_select, pr.t_gather, pr.t_force, pr.t_xchg, pr.t_correct);
    }
    // status() is collective (MPI_BOR). With several ranks, advance_to() stops at the first block step after
    // a rank sets kNaN. Then sim.time() is the time of that block step, before the diag time.
    if (sim.status() & h4nb::kNaN) {
      if (root) {
        tracker.finish(sim.time());
        tracker.write(fv);
        std::fprintf(stderr, "h4nb_run: non-finite value (NaN or Inf) at t=%g\n", sim.time());
      }
      close_all();  // The partial results are kept.
      return 3;  // Exit codes: 1 = runtime error, 2 = settings error, 3 = numerical failure.
    }
    write_diag(sim.diagnostics());
    if (nonfinite_err) {  // Same exit as a NaN state. All ranks see the same error: the diagnostics are collective.
      if (root) {
        tracker.finish(sim.time());
        tracker.write(fv);
        std::fprintf(stderr, "h4nb_run: non-finite relative energy error (NaN or Inf) at t=%g\n", sim.time());
      }
      close_all();
      return 3;
    }
    double dmin = 1e300, dmax = 0, dsum = 0;
    for (int lv : sim.levels()) {
      const double dt = c.dt_max / std::ldexp(1.0, lv);
      dmin = std::min(dmin, dt); dmax = std::max(dmax, dt); dsum += dt;
    }
    if (root) std::fprintf(ft, "%.17g %.6e %.6e %.6e %.3f %.6e\n", sim.time(), dmin, dmax, dsum / N,
                           steps ? double(active) / double(steps) : 0.0, std::sqrt(s1.min_r2));
    if (!close_warned && (sim.status() & h4nb::kClosePair)) {
      if (root)
        std::fprintf(stderr, "warning: a pair came closer than r_close (r_min = %g) by t = %g\n", std::sqrt(s1.min_r2),
                     sim.time());
      close_warned = true;
    }
    write_snap(k);
    for (FILE* f : {fe, fm, ft, fp})
      if (f && (std::fflush(f) != 0 || std::ferror(f))) file_error("cannot write the .dat files in " + out);
    // Agreement point at each diag time: a file error on rank 0 stops all ranks with exit code 1.
    if (const int code = h4nb::max_over_ranks(g_file_error)) {
      close_all();
      return code;
    }
  }
  // Write the final state unless t_end is a snapshot time. write_snap(nseg) wrote that one already (D3).
  const bool end_is_snap = (snap_every && nseg % snap_every == 0) || std::binary_search(snap_index.begin(), snap_index.end(), nseg);
  if (!end_is_snap) {
    const h4nb::Particles fin = sim.state();  // Collective.
    if (root) try {
        h4nb::write_snapshot(out + "/snap_final.snap", fin, sim.time());
      } catch (const std::exception& e) {
        file_error(e.what());
      }
  }
  const unsigned st = sim.status();
  if (root) {
    if (st & h4nb::kClosePair) std::fprintf(stderr, "warning: a pair came closer than r_close\n");
    if (st & h4nb::kDtUnderflow) std::fprintf(stderr, "warning: a particle needs dt < dt_min. Raise max_level.\n");
    std::printf("t=%g: max |dE/E| = %.3e, mean |dE/E| = %.3e\n", sim.time(), max_err, err_sum / double(err_n));
    tracker.finish(sim.time());
    tracker.write(fv);
    std::string verdict = tracker.verdict(energy_tol, period_src, s.real("eps"), sim.time());
    if (drag) verdict += " (energy balance E - E0 - W_diss, " + std::string(dissipation_text) + ")";
    std::printf("%s\n", verdict.c_str());
    close_all();
  }
  // Last agreement point: the final snapshot and the close of the files.
  if (const int code = h4nb::max_over_ranks(g_file_error)) return code;
  // The exit code is 0 for PASS, FAIL and INCOMPLETE. The verdict is a result, not an error.
  // Scripts read the "energy verdict:" line or energy_periods.dat.
  return 0;
}

int main(int argc, char** argv) {
  // fatal() (MPI_Abort) does not unwind, so it calls this hook first to publish the partial files.
  h4nb::set_abort_hook([] { if (g_publish) g_publish(); });
  std::unique_ptr<h4nb::RankScope> scope;
  try {
    scope = std::make_unique<h4nb::RankScope>(argc, argv);
  } catch (const std::exception& e) {
    return settings_main_error("h4nb_run", e);
  }
  try {
    return run(argc, argv);
  } catch (const std::exception& e) {
    const int n = h4nb::ranks();
    if (g_phase == Phase::Setup) {
      // A settings or input error. The other ranks wait at agreement point 1 (or they failed in the same way).
      if (n == 1) return settings_main_error("h4nb_run", e);
      return agree_setup(dynamic_cast<const SettingsError*>(&e) ? 2 : 1, &e);
    }
    if (n == 1) return settings_main_error("h4nb_run", e);
    // Several ranks, and the other ranks can wait in a collective. Flush the files and stop all ranks.
    h4nb::abort_ranks(1, std::string("h4nb_run: error: ") + e.what());
  }
}
