#pragma once
// Relative energy error of the tools (contracts/run-config.md, key energy_norm).
// norm "e0" (default): |E - E0 - W| / |E0|.
// norm "ku": |E - E0 - W| / (|K0| + |U0|).
// W is the work of the dissipative force. It is 0 without dissipation.
#include <cmath>
#include <string>

inline double rel_energy_error(double E, double E0, double W, double K0, double U0, const std::string& norm) {
  const double denom = norm == "ku" ? std::fabs(K0) + std::fabs(U0) : std::fabs(E0);
  return std::fabs((E - E0 - W) / denom);
}

// The error text when norm "e0" cannot divide by E0 (E0 is 0 or not finite). Empty when the norm is usable.
inline std::string energy_norm_error(const std::string& norm, double E0) {
  if (norm != "e0" || (std::isfinite(E0) && E0 != 0)) return "";
  if (!std::isfinite(E0)) return "E0 is not finite. Check the initial state.";
  return "E0 is 0: the relative energy error is not defined. Set energy_norm=ku.";
}
