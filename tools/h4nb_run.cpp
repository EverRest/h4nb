// h4nb_run: runs a simulation. It writes the energy, momentum, timesteps and performance .dat files, and the snapshots.
// Usage: h4nb_run ic=<file.txt|file.snap> out=<dir> t_end=<t> [diag=<dt>] [snap=<dt>] [eta=0.01] [eta_init=0.01]
//        [dt_max=0.015625] [max_level=40] [eps=0] [mode=block|fixed] [fixed_level=0] [fixed_center=0]
//        [r_close=auto] [devices=0,1]
// r_close: a pair closer than this value sets the close-pair flag. auto means 0.1 of the mean particle spacing. 0 turns this off.
// t_end, diag and snap must be multiples of dt_max. t_end and snap must also be multiples of diag.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <string>
#include "args.hpp"
#include "h4nb/h4nb.hpp"

using Clock = std::chrono::steady_clock;
static double since(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }

int main(int argc, char** argv) try {
  const Args a(argc, argv);
  if (!a.has("ic") || !a.has("out") || !a.has("t_end")) {
    std::fprintf(stderr, "usage: h4nb_run ic=<file> out=<dir> t_end=<t> [diag= snap= eta= dt_max= devices= ...]\n");
    return 1;
  }
  h4nb::Config c;
  c.eta = a.num("eta", c.eta);
  c.eta_init = a.num("eta_init", c.eta_init);
  c.dt_max = a.num("dt_max", c.dt_max);
  c.max_level = int(a.num("max_level", c.max_level));
  c.eps2 = std::pow(a.num("eps", 0.0), 2);
  c.mode = a.str("mode", "block") == "fixed" ? h4nb::StepMode::Fixed : h4nb::StepMode::Block;
  c.fixed_level = int(a.num("fixed_level", 0));
  c.fixed_center = a.num("fixed_center", 0) != 0;
  c.devices = a.ints("devices", "0");
  const std::string ic = a.str("ic"), out = a.str("out");
  const double t_end = a.num("t_end", 0), diag = a.num("diag", c.dt_max), snap = a.num("snap", 0);
  const bool binary = ic.size() > 5 && ic.compare(ic.size() - 5, 5, ".snap") == 0;
  const h4nb::Particles p = binary ? h4nb::read_snapshot(ic) : h4nb::load_text(ic);
  const double N = double(p.size());
  double R2 = 0;
  for (size_t i = 0; i < p.size(); ++i) R2 += p.x[i] * p.x[i] + p.y[i] * p.y[i] + p.z[i] * p.z[i];
  // Default close-pair radius: 0.1 times the mean spacing R_rms / N^(1/3) of the initial state.
  // ponytail: a rough guess for a disk. Set r_close explicitly when the system has another scale.
  const double r_close_arg = a.num("r_close", -1.0);
  const double r_close = r_close_arg >= 0 ? r_close_arg : 0.1 * std::sqrt(R2 / N) / std::cbrt(N);
  c.r2_close = r_close * r_close;
  std::filesystem::create_directories(out);
  FILE* fe = std::fopen((out + "/energy.dat").c_str(), "w");
  FILE* fm = std::fopen((out + "/momentum.dat").c_str(), "w");
  FILE* ft = std::fopen((out + "/timesteps.dat").c_str(), "w");
  FILE* fp = std::fopen((out + "/performance.dat").c_str(), "w");
  if (!fe || !fm || !ft || !fp) throw std::runtime_error("cannot write into " + out);
  std::fprintf(fe, "# time K U E rel_err max_rel_err mean_rel_err\n");
  std::fprintf(fm, "# time Px Py Pz Lx Ly Lz dP_rel dL_rel  (changes divided by sum m|v| and sum m|r x v| of the initial state, TZ 7.3)\n");
  std::fprintf(ft, "# time dt_min dt_max dt_mean mean_active_per_block_step r_min\n");
  std::fprintf(fp, "# time wall_s block_steps active pairs_per_s\n");

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
  if (snap_every) h4nb::write_snapshot(out + "/snap_000000.snap", sim.state(), 0.0);
  for (long long k = 1; k <= nseg; ++k) {
    const h4nb::Stats s0 = sim.stats();
    const auto w0 = Clock::now();
    sim.advance_to(double(k) * diag);
    const double wall = since(w0);
    const h4nb::Stats s1 = sim.stats();
    const long long steps = s1.block_steps - s0.block_steps, active = s1.active_total - s0.active_total;
    std::fprintf(fp, "%.17g %.6f %lld %lld %.6e\n", sim.time(), wall, steps, active, double(active) * N / wall);
    if (sim.status() & h4nb::kNaN) {
      std::fprintf(stderr, "h4nb_run: non-finite value (NaN or Inf) at t=%g\n", sim.time());
      return 2;
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
    if (snap_every && k % snap_every == 0) {
      char name[64];
      std::snprintf(name, sizeof name, "/snap_%06lld.snap", k / snap_every);
      h4nb::write_snapshot(out + name, sim.state(), sim.time());
    }
    for (FILE* f : {fe, fm, ft, fp}) std::fflush(f);
  }
  const unsigned st = sim.status();
  if (st & h4nb::kClosePair) std::fprintf(stderr, "warning: a pair came closer than r_close\n");
  if (st & h4nb::kDtUnderflow) std::fprintf(stderr, "warning: a particle needs dt < dt_min. Raise max_level.\n");
  std::printf("t=%g: max |dE/E| = %.3e, mean |dE/E| = %.3e\n", sim.time(), max_err, err_sum / double(err_n));
  for (FILE* f : {fe, fm, ft, fp}) std::fclose(f);
  return 0;
} catch (const std::exception& e) {
  std::fprintf(stderr, "h4nb_run: %s\n", e.what());
  return 1;
}
