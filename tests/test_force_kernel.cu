// force_kernel output for small target counts (NA < TILE). The output must stay bit-identical (constitution IV).
// Each case hashes the raw bytes of pa and pj with FNV-1a 64. The hashes are golden values from the unpatched kernel.
// Needs a CUDA GPU (label gpu).
// Capture: run "test_force_kernel --capture" on the unpatched code, then paste the printed values into kGolden.
#include <cuda_runtime.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include "check.hpp"
#include "kernels.cuh"

using namespace h4nb;

namespace {

constexpr int kTile = 128;
constexpr int kNs = 300;      // Sources. Two j-chunks, so the output has two rows.
constexpr int kChunk = 256;   // A multiple of kTile.
constexpr double kEps2 = 1e-8;

const int kNa[] = {1, 2, 4, 31, 32, 33, 127, 128};
const uint64_t kSeeds[] = {1, 2};

// Golden hashes. Index: [case of kNa][seed of kSeeds]. Zero means "not captured yet". The test fails on zero.
const uint64_t kGolden[8][2] = {
    {0, 0}, {0, 0}, {0, 0}, {0, 0}, {0, 0}, {0, 0}, {0, 0}, {0, 0},
};

void ck(cudaError_t e, const char* what) {
  if (e != cudaSuccess) {
    std::fprintf(stderr, "%s: %s\n", what, cudaGetErrorString(e));
    std::exit(1);
  }
}

uint64_t fnv1a(uint64_t h, const void* data, size_t bytes) {
  const unsigned char* p = static_cast<const unsigned char*>(data);
  for (size_t k = 0; k < bytes; ++k) {
    h ^= p[k];
    h *= 1099511628211ULL;
  }
  return h;
}

// splitmix64. A fixed generator, so the input does not depend on the C++ library.
double next_unit(uint64_t& s) {
  s += 0x9E3779B97F4A7C15ULL;
  uint64_t z = s;
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  z ^= z >> 31;
  return double(z >> 11) * (1.0 / 9007199254740992.0);  // [0, 1)
}

// Returns the FNV-1a hash of pa and pj for NA targets. Targets are sources 0..NA-1, so self pairs occur.
uint64_t run_case(int na, uint64_t seed) {
  std::vector<d4> sx(kNs), sv(kNs);
  std::vector<int> tid(na);
  uint64_t s = seed;
  for (int j = 0; j < kNs; ++j) {
    sx[j] = d4{2 * next_unit(s) - 1, 2 * next_unit(s) - 1, 2 * next_unit(s) - 1, 0.5 + next_unit(s)};
    sv[j] = d4{next_unit(s) - 0.5, next_unit(s) - 0.5, next_unit(s) - 0.5, 0.0};
  }
  for (int i = 0; i < na; ++i) tid[i] = i;

  const int nj = (kNs + kChunk - 1) / kChunk;
  const size_t nout = size_t(na) * nj;
  d4 *dsx = nullptr, *dsv = nullptr, *dpa = nullptr, *dpj = nullptr;
  int* dtid = nullptr;
  ck(cudaMalloc(&dsx, sizeof(d4) * kNs), "malloc sx");
  ck(cudaMalloc(&dsv, sizeof(d4) * kNs), "malloc sv");
  ck(cudaMalloc(&dtid, sizeof(int) * na), "malloc tid");
  ck(cudaMalloc(&dpa, sizeof(d4) * nout), "malloc pa");
  ck(cudaMalloc(&dpj, sizeof(d4) * nout), "malloc pj");
  ck(cudaMemcpy(dsx, sx.data(), sizeof(d4) * kNs, cudaMemcpyHostToDevice), "copy sx");
  ck(cudaMemcpy(dsv, sv.data(), sizeof(d4) * kNs, cudaMemcpyHostToDevice), "copy sv");
  ck(cudaMemcpy(dtid, tid.data(), sizeof(int) * na, cudaMemcpyHostToDevice), "copy tid");
  ck(cudaMemset(dpa, 0, sizeof(d4) * nout), "memset pa");
  ck(cudaMemset(dpj, 0, sizeof(d4) * nout), "memset pj");

  // Targets are the first NA sources. sbase = 0, so source j is target j when j < NA.
  force_kernel<kTile><<<dim3(1, nj), kTile>>>(na, dsx, dsv, dtid, kNs, dsx, dsv, 0, kChunk, kEps2, dpa, dpj);
  ck(cudaGetLastError(), "force_kernel launch");
  ck(cudaDeviceSynchronize(), "force_kernel run");

  std::vector<d4> pa(nout), pj(nout);
  ck(cudaMemcpy(pa.data(), dpa, sizeof(d4) * nout, cudaMemcpyDeviceToHost), "copy pa");
  ck(cudaMemcpy(pj.data(), dpj, sizeof(d4) * nout, cudaMemcpyDeviceToHost), "copy pj");
  cudaFree(dsx);
  cudaFree(dsv);
  cudaFree(dtid);
  cudaFree(dpa);
  cudaFree(dpj);

  uint64_t h = 14695981039346656037ULL;  // FNV offset basis
  h = fnv1a(h, pa.data(), sizeof(d4) * nout);
  h = fnv1a(h, pj.data(), sizeof(d4) * nout);
  return h;
}

}  // namespace

int main(int argc, char** argv) {
  const bool capture = argc > 1 && std::strcmp(argv[1], "--capture") == 0;
  int ncase = 0;
  for (int c = 0; c < 8; ++c) {
    for (int k = 0; k < 2; ++k) {
      const uint64_t h = run_case(kNa[c], kSeeds[k]);
      if (capture) {
        std::printf("NA %d seed %llu hash 0x%016llxULL\n", kNa[c], (unsigned long long)kSeeds[k],
                    (unsigned long long)h);
        continue;
      }
      if (kGolden[c][k] == 0) {
        std::fprintf(stderr, "NA %d seed %llu: golden hash not captured\n", kNa[c], (unsigned long long)kSeeds[k]);
        std::exit(1);
      }
      if (h != kGolden[c][k]) {
        std::fprintf(stderr, "NA %d seed %llu: hash 0x%016llx differs from golden 0x%016llx\n", kNa[c],
                     (unsigned long long)kSeeds[k], (unsigned long long)h, (unsigned long long)kGolden[c][k]);
        std::exit(1);
      }
      ++ncase;
    }
  }
  if (!capture) std::printf("test_force_kernel: %d cases bit-identical\n", ncase);
  return 0;
}
