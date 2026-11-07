// Q1: a Simulation constructor that throws must free its CUDA memory. Label gpu.
// The test takes almost all free device memory with its own allocation. Then the constructor runs out of memory
// after it allocated some arrays. Without the fix, those arrays stay allocated after the throw.
#include <cuda_runtime.h>
#include <cstdio>
#include <stdexcept>
#include "check.hpp"
#include "h4nb/h4nb.hpp"

static size_t free_bytes() {
  size_t f = 0, t = 0;
  CHECK(cudaMemGetInfo(&f, &t) == cudaSuccess);
  cudaGetLastError();
  return f;
}

int main() {
  CHECK(cudaFree(nullptr) == cudaSuccess);  // Create the context first, so its memory is in the baseline.
  const size_t base = free_bytes();
  const size_t keep = size_t(512) << 20;  // Free memory left for the constructor: 512 MB.
  CHECK(base > keep + (size_t(1) << 30));  // The test needs about 1 GB of device memory.

  void* hog = nullptr;
  CHECK(cudaMalloc(&hog, base - keep) == cudaSuccess);

  // About 556 bytes of device memory per particle on one GPU. 1.5e6 particles need about 830 MB > 512 MB.
  const size_t N = 1500000;
  h4nb::Particles p;
  p.resize(N);
  for (size_t i = 0; i < N; ++i) {
    p.id[i] = int64_t(i);
    p.m[i] = 1.0 / double(N);
    p.x[i] = double(i % 97), p.y[i] = double(i % 89), p.z[i] = double(i % 83);
    p.vx[i] = p.vy[i] = p.vz[i] = 0.0;
  }
  bool threw = false;
  try {
    h4nb::Config c;
    h4nb::Simulation s(p, c);
  } catch (const std::exception& e) {
    threw = true;
    std::fprintf(stderr, "expected failure: %s\n", e.what());
  }
  CHECK(threw);

  CHECK(cudaFree(hog) == cudaSuccess);
  cudaGetLastError();
  const size_t after = free_bytes();
  // Allow 32 MB for driver and allocator noise. A leak here is about 500 MB.
  const size_t tol = size_t(32) << 20;
  if (after + tol < base) {
    std::fprintf(stderr, "leak: free before %zu B, after %zu B\n", base, after);
    return 1;
  }
  std::puts("test_construct_leak: all checks passed");
  return 0;
}
