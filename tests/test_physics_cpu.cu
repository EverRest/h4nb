// Physics on the CPU oracle (ref::Ref, same algorithm as the GPU). No GPU needed. TZ 11.1, 11.2, 11.6.
#include <cmath>
#include <cstdio>
#include <memory>
#include <random>
#include "scenarios.hpp"

// LinearDrag (A2): one drag particle, tau = 1, v0 = (1, 0, 0), fixed steps h = 1/8 ... 1/256, end t = 1.
// The exact velocity is v0 exp(-t/tau). The error ratio per halving must be at least 14 (order 4 gives 16, order 3 gives 8).
// Particle 0 has zero mass and no drag. It is the central body in the reference driver.
static void linear_drag_convergence_order4() {
  double err[6];
  for (int k = 0; k < 6; ++k) {
    h4nb::Particles p;
    p.resize(2);
    p.id = {0, 1};
    p.m = {0.0, 0.0};  // Zero masses: no gravity, only the drag acts.
    p.x = {5.0, 0.0}; p.y = {0.0, 0.0}; p.z = {0.0, 0.0};
    p.vx = {0.0, 1.0}; p.vy = {0.0, 0.0}; p.vz = {0.0, 0.0};
    h4nb::Config c;
    c.dissipation = h4nb::Dissipation::LinearDrag;
    c.drag_tau = 1.0;
    c.mode = h4nb::StepMode::Fixed;
    c.dt_max = 1.0 / 8;
    c.max_level = 30;
    c.fixed_level = 3 + k;  // Step h = dt_max / 2^(3 + k).
    ref::Ref sim(p, c);
    sim.advance_to(1.0);
    err[k] = std::fabs(sim.state().vx[1] - std::exp(-1.0));
  }
  // The last halving (h = 1/128 to 1/256) is not checked: its error is about 3e-15, the round-off floor.
  for (int k = 0; k < 4; ++k) {
    const double ratio = err[k] / err[k + 1];
    std::printf("linear drag: e(h)=%.2e ratio=%.2f\n", err[k], ratio);
    CHECK(ratio >= 14.0);
  }
}

// Cold start (issue A1): three equal masses at rest, equilateral triangle of side R. All velocities are 0, so the
// jerk at t = 0 is 0. The first step must come from the full Aarseth estimate, not from dt_max.
// Mass 0.1: with mass 1 the triangle collapses (triple collision) at t of about 0.10, before t = 0.25, and no
// step size keeps |dE/E| small there. Measured |dE/E| at t = 0.25: m = 1: 7.9e8; m = 0.1: 3.1e-7.
void cold_start_triangle() {
  const double R = 0.3, rc = R / std::sqrt(3.0), s3 = std::sqrt(3.0);
  h4nb::Particles p;
  p.resize(3);
  p.id = {0, 1, 2};
  p.m = {0.1, 0.1, 0.1};
  p.x = {rc, -0.5 * rc, -0.5 * rc};
  p.y = {0.0, 0.5 * s3 * rc, -0.5 * s3 * rc};
  p.z = {0.0, 0.0, 0.0};
  p.vx = {0.0, 0.0, 0.0};
  p.vy = {0.0, 0.0, 0.0};
  p.vz = {0.0, 0.0, 0.0};
  h4nb::Config c;
  c.eta = 0.01;
  c.dt_max = 1.0 / 4;
  ref::Ref sim(p, c);
  const h4nb::Diagnostics d0 = ref::direct_diagnostics(sim.state(), c.G, c.eps2);
  sim.advance_to(0.25);
  const h4nb::Diagnostics d = ref::direct_diagnostics(sim.state(), c.G, c.eps2);
  const double dE = std::fabs((d.E - d0.E) / d0.E);
  std::printf("cold_start_triangle: |dE/E|=%.2e status=%u\n", dE, sim.status());
  CHECK(dE < 1e-5);
  CHECK(sim.status() == 0);
}

