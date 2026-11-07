// Internal checks of the particle data (io.cpp). Not part of the public API.
#pragma once
#include <string>
#include "h4nb/h4nb.hpp"

namespace h4nb {
// Checks m > 0, finite values and unique IDs. O(N). Throws std::runtime_error at the first error.
// path names the source in the message.
void validate_particles(const Particles& p, const std::string& path);
}  // namespace h4nb
