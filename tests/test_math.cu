// Unit tests for the per-particle Hermite math (src/hermite.cuh). Host only, no GPU needed.
#include <cmath>
#include <cstdio>
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
  // No force at all (a = j = s = c = 0, e.g. G = 0 without drag): level 0 and no status bit.
  unsigned sz = 0;
  CHECK(init_level(p, z, z, z, z, sz) == 0 && sz == 0);

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

  // Close pair: r^2min below r2_close sets kClosePair.
  Config cc = c;
  cc.mode = StepMode::Block;
  cc.r2_close = 1.0;
  StepParams pc = make_params(cc, tick, 0, true);
  CHECK((update_particle(pc, false, a1, j1, 0.5, x, v, a, j, t, next, lv) & kClosePair));
  CHECK(!(update_particle(pc, false, a1, j1, 2.0, x, v, a, j, t, next, lv) & kClosePair));
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

static void test_make_params() {
  Config c;
  c.mode = StepMode::Block;
  CHECK(make_params(c, 1.0, 5, false).fixed_level == -1);
  c.mode = StepMode::Fixed;
  c.fixed_level = 4;
  StepParams p = make_params(c, 1.0, 5, false);
  CHECK(p.fixed_level == 4 && p.T == 5 && !p.init);
}

int main() {
  test_predict();
  test_correct_exact_quadratic();
  test_aarseth();
  test_choose_level();
  test_update_particle();
  test_accumulate();
  test_make_params();
  std::puts("test_math: OK");
  return 0;
}
