// Unit tests for the per-particle Hermite math (src/hermite.cuh). Host only, no GPU needed.
#include <cmath>
#include <cstdio>
#include <random>
#include <vector>
#include "check.hpp"
#include "hermite.cuh"

using namespace h4nb;

static double comp(const d4& u, int k) { return k == 0 ? u.x : k == 1 ? u.y : u.z; }

// The predictor is exact for x(t) that is a cubic polynomial (constant jerk).
static void test_predict() {
  const d4 x{1.0, -2.0, 0.5, 3.0}, v{0.2, 0.3, -0.4, 0}, a{0.5, -0.1, 0.25, 0}, j{-0.3, 0.7, 0.05, 0};
  const double dt = 0.37, t2 = dt * dt, t3 = t2 * dt;
  d4 xp, vp;
  predict(x, v, a, j, dt, xp, vp);
  for (int k = 0; k < 3; ++k) {
    CHECK_NEAR(comp(xp, k), comp(x, k) + comp(v, k) * dt + comp(a, k) * t2 / 2 + comp(j, k) * t3 / 6, 1e-15);
    CHECK_NEAR(comp(vp, k), comp(v, k) + comp(a, k) * dt + comp(j, k) * t2 / 2, 1e-15);
  }
  CHECK(xp.w == 3.0);  // mass is carried through
}

// The Hermite corrector is exact when a(t) is a quadratic polynomial (x is quartic, v is cubic).
static void test_correct_exact_quadratic() {
  const d4 x0{0.3, -0.7, 0.2, 1.0}, v0{0.1, 0.4, -0.2, 0}, a0{0.6, -0.2, 0.9, 0}, j0{-0.4, 0.5, 0.3, 0};
  const d4 c{0.7, -1.1, 0.25, 0};  // a(t) = a0 + j0 t + c t^2
  const double h = 0.1, t2 = h * h, t3 = t2 * h, t4 = t3 * h;
  const d4 a1{a0.x + j0.x * h + c.x * t2, a0.y + j0.y * h + c.y * t2, a0.z + j0.z * h + c.z * t2, 0};
  const d4 j1{j0.x + 2 * c.x * h, j0.y + 2 * c.y * h, j0.z + 2 * c.z * h, 0};
  d4 x = x0, v = v0;
  const double dt = correct(x, v, a0, j0, a1, j1, h, 0.01);
  for (int k = 0; k < 3; ++k) {
    const double xe = comp(x0, k) + comp(v0, k) * h + comp(a0, k) * t2 / 2 + comp(j0, k) * t3 / 6 + comp(c, k) * t4 / 12;
    const double ve = comp(v0, k) + comp(a0, k) * h + comp(j0, k) * t2 / 2 + comp(c, k) * t3 / 3;
    CHECK_NEAR(comp(x, k), xe, 1e-13);
    CHECK_NEAR(comp(v, k), ve, 1e-13);
  }
  CHECK(dt > 0 && std::isfinite(dt));
}

// Aarseth criterion: hand value and sqrt(eta) scaling.
static void test_aarseth() {
  CHECK_NEAR(aarseth_dt(1.0, 1.0, 1.0, 1.0, 0.01), 0.1, 1e-15);  // sqrt(0.01 * 2 / 2)
  CHECK_NEAR(aarseth_dt(1.0, 1.0, 1.0, 1.0, 0.04) / aarseth_dt(1.0, 1.0, 1.0, 1.0, 0.01), 2.0, 1e-14);
}

// Levels: k = dt_max / 2^k; a finer level is always allowed; going up one level needs an aligned time.
static void test_choose_level() {
  bool u = false;
  CHECK(choose_level(0.3, 1.0, 0, 0, 10, u) == 2);  // 0.25 <= 0.3 < 0.5
  CHECK(!u);
  CHECK(choose_level(1.0, 1.0, 5, 0, 10, u) == 4);   // coarser by one, t = 0 aligned
  CHECK(choose_level(1.0, 1.0, 5, 64, 10, u) == 4);  // step 2^6 ticks: 64 is aligned
  CHECK(choose_level(1.0, 1.0, 5, 32, 10, u) == 5);  // 32 is not aligned: stays at level 5
  CHECK(!u);
  CHECK(choose_level(1e-9, 1.0, 0, 0, 3, u) == 3);  // capped at max_level
  CHECK(u);                                          // dt_min still too large: underflow flag
}

