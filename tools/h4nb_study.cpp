// h4nb_study: convergence study (US3, FR-015). It runs the grid dt_maxes x etas x t_ends in one process.
// Usage: h4nb_study [config=<file>] ic=<file> out=<dir> diag=<interval> [etas=...] [dt_maxes=...] [t_ends=...] [key=value ...]
// "h4nb_study help=1" prints all keys. The tool writes <out>/config.used and <out>/study.dat (data-model.md section 9).
// For each pair (dt_max, eta), the tool integrates one time up to the largest t_end. It reads each row at its t_end:
// max_rel_err and mean_rel_err use the diag samples with time <= t_end, the t=0 sample included (as in h4nb_run).
// block_steps, pair_evals and wall_s count from t=0 to t_end. The init force pass and the diagnostics are not counted.
// A NaN or Inf stops the pair (dt_max, eta). Each row with a t_end after the failure has nan errors and pass=0.
// Exit codes: 0 = done (rows with pass=0 included), 1 = runtime error, 2 = settings error or more than one rank.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <string>
#include <vector>
#include "disk.hpp"
#include "h4nb/h4nb.hpp"
#include "run_info.hpp"
#include "input.hpp"
#include "settings.hpp"

using Clock = std::chrono::steady_clock;
static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

static void declare(Settings& s) {
  using T = Setting;
  s.add("ic", T::String, "", "Initial conditions. .snap is binary. Other names are text \"id m x y z vx vy vz\".").required = true;
  s.add("out", T::String, "", "Output directory for study.dat and config.used.").required = true;
  s.add("etas", T::RealList, "0.002,0.001,0.0005,0.00025", "Grid of eta.", Range::gt(0));
  s.add("dt_maxes", T::RealList, "0.015625", "Grid of dt_max.", Range::gt(0).power_of_two());
  s.add("t_ends", T::RealList, "", "Grid of durations, multiples of diag. No value: the period, rounded up to a multiple of diag.",
        Range::gt(0));
  s.add("diag", T::Real, "", "Interval of the energy samples. A multiple of each dt_max.", Range::gt(0)).required = true;
  s.add("period", T::Real, "0", "Reference period for the default t_ends. 0: estimate from the initial state.", Range::ge(0));
  s.add("period_kind", T::Enum, "mean", "The estimate used when period=0.", Range::one_of({"mean", "median", "mass_weighted"}));
  s.add_preset();
  s.add("G", T::Real, "1", "Gravitational constant.", Range::gt(0));
  s.add("eps", T::Real, "0", "Plummer softening length. The library receives eps^2.", Range::ge(0));
  s.add("eta_init", T::Real, "0.01", "First step: eta_init*|a|/|j|.", Range::gt(0));
  s.add("max_level", T::Int, "40", "dt_min = dt_max / 2^max_level.", Range::between(1, 50));
  s.add("mode", T::Enum, "block", "Block steps or one shared step.", Range::one_of({"block", "fixed"}));
  s.add("fixed_level", T::Int, "0", "Level of all particles in fixed mode. Not more than max_level.", Range::ge(0));
  s.add("devices", T::IntList, "0", "CUDA device IDs. A repeated ID emulates more GPUs on one card.", Range::ge(0));
  s.add("tile", T::Int, "128", "Targets per block in the force and potential kernels.", Range::one_of({"64", "128", "256"}));
  s.add("blocks_per_sm", T::Int, "4", "Target blocks per SM for the source split.", Range::between(1, 16));
  s.add("energy_tol", T::Real, "1e-8", "A row passes when max_rel_err <= energy_tol.", Range::gt(0));
  s.add("r_close", T::Real, "-1", "Close-pair radius. -1: 0.1 of the mean spacing R_rms/N^(1/3). 0: off.",
        Range::ge(0).or_value(-1));
}

// One row of study.dat.
struct Row {
  double eta, dt_max, t_end, max_err, mean_err, final_err, dP, dL, pairs, wall;
  long long steps;
  bool pass;
};

