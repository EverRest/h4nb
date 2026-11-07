// See diag_sum.hpp. This file is compiled once, so every caller runs the same machine code.
#include "diag_sum.hpp"
#include <cmath>
#include <cstddef>

namespace h4nb {
namespace {
// Neumaier compensated sum (TZ 4.4, 6.1). It reduces round-off error.
struct NSum {
  double s = 0, c = 0;
  void add(double x) {
    const double t = s + x;
    c += std::fabs(s) >= std::fabs(x) ? (s - t) + x : (x - t) + s;
    s = t;
  }
  double value() const { return s + c; }
};
}  // namespace

Diagnostics diag_sum(const Particles& p, const double* ph, int G, const double* wd, double Gc) {
  const size_t N = p.size();
  NSum K, U, P[3], L[3], W;
  for (size_t i = 0; i < N; ++i) {
    double phi = 0;
    for (int h = 0; h < G; ++h) phi += ph[size_t(h) * N + i];
    const double mi = p.m[i];
    U.add(mi * phi);
    K.add(0.5 * mi * (p.vx[i] * p.vx[i] + p.vy[i] * p.vy[i] + p.vz[i] * p.vz[i]));
    P[0].add(mi * p.vx[i]); P[1].add(mi * p.vy[i]); P[2].add(mi * p.vz[i]);
    L[0].add(mi * (p.y[i] * p.vz[i] - p.z[i] * p.vy[i]));
    L[1].add(mi * (p.z[i] * p.vx[i] - p.x[i] * p.vz[i]));
    L[2].add(mi * (p.x[i] * p.vy[i] - p.y[i] * p.vx[i]));
    W.add(wd[i]);
  }
  Diagnostics r;
  r.K = K.value();
  r.U = -Gc * U.value();
  r.E = r.K + r.U;
  r.W_diss = W.value();
  for (int k = 0; k < 3; ++k) {
    r.P[k] = P[k].value();
    r.L[k] = L[k].value();
  }
  return r;
}
}  // namespace h4nb