// update_particle: init sets the level from eta_init*|a|/|j|; centre and fixed modes; NaN and close-pair bits.
static void test_update_particle() {
  Config c;
  c.dt_max = 1.0;
  c.max_level = 10;
  c.eta_init = 0.01;
  const double tick = c.dt_max / 1024.0;
  const d4 a1{1, 0, 0, 0}, j1{0, 1, 0, 0}, z{0, 0, 0, 0};
  d4 x{1, 0, 0, 1}, v{0, 1, 0, 0}, a = z, j = z;
  int64_t t = 0, next = 0;
  int lv = 0;

  // First step: the level is a placeholder (0). init_level() sets the real one (cold start, issue A1).
  StepParams p = make_params(c, tick, 0, true);
  unsigned st = update_particle(p, false, a1, j1, 4.0, x, v, a, j, t, next, lv);
  CHECK(st == 0);
  CHECK(lv == 0);
  CHECK(next == 1024);
  CHECK(a.x == 1.0 && j.y == 1.0);

  // init_level(): snap s = (1,0,0), crackle 0: dt = sqrt(0.01 * (1 + 1) / 1) = 0.1414, so level 3 (1/8 = 0.125).
  unsigned sl = 0;
  CHECK(init_level(p, a1, j1, d4{1, 0, 0, 0}, z, sl) == 3 && sl == 0);
  // Zero snap and crackle: the estimate is infinite. Level 0 and kInitStepInvalid.
  unsigned si = 0;
  CHECK(init_level(p, a1, j1, z, z, si) == 0 && si == kInitStepInvalid);
  // No force and no jerk (a = j = 0, e.g. G = 0 without drag): level 0 and no status bit.
  unsigned sz = 0;
  CHECK(init_level(p, z, z, z, z, sz) == 0 && sz == 0);
  // Symmetric centre (issue A5): a = j = 0 but snap nonzero → Aarseth dt = 0. Level 0, no kDtUnderflow.
  unsigned sa5 = 0;
  CHECK(init_level(p, z, z, d4{1, 0, 0, 0}, z, sa5) == 0 && sa5 == 0);

  // Centre body: zero force, level 0 in adaptive mode.
  unsigned sc = update_particle(p, true, a1, j1, 4.0, x, v, a, j, t, next, lv);
  CHECK(sc == 0 && lv == 0 && a.x == 0.0 && j.y == 0.0);

  // Fixed mode: the level is the fixed level, whatever the forces.
  c.mode = StepMode::Fixed;
  c.fixed_level = 3;
  StepParams pf = make_params(c, tick, 0, true);
  CHECK(pf.fixed_level == 3);
  update_particle(pf, false, a1, j1, 4.0, x, v, a, j, t, next, lv);
  CHECK(lv == 3 && next == (int64_t(1) << 7));

  // NaN force sets kNaN.
  const d4 nanv{std::nan(""), 0, 0, 0};
  unsigned sn = update_particle(p, false, nanv, j1, 4.0, x, v, a, j, t, next, lv);
  CHECK(sn & kNaN);

  // NaN step estimate (0/0 in the corrector with no force, issue A3): keep the current level 5. Do not go coarser.
  // No force is normal, so there is no status bit.
  Config cb = c;
  cb.mode = StepMode::Block;
  StepParams pn = make_params(cb, tick, 1024, false);
  d4 an = z, jn = z;
  lv = 5;
  unsigned sa3 = update_particle(pn, false, z, z, 4.0, x, v, an, jn, t, next, lv);
  CHECK(lv == 5 && sa3 == 0);

  // Close pair: r^2min below r2_close sets kClosePair.
  Config cc = c;
  cc.mode = StepMode::Block;
  cc.r2_close = 1.0;
  StepParams pc = make_params(cc, tick, 0, true);
  CHECK((update_particle(pc, false, a1, j1, 0.5, x, v, a, j, t, next, lv) & kClosePair));
  CHECK(!(update_particle(pc, false, a1, j1, 2.0, x, v, a, j, t, next, lv) & kClosePair));
}

