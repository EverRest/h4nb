#pragma once
#include <cmath>

// Relative Kepler orbit at time t, semi-major axis a. Pericentre on +x at t = 0, motion towards +y.
inline void kepler_rel(double mu, double a, double e, double t, double r[3], double v[3]) {
  const double n = std::sqrt(mu / (a * a * a));
  const double M = n * t;
  double E = M;
  for (int it = 0; it < 50; ++it) E -= (E - e * std::sin(E) - M) / (1.0 - e * std::cos(E));
  const double c = std::cos(E), s = std::sin(E), b = a * std::sqrt(1.0 - e * e), Ed = n / (1.0 - e * c);
  r[0] = a * (c - e); r[1] = b * s; r[2] = 0.0;
  v[0] = -a * s * Ed; v[1] = b * c * Ed; v[2] = 0.0;
}