static int run(int argc, char** argv) try {
  Settings s;
  declare(s);
  s.parse(argc, argv);
  if (s.help()) {
    s.print_help(stdout, "h4nb_study");
    return 0;
  }
  if (s.integer("fixed_level") > s.integer("max_level")) s.fail("fixed_level", "more than max_level");
  const std::vector<double> etas = s.reals("etas"), dts = s.reals("dt_maxes");
  if (etas.empty()) s.fail("etas", "the list is empty");
  if (dts.empty()) s.fail("dt_maxes", "the list is empty");
  const double diag = s.real("diag");
  char why[128];
  for (double dt : dts)
    if (!is_multiple(diag, dt)) {
      std::snprintf(why, sizeof why, "not a multiple of dt_max=%.17g", dt);
      s.fail("diag", why);
    }
  const std::string ic = s.str("ic"), out = s.str("out");
  const h4nb::Particles p = load_input(ic);
  if (p.size() < 2) throw SettingsError("the file " + ic + " has less than 2 particles");
  const double G = s.real("G");
  std::vector<double> t_ends = s.reals("t_ends");
  for (double t : t_ends)
    if (!is_multiple(t, diag) || std::llround(t / diag) < 1) {
      std::snprintf(why, sizeof why, "a value is not a multiple of diag=%.17g", diag);
      s.fail("t_ends", why);
    }
  if (t_ends.empty()) {
    // Default t_ends: one reference period, rounded up to a multiple of diag.
    double period = s.real("period");
    if (!(period > 0)) {
      // ponytail: periods() uses G = 1. Set period or t_ends when G is not 1.
      if (G != 1.0) s.fail("period", "the period estimate needs G=1. Set period or t_ends");
      const Periods est = periods(p);
      const std::string& kind = s.str("period_kind");
      period = kind == "median" ? est.median : kind == "mass_weighted" ? est.mass_weighted : est.mean;
      if (!(period > 0)) s.fail("period", "no particle is bound to record 0, thus no period estimate. Set period or t_ends");
    }
    t_ends.push_back(diag * std::ceil(period / diag * (1 - 1e-12)));
    std::printf("h4nb_study: t_ends=%.17g (period %.17g rounded up to a multiple of diag)\n", t_ends[0], period);
  }
  std::sort(t_ends.begin(), t_ends.end());
  t_ends.erase(std::unique(t_ends.begin(), t_ends.end()), t_ends.end());
  const double tol = s.real("energy_tol"), N = double(p.size());

  h4nb::Config c;
  c.G = G;
  c.eps2 = std::pow(s.real("eps"), 2);  // The tool takes eps. The library takes eps^2.
  c.eta_init = s.real("eta_init");
  c.max_level = s.integer("max_level");
  c.mode = s.str("mode") == "fixed" ? h4nb::StepMode::Fixed : h4nb::StepMode::Block;
  c.fixed_level = s.integer("fixed_level");
  c.devices = s.ints("devices");
  c.tile = s.integer("tile");
  c.blocks_per_sm = s.integer("blocks_per_sm");
  // Default close-pair radius as in h4nb_run: 0.1 times the mean spacing R_rms / N^(1/3) of the initial state.
  double R2 = 0, p_scale = 0, l_scale = 0;  // Scales of dP_rel and dL_rel: sum m|v| and sum m|r x v| at t=0.
  for (size_t i = 0; i < p.size(); ++i) {
    R2 += p.x[i] * p.x[i] + p.y[i] * p.y[i] + p.z[i] * p.z[i];
    p_scale += p.m[i] * std::sqrt(p.vx[i] * p.vx[i] + p.vy[i] * p.vy[i] + p.vz[i] * p.vz[i]);
    const double lx = p.y[i] * p.vz[i] - p.z[i] * p.vy[i], ly = p.z[i] * p.vx[i] - p.x[i] * p.vz[i],
                 lz = p.x[i] * p.vy[i] - p.y[i] * p.vx[i];
    l_scale += p.m[i] * std::sqrt(lx * lx + ly * ly + lz * lz);
  }
  if (!(p_scale > 0)) p_scale = 1;
  if (!(l_scale > 0)) l_scale = 1;
  const double r_close = s.real("r_close") >= 0 ? s.real("r_close") : 0.1 * std::sqrt(R2 / N) / std::cbrt(N);
  c.r2_close = r_close * r_close;

  std::filesystem::create_directories(out);
  s.write_used(out + "/config.used", "h4nb_study");
  write_run_info(out + "/run_info.txt", "h4nb_study", c.devices, argc, argv);
  FILE* f = std::fopen((out + "/study.dat").c_str(), "w");
  if (!f) throw std::runtime_error("cannot write " + out + "/study.dat");
  std::string t_list;  // The t_ends that the study uses, also when the key has no value.
  for (double t : t_ends) {
    std::snprintf(why, sizeof why, "%s%.17g", t_list.empty() ? "" : ",", t);
    t_list += why;
  }
  std::fprintf(f, "# h4nb_study N=%zu preset=%s eps2=%g diag=%.17g t_ends=%s energy_tol=%g\n", p.size(), s.str("preset").c_str(),
               c.eps2, diag, t_list.c_str(), tol);
  std::fprintf(f, "# eta dt_max t_end max_rel_err mean_rel_err final_rel_err dP_rel dL_rel block_steps pair_evals wall_s pass\n");
  std::printf("h4nb_study: N=%zu, %zu dt_max x %zu eta x %zu t_end, writing %s/study.dat\n", p.size(), dts.size(), etas.size(),
              t_ends.size(), out.c_str());
  std::fflush(stdout);
  std::vector<Row> rows;
  const double nan = std::nan("");
  for (double dt : dts)
    for (double eta : etas) {
      c.dt_max = dt;
      c.eta = eta;
      auto simp = make_simulation(p, c);
      h4nb::Simulation& sim = *simp;
      const h4nb::Stats st0 = sim.stats();  // The init force pass is in st0. It is not counted.
      const h4nb::Diagnostics d0 = sim.diagnostics();
      double max_err = 0, err_sum = 0, wall = 0;
      long n_err = 1;  // The t=0 sample has err = 0.
      bool failed = false;
      size_t next = 0;  // Index of the next t_end to read off.
      const long long nseg = std::llround(t_ends.back() / diag);
      for (long long k = 1; k <= nseg && next < t_ends.size(); ++k) {
        const auto w0 = Clock::now();
        sim.advance_to(double(k) * diag);
        wall += since(w0);
        const h4nb::Stats st = sim.stats();
        Row r{eta, dt, 0, nan, nan, nan, nan, nan, double(st.active_total - st0.active_total) * N, wall,
              (long long)(st.block_steps - st0.block_steps), false};
        if (!(sim.status() & h4nb::kNaN)) {
          const h4nb::Diagnostics d = sim.diagnostics();
          const double err = std::fabs((d.E - d0.E) / d0.E);
          failed = !std::isfinite(err);
          max_err = std::max(max_err, err);
          err_sum += err;
          ++n_err;
          r.max_err = max_err, r.mean_err = err_sum / double(n_err), r.final_err = err;
          r.dP = std::sqrt(std::pow(d.P[0] - d0.P[0], 2) + std::pow(d.P[1] - d0.P[1], 2) + std::pow(d.P[2] - d0.P[2], 2)) / p_scale;
          r.dL = std::sqrt(std::pow(d.L[0] - d0.L[0], 2) + std::pow(d.L[1] - d0.L[1], 2) + std::pow(d.L[2] - d0.L[2], 2)) / l_scale;
        } else {
          failed = true;
        }
        if (failed) {
          std::fprintf(stderr, "h4nb_study: dt_max=%g eta=%g: non-finite value (NaN or Inf) at t=%g. The point stops.\n", dt, eta,
                       sim.time());
          r.max_err = r.mean_err = r.final_err = r.dP = r.dL = nan;
        }
        // Write a row at each t_end that this sample reaches. After a failure, write all remaining rows.
        while (next < t_ends.size() && (failed || std::llround(t_ends[next] / diag) == k)) {
          r.t_end = t_ends[next++];
          r.pass = !failed && r.max_err <= tol;
          rows.push_back(r);
          std::fprintf(f, "%g %g %.17g %.6e %.6e %.6e %.6e %.6e %lld %.0f %.6f %d\n", r.eta, r.dt_max, r.t_end, r.max_err, r.mean_err,
                       r.final_err, r.dP, r.dL, r.steps, r.pairs, r.wall, int(r.pass));
        }
        std::fflush(f);
        if (failed) break;
      }
      const unsigned st = sim.status();
      if (st & h4nb::kClosePair) std::fprintf(stderr, "warning: dt_max=%g eta=%g: a pair came closer than r_close\n", dt, eta);
      if (st & h4nb::kDtUnderflow) std::fprintf(stderr, "warning: dt_max=%g eta=%g: a particle needs dt < dt_min. Raise max_level.\n", dt, eta);
      std::printf("dt_max=%g eta=%g: max |dE/E| = %.3e at t=%g\n", dt, eta, max_err, sim.time());
      std::fflush(stdout);
    }
  if (std::fclose(f) != 0) throw std::runtime_error("cannot write " + out + "/study.dat");

  // The cheapest row that passes, by pair_evals, for each t_end.
  bool any = false;
  for (double t : t_ends) {
    const Row* best = nullptr;
    for (const Row& r : rows)
      if (r.t_end == t && r.pass && (!best || r.pairs < best->pairs)) best = &r;
    if (best) std::printf("t_end=%g: cheapest pass eta=%g dt_max=%g max_rel_err=%.3e pair_evals=%.3e\n", t, best->eta,
                          best->dt_max, best->max_err, best->pairs);
    else std::printf("t_end=%g: none passes energy_tol=%g\n", t, tol);
    any = any || best;
  }
  if (!any)
    std::printf("note: no eta in the grid passes. Add smaller etas, for example etas=%g,%g.\n",
                *std::min_element(etas.begin(), etas.end()) / 2, *std::min_element(etas.begin(), etas.end()) / 4);
  return 0;
} catch (const std::exception& e) {
  return settings_main_error("h4nb_study", e);
}

// Several ranks are not supported: each grid point is a separate run, and one rank per GPU gives no gain here.
// ponytail: h4nb_study rejects ranks() > 1 (exit code 2). Upgrade: run each grid point as a collective
// Simulation and write the files on rank 0 only, as h4nb_run does.
int main(int argc, char** argv) {
  try {
    h4nb::RankScope scope(argc, argv);
    if (h4nb::ranks() > 1) {
      if (h4nb::rank() == 0)
        std::fprintf(stderr, "h4nb_study: error: %d ranks. This tool runs as one process only. Start it without "
                     "mpirun or srun, or with one task. Use devices= for several GPUs.\n", h4nb::ranks());
      return 2;
    }
    return run(argc, argv);
  } catch (const std::exception& e) {
    return settings_main_error("h4nb_study", e);
  }
}
