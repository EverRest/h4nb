// GPU diagnostics (E, P, L, K, U) against direct CPU sums, 1 and several devices. Needs a CUDA GPU (label gpu).
#include <cuda_runtime.h>
#include <cmath>
#include <cstdio>
#include <vector>
#include "check.hpp"
#include "disk.hpp"
#include "reference.hpp"

int main() {
  const h4nb::Particles p = make_disk(1999, 0.5, 1.0, 3.0, 7);
  double pscale = 0, lscale = 0;
  for (size_t i = 0; i < p.size(); ++i) {
    pscale += p.m[i] * std::hypot(p.vx[i], p.vy[i], p.vz[i]);
    lscale += p.m[i] * std::hypot(p.x[i], p.y[i], p.z[i]) * std::hypot(p.vx[i], p.vy[i], p.vz[i]);
  }
  for (double eps2 : {0.0, 0.01}) {
    const h4nb::Diagnostics r = ref::direct_diagnostics(p, 1.0, eps2);
    for (std::vector<int> devs : {std::vector<int>{0}, std::vector<int>{0, 0, 0}}) {
      h4nb::Config c;
      c.eps2 = eps2;
      c.devices = devs;
      h4nb::Simulation s(p, c);
      const h4nb::Diagnostics g = s.diagnostics();
      std::printf("eps2=%g devices=%zu: dU/U=%.2e dK/K=%.2e\n", eps2, devs.size(),
                  std::fabs(g.U - r.U) / std::fabs(r.U), std::fabs(g.K - r.K) / r.K);
      CHECK_NEAR(g.U, r.U, 1e-12 * std::fabs(r.U));
      CHECK_NEAR(g.K, r.K, 1e-12 * r.K);
      CHECK_NEAR(g.E, r.E, 1e-12 * std::fabs(r.E));
      for (int k = 0; k < 3; ++k) {
        CHECK_NEAR(g.P[k], r.P[k], 1e-12 * pscale);
        CHECK_NEAR(g.L[k], r.L[k], 1e-12 * lscale);
      }
    }
  }
  std::puts("test_diagnostics: OK");
  return 0;
}
