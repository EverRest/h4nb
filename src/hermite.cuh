// Per-particle Hermite math. It is __host__ __device__, so the CPU oracle in tests runs the same code as the GPU.
#pragma once
#include <math.h>
#include <cmath>
#include <cstdint>
#include "h4nb/h4nb.hpp"

#ifdef __CUDACC__
#define H4_HD __host__ __device__ inline
#else
#define H4_HD inline
#endif

namespace h4nb {

struct alignas(32) d4 { double x, y, z, w; };  // Positions: w is the mass. Other vectors: w is not used (0).

H4_HD double h4_rsqrt(double x) {
#ifdef __CUDA_ARCH__
  return ::rsqrt(x);
#else
  return 1.0 / std::sqrt(x);
#endif
}
// NaN and Inf: x - x is NaN for both, and NaN == 0 is false. Valid because fast-math is banned.
H4_HD bool h4_nonfinite(double x) { return !(x - x == 0); }
H4_HD double norm3(const d4& u) { return ::sqrt(u.x * u.x + u.y * u.y + u.z * u.z); }

// Taylor predictor (TZ 3.2). It keeps xp.w as the mass.
H4_HD void predict(const d4& x, const d4& v, const d4& a, const d4& j, double dt, d4& xp, d4& vp) {
  const double h2 = 0.5 * dt * dt, h3 = h2 * dt * (1.0 / 3.0);
  xp = d4{x.x + v.x * dt + a.x * h2 + j.x * h3, x.y + v.y * dt + a.y * h2 + j.y * h3,
          x.z + v.z * dt + a.z * h2 + j.z * h3, x.w};
  vp = d4{v.x + a.x * dt + j.x * h2, v.y + a.y * dt + j.y * h2, v.z + a.z * dt + j.z * h2, 0.0};
}

struct AJ {
  double ax = 0, ay = 0, az = 0, jx = 0, jy = 0, jz = 0;
  double r2min = 1e300;  // Closest source seen (TZ 7.1).
};

// Adds the pull of source (xj, vj; mass xj.w) on target (xi, vi) (TZ 3.3). The caller skips i == j. G is applied later.
H4_HD void accumulate(AJ& f, const d4& xi, const d4& vi, const d4& xj, const d4& vj, double eps2) {
  const double dx = xj.x - xi.x, dy = xj.y - xi.y, dz = xj.z - xi.z;
  const double dvx = vj.x - vi.x, dvy = vj.y - vi.y, dvz = vj.z - vi.z;
  const double r2 = dx * dx + dy * dy + dz * dz;
  f.r2min = ::fmin(f.r2min, r2);
  const double rinv = h4_rsqrt(r2 + eps2);
  const double rinv2 = rinv * rinv;
  const double mr3 = xj.w * rinv * rinv2;
  const double alpha = 3.0 * (dx * dvx + dy * dvy + dz * dvz) * rinv2;
  f.ax += mr3 * dx;
  f.ay += mr3 * dy;
  f.az += mr3 * dz;
  f.jx += mr3 * (dvx - alpha * dx);
  f.jy += mr3 * (dvy - alpha * dy);
  f.jz += mr3 * (dvz - alpha * dz);
}

// Aarseth criterion for 4th-order Hermite (TZ 3.6).
H4_HD double aarseth_dt(double a, double j, double s, double c, double eta) {
  return ::sqrt(eta * (a * s + j * j) / (j * c + s * s));
}

// Hermite corrector (TZ 3.4, Makino and Aarseth 1992). It updates x and v, but not x.w. It returns the Aarseth step at t1.
H4_HD double correct(d4& x, d4& v, const d4& a0, const d4& j0, const d4& a1, const d4& j1, double h, double eta) {
  const double c12 = h * h * (1.0 / 12.0);
  const d4 vn{v.x + 0.5 * (a0.x + a1.x) * h + (j0.x - j1.x) * c12,
              v.y + 0.5 * (a0.y + a1.y) * h + (j0.y - j1.y) * c12,
              v.z + 0.5 * (a0.z + a1.z) * h + (j0.z - j1.z) * c12, 0.0};
  x.x += 0.5 * (v.x + vn.x) * h + (a0.x - a1.x) * c12;
  x.y += 0.5 * (v.y + vn.y) * h + (a0.y - a1.y) * c12;
  x.z += 0.5 * (v.z + vn.z) * h + (a0.z - a1.z) * c12;
  v = vn;
  // TZ 3.5 gives the snap at t0. The criterion needs it at t1: s1 = s0 + c h.
  const double ih = 1.0 / h, ih2 = ih * ih, ih3 = ih2 * ih;
  const d4 s0{(-6.0 * (a0.x - a1.x) - h * (4.0 * j0.x + 2.0 * j1.x)) * ih2,
              (-6.0 * (a0.y - a1.y) - h * (4.0 * j0.y + 2.0 * j1.y)) * ih2,
              (-6.0 * (a0.z - a1.z) - h * (4.0 * j0.z + 2.0 * j1.z)) * ih2, 0.0};
  const d4 cr{(12.0 * (a0.x - a1.x) + 6.0 * h * (j0.x + j1.x)) * ih3,
              (12.0 * (a0.y - a1.y) + 6.0 * h * (j0.y + j1.y)) * ih3,
              (12.0 * (a0.z - a1.z) + 6.0 * h * (j0.z + j1.z)) * ih3, 0.0};
  const d4 s1{s0.x + cr.x * h, s0.y + cr.y * h, s0.z + cr.z * h, 0.0};
  return aarseth_dt(norm3(a1), norm3(j1), norm3(s1), norm3(cr), eta);
}

// Block level for a wanted step. Level k has the step dt_max / 2^k, which is 2^(max_level-k) ticks.
// The level can go to any finer level. It can go up one level only, and only when t is aligned to the coarser step.
H4_HD int choose_level(double dt_want, double dt_max, int k_old, int64_t t_ticks, int max_level, bool& underflow) {
  int k = 0;
  double d = dt_max;
  while (d > dt_want && k < max_level) {
    d *= 0.5;
    ++k;
  }
  if (d > dt_want) underflow = true;  // dt_min is still too large (TZ 7.1)
  if (k < k_old) {
    k = k_old - 1;
    if (t_ticks % (int64_t(1) << (max_level - k)) != 0) k = k_old;
  }
  return k;
}

struct StepParams {
  int64_t T;  // Block time of this step, in ticks.
  double tick, dt_max, eta, eta_init, G, r2_close;
  int max_level;
  int fixed_level;  // 0 or more: Fixed mode. -1: adaptive mode.
  bool init;        // First force evaluation. There is no corrector.
  double drag_tau;     // LinearDrag only (Config::drag_tau).
  double drag_vbg[3];  // LinearDrag only (Config::drag_vbg).
};

inline StepParams make_params(const Config& c, double tick, int64_t T, bool init) {
  return StepParams{T, tick, c.dt_max, c.eta, c.eta_init, c.G, c.r2_close, c.max_level,
                    c.mode == StepMode::Fixed ? c.fixed_level : -1, init, c.drag_tau,
                    {c.drag_vbg[0], c.drag_vbg[1], c.drag_vbg[2]}};
}

// Applies the new force (a1, j1, already multiplied by G) to one active particle. It returns StatusBits.
H4_HD unsigned update_particle(const StepParams& p, bool is_center, d4 a1, d4 j1, double r2min, d4& x, d4& v, d4& a,
                               d4& j, int64_t& t, int64_t& next, int& level) {
  unsigned st = 0;
  if (r2min < p.r2_close) st |= kClosePair;
  if (h4_nonfinite(a1.x + a1.y + a1.z + j1.x + j1.y + j1.z)) st |= kNaN;
  bool under = false;
  int lv;
  if (is_center) {
    a = d4{0, 0, 0, 0};
    j = d4{0, 0, 0, 0};
    lv = p.fixed_level >= 0 ? p.fixed_level : 0;
  } else if (p.init) {
    a = a1;
    j = j1;
    lv = p.fixed_level >= 0 ? p.fixed_level
                            : choose_level(p.eta_init * norm3(a1) / norm3(j1), p.dt_max, 0, p.T, p.max_level, under);
  } else {
    const double dtw = correct(x, v, a, j, a1, j1, double(p.T - t) * p.tick, p.eta);
    a = a1;
    j = j1;
    lv = p.fixed_level >= 0 ? p.fixed_level : choose_level(dtw, p.dt_max, level, p.T, p.max_level, under);
    if (h4_nonfinite(x.x + x.y + x.z + v.x + v.y + v.z)) st |= kNaN;
  }
  if (under) st |= kDtUnderflow;
  level = lv;
  t = p.T;
  next = p.T + (int64_t(1) << (p.max_level - lv));
  return st;
}

// Dissipative acceleration at the velocity v (research R7). Use it only for D != Off.
template <Dissipation D>
H4_HD d4 dissipation_acc(const StepParams& p, const d4& v) {
  static_assert(D == Dissipation::LinearDrag, "Add the new model here.");
  return d4{-(v.x - p.drag_vbg[0]) / p.drag_tau, -(v.y - p.drag_vbg[1]) / p.drag_tau,
            -(v.z - p.drag_vbg[2]) / p.drag_tau, 0.0};
}

// Adds the dissipative term to the gravitational a1 and j1 (already multiplied by G) at the predicted velocity vp.
// LinearDrag: a_tot = a1 + a_diss(vp). j_tot = j1 - a_tot / tau, because d/dt a_diss = -(dv/dt) / tau and dv/dt = a_tot.
// Off: the function does nothing. The compiler removes it, so the Off path has the same instructions as before.
template <Dissipation D>
H4_HD void dissipation_term(const StepParams& p, const d4& vp, d4& a1, d4& j1) {
  if constexpr (D == Dissipation::LinearDrag) {
    const d4 ad = dissipation_acc<D>(p, vp);
    a1 = d4{a1.x + ad.x, a1.y + ad.y, a1.z + ad.z, 0.0};
    j1 = d4{j1.x - a1.x / p.drag_tau, j1.y - a1.y / p.drag_tau, j1.z - a1.z / p.drag_tau, 0.0};
  }
}

// Power m v . a_diss(v) of the dissipative force on a particle with mass m and velocity v.
template <Dissipation D>
H4_HD double dissipation_power(const StepParams& p, double m, const d4& v) {
  const d4 ad = dissipation_acc<D>(p, v);
  return m * (v.x * ad.x + v.y * ad.y + v.z * ad.z);
}

// Time derivative of dissipation_power() for a particle with total acceleration a.
template <Dissipation D>
H4_HD double dissipation_power_rate(const StepParams& p, double m, const d4& v, const d4& a) {
  static_assert(D == Dissipation::LinearDrag, "Add the new model here.");
  const d4 ad = dissipation_acc<D>(p, v);
  return m * (a.x * ad.x + a.y * ad.y + a.z * ad.z - (v.x * a.x + v.y * a.y + v.z * a.z) / p.drag_tau);
}

// update_particle() with the dissipation model D. drag is false for particle 0 (the central body).
// vp is the predicted velocity at the block time p.T. wd is the work of the dissipative force on this particle since t = 0.
// For D == Off, this is the plain update_particle() call. vp, drag and wd are not used.
// The work uses the corrected trapezoid rule over each step (4th order, the same order as the Hermite step):
// W += h/2 (P0 + P1) + h^2/12 (P0' - P1'), with P' = m (a . a_diss + v . d(a_diss)/dt) = m (a . a_diss - v . a / tau).
// a is the total acceleration that is stored at each end of the step.
template <Dissipation D>
H4_HD unsigned update_particle_d(const StepParams& p, bool is_center, bool drag, d4 a1, d4 j1, const d4& vp, double r2min,
                                 d4& x, d4& v, d4& a, d4& j, int64_t& t, int64_t& next, int& level, double& wd) {
  if constexpr (D == Dissipation::Off) {
    return update_particle(p, is_center, a1, j1, r2min, x, v, a, j, t, next, level);
  } else {
    if (!drag || is_center) return update_particle(p, is_center, a1, j1, r2min, x, v, a, j, t, next, level);
    dissipation_term<D>(p, vp, a1, j1);
    const d4 v0 = v, a0 = a;
    const double h = double(p.T - t) * p.tick;
    const unsigned st = update_particle(p, is_center, a1, j1, r2min, x, v, a, j, t, next, level);
    if (!p.init)
      wd += 0.5 * h * (dissipation_power<D>(p, x.w, v0) + dissipation_power<D>(p, x.w, v)) +
            h * h / 12.0 * (dissipation_power_rate<D>(p, x.w, v0, a0) - dissipation_power_rate<D>(p, x.w, v, a));
    return st;
  }
}

}  // namespace h4nb
