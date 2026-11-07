// GPU library == CPU oracle, block and fixed steps, 1 device and several (emulated or real). TZ 11.5, req. 13.
// Needs a CUDA GPU (label gpu).
#include <cuda_runtime.h>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <vector>
#include "check.hpp"
#include "disk.hpp"
#include "reference.hpp"

static double max_diff(const h4nb::Particles& a, const h4nb::Particles& b) {
  double d = 0;
  for (size_t i = 0; i < a.size(); ++i) {
    d = std::max({d, std::fabs(a.x[i] - b.x[i]), std::fabs(a.y[i] - b.y[i]), std::fabs(a.z[i] - b.z[i]),
                  std::fabs(a.vx[i] - b.vx[i]), std::fabs(a.vy[i] - b.vy[i]), std::fabs(a.vz[i] - b.vz[i])});
  }
  return d;
}

static bool bitwise_equal(const h4nb::Particles& a, const h4nb::Particles& b) {
  return a.x == b.x && a.y == b.y && a.z == b.z && a.vx == b.vx && a.vy == b.vy && a.vz == b.vz && a.m == b.m;
}

int main() {
  // N = 777: not a multiple of BI, several tiles, j-split nj > 1. dt_max = 0.5 gives levels 2..5.
  const h4nb::Particles p = make_disk(776, 0.1, 1.0, 2.0, 42);
  int ndev = 0;
  CHECK(cudaGetDeviceCount(&ndev) == cudaSuccess && ndev >= 1);
  std::vector<std::vector<int>> sets = {{0}, {0, 0, 0}};  // {0,0,0}: three virtual GPUs on one card
  if (ndev >= 2) sets.push_back({0, 1});

  for (h4nb::StepMode mode : {h4nb::StepMode::Block, h4nb::StepMode::Fixed}) {
    h4nb::Config c;
    c.dt_max = 0.5;
    c.eta = 0.01;
    c.max_level = 30;
    c.eps2 = 1e-4;
    c.mode = mode;
    c.fixed_level = 5;
    ref::Ref r(p, c);
    r.advance_to(2.0);
    for (const auto& devs : sets) {
      c.devices = devs;
      h4nb::Simulation s(p, c);
      s.advance_to(2.0);
      const double d = max_diff(s.state(), r.state());
      std::printf("mode=%d devices=%zu: max|gpu-ref|=%.2e block_steps=%lld\n", int(mode), devs.size(), d,
                  (long long)s.stats().block_steps);
      CHECK(d <= 1e-10);
      CHECK(s.levels() == r.levels());
      CHECK(s.status() == 0);
      CHECK_NEAR(s.time(), 2.0, 0.0);
    }
  }

  // Determinism (constitution IV): the same input and devices give the same bits, twice.
  {
    h4nb::Config c;
    c.dt_max = 0.5;
    c.eta = 0.01;
    c.max_level = 30;
    c.eps2 = 1e-4;
    c.devices = {0, 0, 0};
    h4nb::Simulation a(p, c), b(p, c);
    a.advance_to(2.0);
    b.advance_to(2.0);
    CHECK(bitwise_equal(a.state(), b.state()));
    CHECK(a.stats().block_steps == b.stats().block_steps);
  }

  // Bad times are rejected; close pairs are flagged.
  h4nb::Config c;
  h4nb::Simulation s(p, c);
  bool threw = false;
  try {
    s.advance_to(0.3 * c.dt_max);
  } catch (const std::invalid_argument&) {
    threw = true;
  }
  CHECK(threw);
  c.r2_close = 4.0;
  h4nb::Simulation close(p, c);
  CHECK(close.status() & h4nb::kClosePair);
  std::puts("test_gpu_vs_ref: OK");
  return 0;
}
