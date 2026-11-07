// Physics on the GPU library (h4nb::Simulation): TZ 11.1, 11.2, 11.6. Needs a CUDA GPU (label gpu).
#include <cstdio>
#include <memory>
#include "scenarios.hpp"

int main() {
  auto make = [](const h4nb::Particles& p, const h4nb::Config& c) { return std::make_unique<h4nb::Simulation>(p, c); };
  for (double e : {0.1, 0.5}) {
    kepler_orbit(make, e, false);
    kepler_orbit(make, e, true);
    convergence(make, e);
  }
  triple(make, true);
  triple(make, false);

  auto make2 = [](const h4nb::Particles& p, h4nb::Config c) {  // the same physics on 2 virtual devices
    c.devices = {0, 0};
    return std::make_unique<h4nb::Simulation>(p, c);
  };
  kepler_orbit(make2, 0.5, false);
  triple(make2, false);

  // GPU energy diagnostics agree with the direct CPU sum on a moving system.
  h4nb::Simulation s(hierarchical_triple(), h4nb::Config{});
  s.advance_to(1.0);
  const h4nb::Diagnostics g = s.diagnostics(), r = ref::direct_diagnostics(s.state(), 1.0, 0.0);
  CHECK_NEAR(g.E, r.E, 1e-13 * std::fabs(r.E));
  CHECK_NEAR(g.time, 1.0, 0.0);
  std::puts("test_physics_gpu: OK");
  return 0;
}