// A8: block mode (Aarseth step). The energy error after t = 6.25 for eta = 1e-4, 2.5e-5, 6.25e-6. The levels go 2, 3, 4
// (the step scales as sqrt(eta), levels are powers of two). A 4th-order scheme gives a ratio of about 16 per level.
// The bound is 8, loose on purpose, and it stays above the round-off floor (about 1e-14).
static void block_eta_scan() {
  const double etas[3] = {1e-4, 2.5e-5, 6.25e-6};
  double err[3];
  for (int k = 0; k < 3; ++k) {
    const TwoBody tb = two_body(0.1, 1e-3, false);
    h4nb::Config c;
    c.eta = etas[k];
    c.dt_max = 1.0 / 64;
    c.max_level = 30;
    ref::Ref sim(tb.p, c);
    const double E0 = ref::direct_diagnostics(tb.p, c.G, c.eps2).E;
    sim.advance_to(6.25);
    const double E1 = ref::direct_diagnostics(sim.state(), c.G, c.eps2).E;
    err[k] = std::fabs(E1 - E0) / std::fabs(E0);
    std::printf("block eta=%.3f: |dE/E|=%.3e\n", etas[k], err[k]);
    CHECK(sim.status() == 0);
  }
  CHECK(err[0] > err[1] && err[1] > err[2]);
  CHECK(err[0] / err[1] > 8.0 && err[1] / err[2] > 8.0);
}

// A8: softened cluster (Plummer softening, eps2 > 0). 64 equal masses in a ball, random velocities, one time unit.
// The bound is energy error. No Newtonian shortcut: this checks the softened force in the full step.
static void softened_cluster_energy() {
  const int n = 64;
  std::mt19937_64 rng(7);
  std::uniform_real_distribution<double> u(-1.0, 1.0);
  h4nb::Particles p;
  p.resize(n);
  for (int i = 0; i < n; ++i) {
    double x, y, z;
    do {
      x = u(rng); y = u(rng); z = u(rng);
    } while (x * x + y * y + z * z > 1.0);
    p.id[i] = i;
    p.m[i] = 1.0 / n;
    p.x[i] = x; p.y[i] = y; p.z[i] = z;
    p.vx[i] = 0.3 * u(rng); p.vy[i] = 0.3 * u(rng); p.vz[i] = 0.3 * u(rng);
  }
  h4nb::Config c;
  c.eps2 = 0.01;
  c.eta = 0.01;
  c.dt_max = 1.0 / 64;
  c.max_level = 30;
  ref::Ref sim(p, c);
  const double E0 = ref::direct_diagnostics(p, c.G, c.eps2).E;
  CHECK(E0 < 0);  // Bound cluster.
  sim.advance_to(1.0);
  const double E1 = ref::direct_diagnostics(sim.state(), c.G, c.eps2).E;
  const double rel = std::fabs(E1 - E0) / std::fabs(E0);
  std::printf("softened cluster N=%d: |dE/E|=%.3e status=%u\n", n, rel, sim.status());
  CHECK(sim.status() == 0);
  CHECK(rel < 1e-6);
}

int main() {
  block_eta_scan();
  softened_cluster_energy();
  linear_drag_convergence_order4();
  cold_start_triangle();
  auto make = [](const h4nb::Particles& p, const h4nb::Config& c) { return std::make_unique<ref::Ref>(p, c); };
  for (double e : {0.1, 0.5}) {
    kepler_orbit(make, e, false);
    kepler_orbit(make, e, true);
    convergence(make, e);
  }
  triple(make, true);
  triple(make, false);
  drag_decay(make, 1.0);
  drag_kepler(make, 0.1, 5.0);
  drag_kepler(make, 0.5, 5.0);

  // The CPU oracle is deterministic: two identical runs give identical bits.
  const TwoBody tb = two_body(0.5, 1e-3, false);
  h4nb::Config c;
  c.eta = 0.001;
  c.dt_max = 1.0 / 16;
  ref::Ref a(tb.p, c), b(tb.p, c);
  a.advance_to(2.0);
  b.advance_to(2.0);
  const h4nb::Particles sa = a.state(), sb = b.state();
  CHECK(sa.x == sb.x && sa.y == sb.y && sa.vx == sb.vx && sa.vy == sb.vy);
  std::puts("test_physics_cpu: OK");
  return 0;
}