// Step estimate from the corrector at t1 (issue A3). h = 1 here (T = 1024 ticks, tick = 1/1024).
// dt = 0 (eta = 0) gives the finest level and kDtUnderflow. dt = Inf gives the coarsest level. NaN (0/0, no force)
// keeps the level with no status bit. The eta values (0 and 1e308) are edge inputs chosen to hit each case, not
// realistic ones.
static void test_step_estimate_edges() {
  Config c;
  c.dt_max = 1.0;
  c.max_level = 10;
  c.mode = StepMode::Block;
  const double tick = c.dt_max / 1024.0;
  const d4 a1{1, 0, 0, 0}, j1{0, 1, 0, 0}, z{0, 0, 0, 0};
  d4 x{1, 0, 0, 1}, v{0, 1, 0, 0}, a = z, j = z;
  int64_t t = 0, next = 0;
  int lv = 5;

  // dt = 0: the finest level, with the underflow bit.
  c.eta = 0.0;
  unsigned s0 = update_particle(make_params(c, tick, 1024, false), false, a1, j1, 4.0, x, v, a, j, t, next, lv);
  CHECK(lv == 10 && (s0 & kDtUnderflow));

  // dt = Inf (the product eta * (a s + j j) overflows): the coarsest level, no underflow bit.
  c.eta = 1e308;
  lv = 0;
  a = z;
  j = z;
  unsigned si = update_particle(make_params(c, tick, 1024, false), false, a1, j1, 4.0, x, v, a, j, t, next, lv);
  CHECK(lv == 0 && !(si & kDtUnderflow));

  // dt = NaN (0/0, no force): keep the level, no status bit.
  c.eta = 0.01;
  lv = 5;
  a = z;
  j = z;
  unsigned sn = update_particle(make_params(c, tick, 1024, false), false, z, z, 4.0, x, v, a, j, t, next, lv);
  CHECK(lv == 5 && sn == 0);
}

// kDtUnderflow from a positive step below dt_min, through the corrector (update_particle) and the cold start
// (init_level). dt_min = dt_max / 2^max_level = tick here. The eta values are edge inputs that make the estimate tiny.
static void test_underflow_bit() {
  Config c;
  c.dt_max = 1.0;
  c.max_level = 10;
  c.mode = StepMode::Block;
  const double tick = c.dt_max / 1024.0;
  const d4 a1{1, 0, 0, 0}, j1{0, 1, 0, 0}, z{0, 0, 0, 0};
  const d4 x0{1, 0, 0, 1}, v0{0, 1, 0, 0};

  // Corrector: tiny eta gives a positive step far below dt_min. The level is the finest one, with the bit.
  d4 x = x0, v = v0, a = z, j = z;
  int64_t t = 0, next = 0;
  int lv = 5;
  c.eta = 1e-12;
  unsigned s1 = update_particle(make_params(c, tick, 1024, false), false, a1, j1, 4.0, x, v, a, j, t, next, lv);
  CHECK(lv == 10 && (s1 & kDtUnderflow));

  // Same inputs with eta = 0.01: the step is above dt_min, so there is no bit.
  c.eta = 0.01;
  x = x0; v = v0; a = z; j = z; t = 0; next = 0; lv = 5;
  unsigned s2 = update_particle(make_params(c, tick, 1024, false), false, a1, j1, 4.0, x, v, a, j, t, next, lv);
  CHECK(!(s2 & kDtUnderflow));

  // Cold start: tiny eta_init gives the finest level and the bit. It is not an invalid estimate.
  c.eta_init = 1e-12;
  const d4 s4{1, 1, 0, 0}, cr{0.5, 0.5, 0, 0};
  unsigned s3 = 0;
  const int lv3 = init_level(make_params(c, tick, 0, true), a1, j1, s4, cr, s3);
  CHECK(lv3 == 10 && (s3 & kDtUnderflow) && !(s3 & kInitStepInvalid));
}

