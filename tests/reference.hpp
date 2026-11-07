// CPU oracle: the same block-step algorithm as the GPU library, O(N^2) per step. Small N only.
#pragma once
#include <algorithm>
#include <cmath>
#include <vector>
#include "hermite.cuh"

namespace ref {
using h4nb::d4;

class Ref {
 public:
  Ref(const h4nb::Particles& p, const h4nb::Config& c)
      : c_(c), n_(int(p.size())), tick_(c.dt_max / std::ldexp(1.0, c.max_level)), id_(p.id), x_(n_), v_(n_),
        a_(n_), j_(n_), t_(n_, 0), next_(n_, 0), level_(n_, 0), wd_(n_, 0.0) {
    for (int i = 0; i < n_; ++i) {
      x_[i] = d4{p.x[i], p.y[i], p.z[i], p.m[i]};
      v_[i] = d4{p.vx[i], p.vy[i], p.vz[i], 0.0};
    }
    if (c_.fixed_center) v_[0] = d4{0, 0, 0, 0};
    step(true);
    init_levels();
  }
  void advance_to(double t) {
    const int64_t target = int64_t(std::llround(t / c_.dt_max)) << c_.max_level;
    while (T_ < target) step(false);
  }
  double time() const { return double(T_) * tick_; }
  h4nb::Particles state() const {
    h4nb::Particles p;
    p.resize(size_t(n_));
    p.id = id_;
    for (int i = 0; i < n_; ++i) {
      p.m[i] = x_[i].w; p.x[i] = x_[i].x; p.y[i] = x_[i].y; p.z[i] = x_[i].z;
      p.vx[i] = v_[i].x; p.vy[i] = v_[i].y; p.vz[i] = v_[i].z;
    }
    return p;
  }
  std::vector<int> levels() const { return level_; }
  unsigned status() const { return status_; }
  // Work of the dissipative forces since t = 0: the sum of the per-particle work in index order (Neumaier), as on the GPU.
  double w_diss() const {
    double s = 0, c = 0;
    for (double x : wd_) {
      const double t = s + x;
      c += std::fabs(s) >= std::fabs(x) ? (s - t) + x : (x - t) + s;
      s = t;
    }
    return s + c;
  }

 private:
  // Cold start (issue A1): first levels from the full Aarseth estimate. Snap and crackle use all sources at t = 0.
  // Same as init_level_kernel. The center (fixed_center, particle 0) keeps the level of the update.
  void init_levels() {
    const h4nb::StepParams p = h4nb::make_params(c_, tick_, 0, true);
    for (int i = 0; i < n_; ++i) {
      if (c_.fixed_center && i == 0) continue;
      h4nb::SC sc;
      for (int s = 0; s < n_; ++s)
        if (s != i) h4nb::accumulate_sc(sc, x_[i], v_[i], a_[i], j_[i], x_[s], v_[s], a_[s], j_[s], c_.eps2);
      d4 snap{c_.G * sc.s[0], c_.G * sc.s[1], c_.G * sc.s[2], 0.0};
      d4 crackle{c_.G * sc.c[0], c_.G * sc.c[1], c_.G * sc.c[2], 0.0};
      // Particle 0 has no drag (same rule as update()). The others have LinearDrag if it is on.
      if (c_.dissipation == h4nb::Dissipation::LinearDrag && i != 0) h4nb::add_drag_sc(c_.drag_tau, j_[i], snap, crackle);
      unsigned st = 0;
      level_[i] = h4nb::init_level(p, a_[i], j_[i], snap, crackle, st);
      next_[i] = int64_t(1) << (c_.max_level - level_[i]);
      status_ |= st;
    }
  }
  void step(bool init) {
    const int64_t Tn = init ? 0 : *std::min_element(next_.begin(), next_.end());
    std::vector<d4> xp(n_), vp(n_);
    for (int i = 0; i < n_; ++i) h4nb::predict(x_[i], v_[i], a_[i], j_[i], double(Tn - t_[i]) * tick_, xp[i], vp[i]);
    std::vector<int> act;
    for (int i = 0; i < n_; ++i)
      if (next_[i] == Tn) act.push_back(i);
    std::vector<h4nb::AJ> f(act.size());  // all forces first, then all updates (as on the GPU)
    for (size_t k = 0; k < act.size(); ++k)
      for (int s = 0; s < n_; ++s)
        if (s != act[k]) h4nb::accumulate(f[k], xp[act[k]], vp[act[k]], xp[s], vp[s], c_.eps2);
    const h4nb::StepParams p = h4nb::make_params(c_, tick_, Tn, init);
    if (c_.dissipation == h4nb::Dissipation::LinearDrag)
      update<h4nb::Dissipation::LinearDrag>(p, act, f, vp);
    else
      update<h4nb::Dissipation::Off>(p, act, f, vp);
    T_ = Tn;
  }
  // The same per-particle update as correct_kernel. D selects the dissipation model at compile time.
  template <h4nb::Dissipation D>
  void update(const h4nb::StepParams& p, const std::vector<int>& act, const std::vector<h4nb::AJ>& f,
              const std::vector<d4>& vp) {
    for (size_t k = 0; k < act.size(); ++k) {
      const int i = act[k];
      const d4 a1{c_.G * f[k].ax, c_.G * f[k].ay, c_.G * f[k].az, 0.0};
      const d4 j1{c_.G * f[k].jx, c_.G * f[k].jy, c_.G * f[k].jz, 0.0};
      status_ |= h4nb::update_particle_d<D>(p, c_.fixed_center && i == 0, i != 0, a1, j1, vp[i], f[k].r2min, x_[i],
                                            v_[i], a_[i], j_[i], t_[i], next_[i], level_[i], wd_[i]);
    }
  }

  h4nb::Config c_;
  int n_;
  double tick_;
  std::vector<int64_t> id_;
  std::vector<d4> x_, v_, a_, j_;
  std::vector<int64_t> t_, next_;
  std::vector<int> level_;
  std::vector<double> wd_;  // Work of the dissipative force on each particle since t = 0.
  int64_t T_ = 0;
  unsigned status_ = 0;
};

// Direct O(N^2) energy, momentum and angular momentum.
inline h4nb::Diagnostics direct_diagnostics(const h4nb::Particles& p, double G, double eps2) {
  h4nb::Diagnostics d;
  const size_t n = p.size();
  double U = 0;
  for (size_t i = 0; i < n; ++i) {
    const double m = p.m[i];
    d.K += 0.5 * m * (p.vx[i] * p.vx[i] + p.vy[i] * p.vy[i] + p.vz[i] * p.vz[i]);
    d.P[0] += m * p.vx[i]; d.P[1] += m * p.vy[i]; d.P[2] += m * p.vz[i];
    d.L[0] += m * (p.y[i] * p.vz[i] - p.z[i] * p.vy[i]);
    d.L[1] += m * (p.z[i] * p.vx[i] - p.x[i] * p.vz[i]);
    d.L[2] += m * (p.x[i] * p.vy[i] - p.y[i] * p.vx[i]);
    for (size_t k = i + 1; k < n; ++k) {
      const double dx = p.x[k] - p.x[i], dy = p.y[k] - p.y[i], dz = p.z[k] - p.z[i];
      U += m * p.m[k] / std::sqrt(dx * dx + dy * dy + dz * dz + eps2);
    }
  }
  d.U = -G * U;
  d.E = d.K + d.U;
  return d;
}
}  // namespace ref
