// Physics scenarios, templated over the integrator: make(p, c) -> unique_ptr<X>, where X has
// advance_to(double), state(), levels(), status(). They run on ref::Ref (CPU) and on h4nb::Simulation (GPU).
// The limits come from a model of this algorithm (docs/superpowers/plans: "Measured numbers"). Do not loosen them.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdio>
#include "check.hpp"
#include "kepler.hpp"
#include "reference.hpp"

constexpr double kPi = 3.14159265358979323846;

struct TwoBody {
  h4nb::Particles p;
  double mu;
};

// m0 = 1, m1 at semi-major axis 1, start at pericentre. Barycentric unless fixed_center (then m0 sits at the origin).
inline TwoBody two_body(double e, double m1, bool fixed_center) {
  TwoBody tb;
  tb.mu = fixed_center ? 1.0 : 1.0 + m1;
  double r[3], v[3];
  kepler_rel(tb.mu, 1.0, e, 0.0, r, v);
  const double f0 = fixed_center ? 0.0 : -m1 / (1.0 + m1), f1 = fixed_center ? 1.0 : 1.0 / (1.0 + m1);
  tb.p.id = {0, 1};
  tb.p.m = {1.0, m1};
  tb.p.x = {f0 * r[0], f1 * r[0]}; tb.p.y = {f0 * r[1], f1 * r[1]}; tb.p.z = {0.0, 0.0};
  tb.p.vx = {f0 * v[0], f1 * v[0]}; tb.p.vy = {f0 * v[1], f1 * v[1]}; tb.p.vz = {0.0, 0.0};
  return tb;
}

inline double rel_error(const h4nb::Particles& s, const double r[3]) {
  return std::sqrt(std::pow(s.x[1] - s.x[0] - r[0], 2) + std::pow(s.y[1] - s.y[0] - r[1], 2) +
                   std::pow(s.z[1] - s.z[0] - r[2], 2));
}

// TZ 11.1: one orbit with block steps; energy, angular momentum, position vs analytic.
template <class Make>
void kepler_orbit(Make make, double e, bool fixed_center) {
  const TwoBody tb = two_body(e, 1e-3, fixed_center);
  h4nb::Config c;
  c.eta = 0.0005;
  c.dt_max = 1.0 / 16;
  c.max_level = 30;
  c.fixed_center = fixed_center;
  auto sim = make(tb.p, c);
  const h4nb::Diagnostics d0 = ref::direct_diagnostics(sim->state(), c.G, c.eps2);
  const int n = int(2 * kPi / std::sqrt(tb.mu) / c.dt_max);
  double dE = 0, dL = 0;
  for (int k = 1; k <= n; ++k) {
    sim->advance_to(k * c.dt_max);
    const h4nb::Diagnostics d = ref::direct_diagnostics(sim->state(), c.G, c.eps2);
    dE = std::max(dE, std::fabs((d.E - d0.E) / d0.E));
    dL = std::max(dL, std::fabs((d.L[2] - d0.L[2]) / d0.L[2]));
  }
  double r[3], v[3];
  kepler_rel(tb.mu, 1.0, e, n * c.dt_max, r, v);
  const double err = rel_error(sim->state(), r);
  std::printf("kepler e=%.1f fixed_center=%d: dE_max=%.2e dL_max=%.2e pos_err=%.2e\n", e, int(fixed_center), dE, dL, err);
  CHECK(dE <= 1e-8);
  CHECK(dL <= 2e-8);
  CHECK(err <= 1e-6);
  CHECK(sim->status() == 0);
}

// TZ 11.6: Fixed shared step h, h/2, h/4, h/8 -> error ratio ~16.
template <class Make>
void convergence(Make make, double e) {
  double err[4];
  for (int k = 0; k < 4; ++k) {
    const TwoBody tb = two_body(e, 1e-3, false);
    h4nb::Config c;
    c.mode = h4nb::StepMode::Fixed;
    c.dt_max = 1.0 / 8;
    c.max_level = 30;
    c.fixed_level = 3 + k;
    auto sim = make(tb.p, c);
    sim->advance_to(1.0);
    double r[3], v[3];
    kepler_rel(tb.mu, 1.0, e, 1.0, r, v);
    err[k] = rel_error(sim->state(), r);
  }
  for (int k = 0; k < 3; ++k) {
    const double ratio = err[k] / err[k + 1];
    std::printf("convergence e=%.1f: e(h)=%.2e ratio=%.2f\n", e, err[k], ratio);
    CHECK(ratio > 14.0 && ratio < 18.0);
  }
}

// Inner binary (1, 0.3) at separation 1, third body 0.1 at distance 10; centre-of-mass frame.
inline h4nb::Particles hierarchical_triple() {
  h4nb::Particles p;
  const double mb = 1.3, vb = std::sqrt(mb);
  p.id = {0, 1, 2};
  p.m = {1.0, 0.3, 0.1};
  p.x = {-0.3 / mb, 1.0 / mb, 10.0}; p.y = {0, 0, 0}; p.z = {0, 0, 0};
  p.vx = {0, 0, 0}; p.vy = {-0.3 / mb * vb, 1.0 / mb * vb, std::sqrt(1.4 / 10.0)}; p.vz = {0, 0, 0};
  double M = 0, cx = 0, cvy = 0;
  for (int i = 0; i < 3; ++i) { M += p.m[i]; cx += p.m[i] * p.x[i]; cvy += p.m[i] * p.vy[i]; }
  for (int i = 0; i < 3; ++i) { p.x[i] -= cx / M; p.vy[i] -= cvy / M; }
  return p;
}