// update_particle_d with LinearDrag: the status bits come from pass 2, the pass that gives the stored state.
// A NaN velocity in pass 1 goes into pass 2, so kNaN is not lost.
static void test_update_particle_d_status() {
  Config c;
  c.dt_max = 1.0;
  c.max_level = 10;
  c.dissipation = Dissipation::LinearDrag;
  c.drag_tau = 1.0;
  const double tick = c.dt_max / 1024.0;
  const int64_t T = 8;
  const StepParams p = make_params(c, tick, T, false);
  const d4 a1{1, 0, 0, 0}, j1{0, 1, 0, 0}, vp{0, 1, 0, 0};
  const d4 x0{1, 0, 0, 1}, v0{0, 1, 0, 0}, a0{1, 0, 0, 0}, j0{0, 1, 0, 0};

  // The returned status is the status of a plain pass 2 from the saved state.
  d4 x = x0, v = v0, a = a0, j = j0;
  int64_t t = 0, next = T;
  int lv = 7;
  double wd = 0;
  const unsigned st = update_particle_d<Dissipation::LinearDrag>(p, false, true, a1, j1, vp, 4.0, x, v, a, j, t, next, lv, wd);
  d4 xr = x0, vr = v0, ar = a0, jr = j0;
  int64_t tr = 0, nr = T;
  int lr = 7;
  d4 a1r = a1, j1r = j1;
  dissipation_term<Dissipation::LinearDrag>(p, vp, a1r, j1r);
  update_particle(p, false, a1r, j1r, 4.0, xr, vr, ar, jr, tr, nr, lr);  // pass 1
  const d4 v1 = vr;
  xr = x0; vr = v0; ar = a0; jr = j0; tr = 0; nr = T; lr = 7;
  a1r = a1; j1r = j1;
  dissipation_term<Dissipation::LinearDrag>(p, v1, a1r, j1r);
  const unsigned st2 = update_particle(p, false, a1r, j1r, 4.0, xr, vr, ar, jr, tr, nr, lr);  // pass 2
  CHECK(st == st2);
  CHECK(v.x == vr.x && v.y == vr.y && lv == lr);

  // NaN predicted velocity: kNaN reaches the returned status.
  x = x0; v = v0; a = a0; j = j0; t = 0; next = T; lv = 7; wd = 0;
  const d4 vnan{std::nan(""), 0, 0, 0};
  CHECK(update_particle_d<Dissipation::LinearDrag>(p, false, true, a1, j1, vnan, 4.0, x, v, a, j, t, next, lv, wd) & kNaN);
}

// accumulate: Newtonian pull, Plummer softening, and the jerk against a finite difference.
static void test_accumulate() {
  const d4 xi{0, 0, 0, 1}, vi{0, 0, 0, 0};
  AJ f;
  accumulate(f, xi, vi, d4{2, 0, 0, 3.0}, d4{0, 0, 0, 0}, 0.0);
  CHECK_NEAR(f.ax, 3.0 / 4.0, 1e-15);  // m / r^2 towards the source
  CHECK(f.ay == 0.0 && f.az == 0.0 && f.jx == 0.0);
  CHECK_NEAR(f.r2min, 4.0, 1e-15);

  AJ fs;
  accumulate(fs, xi, vi, d4{2, 0, 0, 3.0}, d4{0, 0, 0, 0}, 1.0);
  CHECK_NEAR(fs.ax, 3.0 * 2.0 / std::pow(5.0, 1.5), 1e-15);  // m d / (r^2 + eps^2)^(3/2)

  // Source moves at constant velocity; the jerk is the time derivative of the acceleration.
  const double u = 0.5, h = 1e-5;
  auto acc_at = [&](double t) {
    AJ g;
    accumulate(g, xi, vi, d4{2, u * t, 0, 3.0}, d4{0, u, 0, 0}, 0.0);
    return g;
  };
  const AJ at = acc_at(0.0), ap = acc_at(h), am = acc_at(-h);
  const double jy_fd = (ap.ay - am.ay) / (2 * h);
  const double jx_fd = (ap.ax - am.ax) / (2 * h);
  CHECK_NEAR(at.jy, jy_fd, 1e-7 * std::fabs(jy_fd));
  CHECK_NEAR(at.jx, jx_fd, 1e-7 * std::fabs(jx_fd) + 1e-12);
}

// Taylor trajectory of one body (TZ 3.2). Exact for constant jerk. The mass stays in x.w.
struct Body {
  d4 x, v, a, j;
};

