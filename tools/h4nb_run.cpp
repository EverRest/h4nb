// h4nb_run: runs a simulation. It writes the energy, momentum, timesteps and performance .dat files, and the snapshots.
// Usage: h4nb_run [config=<file>] ic=<file.txt|file.snap> out=<dir> t_end=<t> [key=value ...]
// "h4nb_run help=1" prints all keys with their defaults and ranges (contracts/run-config.md).
// t_end, diag, snap and each snap_times entry must be multiples of dt_max. t_end, snap and each snap_times entry
// must also be multiples of diag.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <string>
#include "disk.hpp"
#include "h4nb/h4nb.hpp"
#include "settings.hpp"

using Clock = std::chrono::steady_clock;
static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

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
  // Task T041 adds the model linear_drag and its keys drag_tau and drag_vbg.
  s.add("dissipation", T::Enum, "off", "Dissipation model.", Range::one_of({"off"}));
  s.add("mode", T::Enum, "block", "Block steps or one shared step.", Range::one_of({"block", "fixed"}));
  s.add("eta", T::Real, "0.01", "Aarseth accuracy parameter.", Range::gt(0));
  s.add("eta_init", T::Real, "0.01", "First step: eta_init*|a|/|j|.", Range::gt(0));
  s.add("dt_max", T::Real, "0.015625", "Step of level 0.", Range::gt(0).power_of_two());
  s.add("max_level", T::Int, "40", "dt_min = dt_max / 2^max_level.", Range::between(1, 50));
  s.add("fixed_level", T::Int, "0", "Level of all particles in fixed mode. Not more than max_level.", Range::ge(0));
  s.add("r_close", T::Real, "-1", "Close-pair radius. -1: 0.1 of the mean spacing R_rms/N^(1/3). 0: off.",
        Range::ge(0).or_value(-1));
  s.add("devices", T::IntList, "0", "CUDA device IDs. A repeated ID emulates more GPUs on one card.", Range::ge(0));
  s.add("tile", T::Int, "128", "Targets per block in the force and potential kernels.", Range::one_of({"64", "128", "256"}));
  s.add("blocks_per_sm", T::Int, "4", "Target blocks per SM for the source split.", Range::between(1, 16));
  s.add("diag", T::Real, "", "Interval of the energy and momentum records. No value: dt_max.", Range::gt(0));
  s.add("snap", T::Real, "0", "Snapshot interval, a multiple of diag. 0 and no snap_times: only the final snapshot.", Range::ge(0));
  s.add("snap_times", T::RealList, "", "Explicit snapshot times, multiples of diag. Do not set it with snap.", Range::ge(0));
  s.add("energy_tol", T::Real, "1e-8", "Threshold for the energy verdict. It does not change the integration.", Range::gt(0));
  s.add("perf", T::Bool, "1", "Write performance.dat.");
}

