// Physics on the CPU oracle (ref::Ref, same algorithm as the GPU). No GPU needed. TZ 11.1, 11.2, 11.6.
#include <cstdio>
#include <memory>
#include "scenarios.hpp"

int main() {
  auto make = [](const h4nb::Particles& p, const h4nb::Config& c) { return std::make_unique<ref::Ref>(p, c); };
  for (double e : {0.1, 0.5}) {
    kepler_orbit(make, e, false);
    kepler_orbit(make, e, true);
    convergence(make, e);
  }
  triple(make, true);
  triple(make, false);

  // The CPU oracle is deterministic: two identical runs give identical bits.
  const TwoBody tb = two_body(0.5, 1e-3, false);
  h4nb::Config c;
  c.eta = 0.001;
  c.dt_max = 1.0 / 16;
  ref::Ref a(tb.p, c), b(tb.p, c);
  a.advance_to(2.0);
  b.advance_to(2.0);
  const h4nb::Particles sa = a.state(), sb = b.state();
  CHECK(sa.x == sb.x && sa.y == sb.y && sa.vx == sb.vx && sa.vy == sb.vy);
  std::puts("test_physics_cpu: OK");
  return 0;
}
