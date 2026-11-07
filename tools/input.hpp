// input.hpp: reads the initial conditions for the tools.
#pragma once
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