static double pos(const Body& b, int k, double t) {
  return comp(b.x, k) + comp(b.v, k) * t + comp(b.a, k) * t * t / 2 + comp(b.j, k) * t * t * t / 6;
}

// Pair acceleration on body i from body s at time t, component k. G is 1. The mass of s is in s.x.w.
static double pair_acc(const Body& bi, const Body& bs, int k, double t, double eps2) {
  double r2 = eps2, dk = 0;
  for (int c = 0; c < 3; ++c) {
    const double dc = pos(bs, c, t) - pos(bi, c, t);
    r2 += dc * dc;
    if (c == k) dk = dc;
  }
  return bs.x.w * dk / std::pow(r2, 1.5);
}

// Snap and crackle at t = 0 by finite differences. The second derivative uses a 5-point stencil (error h^4).
// The third derivative uses a 4-point stencil (error h^2). Richardson with h and h/2 removes the leading error.
static void fd_snap_crackle(const Body& bi, const Body& bs, double eps2, double h, double s[3], double c[3]) {
  for (int k = 0; k < 3; ++k) {
    auto A = [&](double t) { return pair_acc(bi, bs, k, t, eps2); };
    auto d2 = [&](double hh) { return (-A(2 * hh) + 16 * A(hh) - 30 * A(0) + 16 * A(-hh) - A(-2 * hh)) / (12 * hh * hh); };
    auto d3 = [&](double hh) { return (A(2 * hh) - 2 * A(hh) + 2 * A(-hh) - A(-2 * hh)) / (2 * hh * hh * hh); };
    s[k] = (16 * d2(h / 2) - d2(h)) / 15;
    c[k] = (4 * d3(h / 2) - d3(h)) / 3;
  }
}

// Compares accumulate_sc with the finite differences. The error is a vector-norm ratio.
static void check_sc_fd(const Body& bi, const Body& bs, double eps2) {
  double s_fd[3], c_fd[3];
  fd_snap_crackle(bi, bs, eps2, 1e-2, s_fd, c_fd);
  SC f;
  accumulate_sc(f, bi.x, bi.v, bi.a, bi.j, bs.x, bs.v, bs.a, bs.j, eps2);
  double ds = 0, ns = 0, dc = 0, nc = 0;
  for (int k = 0; k < 3; ++k) {
    ds += (f.s[k] - s_fd[k]) * (f.s[k] - s_fd[k]);
    ns += f.s[k] * f.s[k];
    dc += (f.c[k] - c_fd[k]) * (f.c[k] - c_fd[k]);
    nc += f.c[k] * f.c[k];
  }
  const double snap_err = std::sqrt(ds / ns), crackle_err = std::sqrt(dc / nc);
  CHECK_NEAR(snap_err, 0.0, 1e-8);     // Measured 2e-11.
  CHECK_NEAR(crackle_err, 0.0, 1e-6);  // Measured 1e-8.
}

// accumulate_sc against finite differences. The bodies have nonzero dr, dv, da and dj, so every term counts.
static void test_accumulate_sc() {
  const Body bi{{0.1, -0.2, 0.3, 1.0}, {0.3, -0.2, 0.1, 0}, {0.5, 0.4, -0.3, 0}, {-0.2, 0.6, 0.1, 0}};
  const Body bs{{1.2, 0.5, -0.8, 2.0}, {-0.1, 0.4, 0.2, 0}, {-0.3, 0.2, 0.6, 0}, {0.4, -0.5, 0.3, 0}};
  check_sc_fd(bi, bs, 0.05);
  check_sc_fd(bi, bs, 0.0);
}

// add_drag_sc with hand values: tau = 2, j = (4, -2, 1), s = (1, 1, 1), c = (3, 0, -1).
// s = s - j / tau = (-1, 2, 0.5). c = c - s_new / tau = (3.5, -1, -1.25).
static void test_add_drag_sc() {
  d4 s{1, 1, 1, 0}, c{3, 0, -1, 0};
  add_drag_sc(2.0, d4{4, -2, 1, 0}, s, c);
  CHECK_NEAR(s.x, -1.0, 1e-15);
  CHECK_NEAR(s.y, 2.0, 1e-15);
  CHECK_NEAR(s.z, 0.5, 1e-15);
  CHECK_NEAR(c.x, 3.5, 1e-15);
  CHECK_NEAR(c.y, -1.0, 1e-15);
  CHECK_NEAR(c.z, -1.25, 1e-15);
}