// TZ 11.2: mutual gravity, a moving central body, conservation of P (exact for a shared step) and E.
template <class Make>
void triple(Make make, bool fixed) {
  const h4nb::Particles p0 = hierarchical_triple();
  h4nb::Config c;
  c.dt_max = 1.0 / 16;
  c.max_level = 30;
  c.eta = 0.001;
  if (fixed) {
    c.mode = h4nb::StepMode::Fixed;
    c.fixed_level = 7;
  }
  auto sim = make(p0, c);
  const h4nb::Diagnostics d0 = ref::direct_diagnostics(sim->state(), c.G, c.eps2);
  double pscale = 0;
  for (size_t i = 0; i < p0.size(); ++i) pscale += p0.m[i] * std::hypot(p0.vx[i], p0.vy[i], p0.vz[i]);
  double dE = 0, dP = 0;
  for (int k = 1; k <= 160; ++k) {
    sim->advance_to(k / 16.0);
    const h4nb::Diagnostics d = ref::direct_diagnostics(sim->state(), c.G, c.eps2);
    dE = std::max(dE, std::fabs((d.E - d0.E) / d0.E));
    dP = std::max(dP, std::hypot(d.P[0] - d0.P[0], d.P[1] - d0.P[1], d.P[2] - d0.P[2]) / pscale);
  }
  std::printf("triple fixed=%d: dE_max=%.2e dP_max=%.2e\n", int(fixed), dE, dP);
  CHECK(dE <= (fixed ? 1e-12 : 1e-9));
  CHECK(dP <= (fixed ? 1e-13 : 1e-10));
  CHECK(sim->status() == 0);
}

// Work of the dissipative forces since t = 0 (Diagnostics::W_diss). E - E0 - W_diss is about 0.
inline double w_diss_of(const ref::Ref& r) { return r.w_diss(); }
inline double w_diss_of(h4nb::Simulation& s) { return s.diagnostics().W_diss; }

// LinearDrag, G = 0, no background flow. Particle 1 has v(t) = v0 exp(-t / tau). Particle 0 has no drag.
// The drag work is the kinetic energy change of particle 1: W_diss = 0.5 m (v^2 - v0^2). It is negative.
template <class Make>
void drag_decay(Make make, double tau) {
  h4nb::Particles p;
  p.id = {0, 1};
  p.m = {1.0, 1.0};
  p.x = {0.0, 1.0}; p.y = {0.0, 0.0}; p.z = {0.0, 0.0};
  p.vx = {0.3, 0.5}; p.vy = {0.0, 0.2}; p.vz = {0.0, 0.0};
  h4nb::Config c;
  c.G = 0.0;
  c.dissipation = h4nb::Dissipation::LinearDrag;
  c.drag_tau = tau;
  c.eta = 1e-5;
  c.eta_init = 1e-5;
  c.dt_max = 1.0 / 8;
  c.max_level = 30;
  auto sim = make(p, c);
  const double K0 = 0.5 * (0.5 * 0.5 + 0.2 * 0.2);
  double ev = 0, ew = 0;
  for (int k = 1; k <= 32; ++k) {
    sim->advance_to(k * c.dt_max);
    const h4nb::Particles s = sim->state();
    const double f = std::exp(-k * c.dt_max / tau);
    ev = std::max(ev, std::hypot(s.vx[1] - 0.5 * f, s.vy[1] - 0.2 * f));
    const double K = 0.5 * (s.vx[1] * s.vx[1] + s.vy[1] * s.vy[1]);
    ew = std::max(ew, std::fabs(w_diss_of(*sim) - (K - K0)));
    CHECK_NEAR(s.vx[0], 0.3, 1e-14);  // Particle 0 keeps its velocity.
    CHECK_NEAR(s.vy[0], 0.0, 1e-14);
  }
  std::printf("drag_decay tau=%.2f: dv_max=%.2e dW_max=%.2e\n", tau, ev, ew);
  CHECK(ev <= 1e-8);
  CHECK(ew <= 1e-8);
  CHECK(sim->status() == 0);
}

// Kepler orbit with LinearDrag on particle 1 (particle 0 has no drag), one orbit.
// The energy balance holds: E - E0 - W_diss is about 0. The drag must act: |W_diss| is not small.
template <class Make>
void drag_kepler(Make make, double e, double tau) {
  const TwoBody tb = two_body(e, 1e-3, false);
  h4nb::Config c;
  c.eta = 1e-5;
  c.eta_init = 1e-5;
  c.dt_max = 1.0 / 16;
  c.max_level = 30;
  c.dissipation = h4nb::Dissipation::LinearDrag;
  c.drag_tau = tau;
  auto sim = make(tb.p, c);
  const h4nb::Diagnostics d0 = ref::direct_diagnostics(sim->state(), c.G, c.eps2);
  const int n = int(2 * kPi / std::sqrt(tb.mu) / c.dt_max);
  double dE = 0, wmax = 0;
  for (int k = 1; k <= n; ++k) {
    sim->advance_to(k * c.dt_max);
    const h4nb::Diagnostics d = ref::direct_diagnostics(sim->state(), c.G, c.eps2);
    const double w = w_diss_of(*sim);
    dE = std::max(dE, std::fabs((d.E - d0.E - w) / d0.E));
    wmax = std::max(wmax, std::fabs(w));
  }
  std::printf("drag_kepler e=%.1f tau=%.1f: |E-E0-W|_max=%.2e W_max=%.2e\n", e, tau, dE, wmax);
  CHECK(dE <= 1e-8);
  CHECK(wmax > 1e-3);
  CHECK(sim->status() == 0);
}
