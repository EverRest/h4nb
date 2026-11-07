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
        a_(n_), j_(n_), t_(n_, 0), next_(n_, 0), level_(n_, 0) {
    for (int i = 0; i < n_; ++i) {
      x_[i] = d4{p.x[i], p.y[i], p.z[i], p.m[i]};
      v_[i] = d4{p.vx[i], p.vy[i], p.vz[i], 0.0};
    }
    if (c_.fixed_center) v_[0] = d4{0, 0, 0, 0};
    step(true);
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

 private:
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
    for (size_t k = 0; k < act.size(); ++k) {
      const int i = act[k];
      const d4 a1{c_.G * f[k].ax, c_.G * f[k].ay, c_.G * f[k].az, 0.0};
      const d4 j1{c_.G * f[k].jx, c_.G * f[k].jy, c_.G * f[k].jz, 0.0};
      status_ |= h4nb::update_particle(p, c_.fixed_center && i == 0, a1, j1, f[k].r2min, x_[i], v_[i], a_[i], j_[i],
                                       t_[i], next_[i], level_[i]);
    }
    T_ = Tn;
  }

  h4nb::Config c_;
  int n_;
  double tick_;
  std::vector<int64_t> id_;
  std::vector<d4> x_, v_, a_, j_;
  std::vector<int64_t> t_, next_;
  std::vector<int> level_;
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