static void test_make_params() {
  Config c;
  c.mode = StepMode::Block;
  CHECK(make_params(c, 1.0, 5, false).fixed_level == -1);
  c.mode = StepMode::Fixed;
  c.fixed_level = 4;
  StepParams p = make_params(c, 1.0, 5, false);
  CHECK(p.fixed_level == 4 && p.T == 5 && !p.init);
  // eta_init = 0 means "use eta". A positive eta_init is passed as it is.
  Config e;
  e.eta = 0.02;
  e.eta_init = 0.0;
  CHECK(make_params(e, 1.0, 0, false).eta_init == 0.02);
  e.eta_init = 0.005;
  CHECK(make_params(e, 1.0, 0, false).eta_init == 0.005);
}

// Independent check of the pair force (W6). The reference is written from the textbook formulas in long double,
// not from accumulate(). It checks a and j for 16 random particles with softening. This test catches a wrong formula,
// which a GPU-vs-CPU comparison with the same code would not catch.
static void test_force_independent_longdouble() {
  std::mt19937 rng(12345);
  std::uniform_real_distribution<double> u(-1.0, 1.0);
  const int n = 16;
  const double eps2 = 0.01;
  std::vector<h4nb::d4> x(n), v(n);
  for (int i = 0; i < n; ++i) {
    x[i] = h4nb::d4{u(rng), u(rng), u(rng), 0.5 + 0.5 * (u(rng) + 1.0)};
    v[i] = h4nb::d4{0.3 * u(rng), 0.3 * u(rng), 0.3 * u(rng), 0.0};
  }
  for (int i = 0; i < n; ++i) {
    h4nb::AJ f;
    long double ax = 0, ay = 0, az = 0, jx = 0, jy = 0, jz = 0;
    for (int j = 0; j < n; ++j) {
      if (j == i) continue;
      h4nb::accumulate(f, x[i], v[i], x[j], v[j], eps2);
      // Reference: r = xj - xi, dv = vj - vi, R2 = r.r + eps2, m = mass of j.
      const long double rx = (long double)x[j].x - x[i].x, ry = (long double)x[j].y - x[i].y,
                        rz = (long double)x[j].z - x[i].z;
      const long double dvx = (long double)v[j].x - v[i].x, dvy = (long double)v[j].y - v[i].y,
                        dvz = (long double)v[j].z - v[i].z;
      const long double R2 = rx * rx + ry * ry + rz * rz + eps2;
      const long double R3 = R2 * sqrtl(R2);
      const long double m = x[j].w;
      const long double rdv = rx * dvx + ry * dvy + rz * dvz;
      ax += m * rx / R3;
      ay += m * ry / R3;
      az += m * rz / R3;
      jx += m * (dvx / R3 - 3.0L * rdv * rx / (R3 * R2));
      jy += m * (dvy / R3 - 3.0L * rdv * ry / (R3 * R2));
      jz += m * (dvz / R3 - 3.0L * rdv * rz / (R3 * R2));
    }
    const double sc = std::fabs((double)ax) + std::fabs((double)ay) + std::fabs((double)az);
    const double sj = std::fabs((double)jx) + std::fabs((double)jy) + std::fabs((double)jz);
    CHECK_NEAR(f.ax, (double)ax, 1e-12 * sc);
    CHECK_NEAR(f.ay, (double)ay, 1e-12 * sc);
    CHECK_NEAR(f.az, (double)az, 1e-12 * sc);
    CHECK_NEAR(f.jx, (double)jx, 1e-12 * sj);
    CHECK_NEAR(f.jy, (double)jy, 1e-12 * sj);
    CHECK_NEAR(f.jz, (double)jz, 1e-12 * sj);
  }
}

int main() {
  test_force_independent_longdouble();
  test_predict();
  test_correct_exact_quadratic();
  test_aarseth();
  test_choose_level();
  test_update_particle();
  test_step_estimate_edges();
  test_underflow_bit();
  test_update_particle_d_status();
  test_accumulate();
  test_accumulate_sc();
  test_add_drag_sc();
  test_make_params();
  std::puts("test_math: OK");
  return 0;
}