int main(int argc, char** argv) try {
  Settings s;
  declare(s);
  s.parse(argc, argv);
  if (s.help()) {
    s.print_help(stdout, "h4nb_run");
    return 0;
  }
  // Checks across keys. Each error names the key, its value and its source.
  // snap=0 means "no interval". It does not conflict with snap_times.
  if (s.real("snap") > 0 && s.has_value("snap_times")) s.fail("snap_times", "do not set it with snap");
  if (s.integer("fixed_level") > s.integer("max_level")) s.fail("fixed_level", "more than max_level");
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
  c.devices = s.ints("devices");
  c.tile = s.integer("tile");
  c.blocks_per_sm = s.integer("blocks_per_sm");
  const bool perf = s.boolean("perf");
  // energy_tol is only printed now. Task T014 adds the pass or fail verdict with it.
  const double energy_tol = s.real("energy_tol");
  const std::string ic = s.str("ic"), out = s.str("out");
  const bool binary = ic.size() > 5 && ic.compare(ic.size() - 5, 5, ".snap") == 0;
  const h4nb::Particles p = binary ? h4nb::read_snapshot(ic) : h4nb::load_text(ic);
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
  std::printf("h4nb_run: preset=%s eps2=%g eta=%g dt_max=%g period=%.17g (%s) energy_tol=%g\n", s.str("preset").c_str(),
              c.eps2, c.eta, c.dt_max, period, period_src.c_str(), energy_tol);
  std::fflush(stdout);
  std::filesystem::create_directories(out);
  s.write_used(out + "/config.used", "h4nb_run");
  FILE* fe = std::fopen((out + "/energy.dat").c_str(), "w");
  FILE* fm = std::fopen((out + "/momentum.dat").c_str(), "w");
  FILE* ft = std::fopen((out + "/timesteps.dat").c_str(), "w");
  FILE* fp = perf ? std::fopen((out + "/performance.dat").c_str(), "w") : nullptr;
  if (!fe || !fm || !ft || (perf && !fp)) throw std::runtime_error("cannot write into " + out);
  std::fprintf(fe, "# time K U E rel_err max_rel_err mean_rel_err\n");
  std::fprintf(fm, "# time Px Py Pz Lx Ly Lz dP_rel dL_rel  (changes divided by sum m|v| and sum m|r x v| of the initial state, TZ 7.3)\n");
  std::fprintf(ft, "# time dt_min dt_max dt_mean mean_active_per_block_step r_min\n");
  if (fp) std::fprintf(fp, "# time wall_s block_steps active pairs_per_s\n");

  const auto t0 = Clock::now();
  h4nb::Simulation sim(p, c);
  const double t_init = since(t0);
  std::printf("N=%zu devices=%zu: init (one full force pass) %.3f s, %.3e pairs/s\n", p.size(), c.devices.size(),
              t_init, N * (N - 1) / t_init);
  const h4nb::Diagnostics d0 = sim.diagnostics();
  bool close_warned = false;
  double max_err = 0, err_sum = 0;
  long err_n = 0;
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
    const double err = std::fabs((d.E - d0.E) / d0.E);
    max_err = std::max(max_err, err);
    err_sum += err;
    ++err_n;
    const double dP = std::sqrt(std::pow(d.P[0] - d0.P[0], 2) + std::pow(d.P[1] - d0.P[1], 2) + std::pow(d.P[2] - d0.P[2], 2));
    const double dL = std::sqrt(std::pow(d.L[0] - d0.L[0], 2) + std::pow(d.L[1] - d0.L[1], 2) + std::pow(d.L[2] - d0.L[2], 2));
    std::fprintf(fe, "%.17g %.17g %.17g %.17g %.6e %.6e %.6e\n", d.time, d.K, d.U, d.E, err, max_err, err_sum / double(err_n));
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
    h4nb::write_snapshot(out + name, sim.state(), sim.time());
  };
  write_snap(0);
  for (long long k = 1; k <= nseg; ++k) {
    const h4nb::Stats s0 = sim.stats();
    const auto w0 = Clock::now();
    sim.advance_to(double(k) * diag);
    const double wall = since(w0);
    const h4nb::Stats s1 = sim.stats();
    const long long steps = s1.block_steps - s0.block_steps, active = s1.active_total - s0.active_total;
    if (fp) std::fprintf(fp, "%.17g %.6f %lld %lld %.6e\n", sim.time(), wall, steps, active, double(active) * N / wall);
    if (sim.status() & h4nb::kNaN) {
      std::fprintf(stderr, "h4nb_run: non-finite value (NaN or Inf) at t=%g\n", sim.time());
      return 3;  // Exit codes: 1 = runtime error, 2 = settings error, 3 = numerical failure.
    }
    write_diag(sim.diagnostics());
    double dmin = 1e300, dmax = 0, dsum = 0;
    for (int lv : sim.levels()) {
      const double dt = c.dt_max / std::ldexp(1.0, lv);
      dmin = std::min(dmin, dt); dmax = std::max(dmax, dt); dsum += dt;
    }
    std::fprintf(ft, "%.17g %.6e %.6e %.6e %.3f %.6e\n", sim.time(), dmin, dmax, dsum / N,
                 steps ? double(active) / double(steps) : 0.0, std::sqrt(s1.min_r2));
    if (!close_warned && (sim.status() & h4nb::kClosePair)) {
      std::fprintf(stderr, "warning: a pair came closer than r_close (r_min = %g) by t = %g\n", std::sqrt(s1.min_r2), sim.time());
      close_warned = true;
    }
    write_snap(k);
    for (FILE* f : {fe, fm, ft, fp})
      if (f) std::fflush(f);
  }
  // With no snap and no snap_times, write only the final snapshot.
  if (!snap_every && snap_index.empty()) h4nb::write_snapshot(out + "/snap_final.snap", sim.state(), sim.time());
  const unsigned st = sim.status();
  if (st & h4nb::kClosePair) std::fprintf(stderr, "warning: a pair came closer than r_close\n");
  if (st & h4nb::kDtUnderflow) std::fprintf(stderr, "warning: a particle needs dt < dt_min. Raise max_level.\n");
  std::printf("t=%g: max |dE/E| = %.3e, mean |dE/E| = %.3e\n", sim.time(), max_err, err_sum / double(err_n));
  for (FILE* f : {fe, fm, ft, fp})
    if (f) std::fclose(f);
  return 0;
} catch (const std::exception& e) {
  return settings_main_error("h4nb_run", e);
}
