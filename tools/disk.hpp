#pragma once
#include <algorithm>
#include <cmath>
#include <random>
#include <vector>
#include "h4nb/h4nb.hpp"

// Central body (m = 1, index 0) and n disk particles. The disk particles have total mass disk_frac. G = 1.
// The radius is uniform in [r_in, r_out]. The surface density is about 1/r. The disk is thin (h = 0.01 r). The orbits are near-circular
// with the enclosed mass. The output is in the centre-of-mass frame. TZ 11.3: "approximately Keplerian".
inline h4nb::Particles make_disk(int n, double disk_frac, double r_in, double r_out, uint64_t seed) {
  constexpr double kTwoPi = 6.28318530717958647692;
  h4nb::Particles p;
  p.resize(size_t(n) + 1);
  std::mt19937_64 rng(seed);
  std::uniform_real_distribution<double> u(0.0, 1.0);
  std::normal_distribution<double> g(0.0, 1.0);
  p.id[0] = 0;
  p.m[0] = 1.0;
  for (int k = 1; k <= n; ++k) {
    const double r = r_in + (r_out - r_in) * u(rng), phi = kTwoPi * u(rng);
    const double vc = std::sqrt((1.0 + disk_frac * (r - r_in) / (r_out - r_in)) / r);
    p.id[k] = k;
    p.m[k] = disk_frac / n;
    p.x[k] = r * std::cos(phi); p.y[k] = r * std::sin(phi); p.z[k] = 0.01 * r * g(rng);
    p.vx[k] = -vc * std::sin(phi); p.vy[k] = vc * std::cos(phi); p.vz[k] = 0.0;
  }
  double M = 0, c[6] = {0, 0, 0, 0, 0, 0};
  for (size_t i = 0; i < p.size(); ++i) {
    M += p.m[i];
    c[0] += p.m[i] * p.x[i]; c[1] += p.m[i] * p.y[i]; c[2] += p.m[i] * p.z[i];
    c[3] += p.m[i] * p.vx[i]; c[4] += p.m[i] * p.vy[i]; c[5] += p.m[i] * p.vz[i];
  }
  for (size_t i = 0; i < p.size(); ++i) {
    p.x[i] -= c[0] / M; p.y[i] -= c[1] / M; p.z[i] -= c[2] / M;
    p.vx[i] -= c[3] / M; p.vy[i] -= c[4] / M; p.vz[i] -= c[5] / M;
  }
  return p;
}

struct Periods { double mean = 0, median = 0, mass_weighted = 0; };

// Keplerian period of each bound particle around body 0 (TZ 6.3). This is an estimate only when the disk is heavy.
inline Periods periods(const h4nb::Particles& p) {
  constexpr double kTwoPi = 6.28318530717958647692;
  std::vector<double> P;
  double wsum = 0, msum = 0;
  for (size_t i = 1; i < p.size(); ++i) {
    const double dx = p.x[i] - p.x[0], dy = p.y[i] - p.y[0], dz = p.z[i] - p.z[0];
    const double dvx = p.vx[i] - p.vx[0], dvy = p.vy[i] - p.vy[0], dvz = p.vz[i] - p.vz[0];
    const double mu = p.m[0] + p.m[i];
    const double a = 1.0 / (2.0 / std::sqrt(dx * dx + dy * dy + dz * dz) - (dvx * dvx + dvy * dvy + dvz * dvz) / mu);
    if (!(a > 0)) continue;
    const double Pi = kTwoPi * std::sqrt(a * a * a / mu);
    P.push_back(Pi);
    wsum += p.m[i] * Pi;
    msum += p.m[i];
  }
  Periods r;
  if (P.empty()) return r;
  double s = 0;
  for (double x : P) s += x;
  std::sort(P.begin(), P.end());
  r.mean = s / double(P.size());
  r.median = P[P.size() / 2];
  r.mass_weighted = wsum / msum;
  return r;
}
