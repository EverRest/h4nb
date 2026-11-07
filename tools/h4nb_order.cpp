// h4nb_order: two-body Kepler check (TZ 11.1, 11.6). It uses the fixed steps h, h/2, h/4 and h/8. It compares the error with the analytic
// solution. It also computes the ratio e(h)/e(h/2). For a 4th-order method, the ratio is about 16.
// Usage: h4nb_order [e=0.5] [m1=1e-3] [t_end=1] [dt_max=0.125] [level0=3] [levels=4] [devices=0] [config=<file>] [help=1]
// t_end must be a multiple of dt_max. dt_max must be a power of two. A settings error gives exit code 2.
// The orbit has a = 1, G = 1 and central mass 1. It starts at apocentre.
#include <cmath>
#include <cstdio>
#include "h4nb/h4nb.hpp"
#include "input.hpp"
#include "settings.hpp"

struct Rel { double r[3], v[3]; };

// Relative orbit in the pericentre frame (a = 1), at eccentric anomaly E.
static Rel kepler(double e, double mu, double E) {
  const double n = std::sqrt(mu), d = 1 - e * std::cos(E), s = std::sqrt(1 - e * e);
  return {{std::cos(E) - e, s * std::sin(E), 0}, {-n * std::sin(E) / d, n * s * std::cos(E) / d, 0}};
}

int main(int argc, char** argv) try {
  Settings a;
  Range below_one = Range::between(0, 1);
  below_one.hi_open = true;  // A bound orbit needs e < 1.
  a.add("e", Setting::Real, "0.5", "Orbit eccentricity (0 <= e < 1).", below_one);
  a.add("m1", Setting::Real, "1e-3", "Mass of the second body. The central mass is 1.", Range::gt(0));
  a.add("t_end", Setting::Real, "1", "End time. It must be a multiple of dt_max.", Range::gt(0));
  a.add("dt_max", Setting::Real, "0.125", "Largest step. The step of a level is dt_max / 2^level.", Range::gt(0).power_of_two());
  a.add("level0", Setting::Int, "3", "First fixed step level.", Range::ge(0));
  a.add("levels", Setting::Int, "4", "Number of levels. Each level halves the step.", Range::ge(2));
  a.add("devices", Setting::IntList, "0", "CUDA device IDs.", Range::ge(0));
  a.parse(argc, argv);
  if (a.help()) { a.print_help(stdout, "h4nb_order"); return 0; }
  const double e = a.real("e"), m1 = a.real("m1"), t_end = a.real("t_end");
  if (!is_multiple(t_end, a.real("dt_max"))) a.fail("t_end", "not a multiple of dt_max");
  constexpr double kPi = 3.14159265358979323846;
  const double mu = 1 + m1;
  double M = kPi + std::sqrt(mu) * t_end, E = M;  // Start at apocentre (E = pi).
  for (int k = 0; k < 100; ++k) E -= (E - e * std::sin(E) - M) / (1 - e * std::cos(E));
  const Rel r0 = kepler(e, mu, kPi), rt = kepler(e, mu, E);

  h4nb::Particles p;
  p.resize(2);
  p.id = {0, 1};
  p.m = {1.0, m1};
  p.x = {-m1 / mu * r0.r[0], r0.r[0] / mu};  // Centre-of-mass frame.
  p.y = {-m1 / mu * r0.r[1], r0.r[1] / mu};
  p.z = {0, 0};
  p.vx = {-m1 / mu * r0.v[0], r0.v[0] / mu};
  p.vy = {-m1 / mu * r0.v[1], r0.v[1] / mu};
  p.vz = {0, 0};

  h4nb::Config c;
  c.mode = h4nb::StepMode::Fixed;
  c.dt_max = a.real("dt_max");
  c.devices = a.ints("devices");
  const int level0 = a.integer("level0"), levels = a.integer("levels");
  std::printf("e=%g m1=%g t_end=%g\n%6s %12s %12s %8s %12s\n", e, m1, t_end, "level", "h", "pos_err", "ratio", "dE/E");
  double prev = 0;
  bool pass = levels > 1;
  for (int k = 0; k < levels; ++k) {
    c.fixed_level = level0 + k;
    auto simp = make_simulation(p, c);
    h4nb::Simulation& sim = *simp;
    const h4nb::Diagnostics d0 = sim.diagnostics();
    sim.advance_to(t_end);
    const h4nb::Particles s = sim.state();
    const double dx = s.x[1] - s.x[0] - rt.r[0], dy = s.y[1] - s.y[0] - rt.r[1], dz = s.z[1] - s.z[0];
    const double err = std::sqrt(dx * dx + dy * dy + dz * dz);
    const double ratio = k ? prev / err : 0.0;
    if (k && std::fabs(ratio - 16.0) > 2.0) pass = false;
    std::printf("%6d %12.5e %12.5e %8.2f %12.3e\n", c.fixed_level, c.dt_max / std::ldexp(1.0, c.fixed_level), err,
                ratio, std::fabs((sim.diagnostics().E - d0.E) / d0.E));
    prev = err;
  }
  std::printf("order check (ratio within 16 +- 2): %s\n", pass ? "PASS" : "FAIL");
  return pass ? 0 : 3;
} catch (const std::exception& ex) {
  return settings_main_error("h4nb_order", ex);
}
