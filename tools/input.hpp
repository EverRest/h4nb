// input.hpp: reads the initial conditions for the tools.
#pragma once
#include <memory>
#include <stdexcept>
#include <string>
#include "h4nb/h4nb.hpp"
#include "settings.hpp"

// Reads the initial conditions: a .snap file is binary, other files are text.
// A read or validation error is an input error. It becomes a SettingsError, so the tool returns exit code 2.
inline h4nb::Particles load_input(const std::string& path) {
  const bool binary = path.size() > 5 && path.compare(path.size() - 5, 5, ".snap") == 0;
  try {
    return binary ? h4nb::read_snapshot(path) : h4nb::load_text(path);
  } catch (const std::runtime_error& e) {
    throw SettingsError(std::string("ic: ") + e.what());
  }
}

// Builds a Simulation. The constructor throws std::invalid_argument for a bad Config or bad input (device ids too).
// That is an input error, so it becomes a SettingsError and the tool returns 2. Other errors (no CUDA device) stay 1.
inline std::unique_ptr<h4nb::Simulation> make_simulation(const h4nb::Particles& p, const h4nb::Config& c) {
  try {
    return std::make_unique<h4nb::Simulation>(p, c);
  } catch (const std::invalid_argument& e) {
    throw SettingsError(e.what());
  }
}
