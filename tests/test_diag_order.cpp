// MPI-M1: the MPI diagnostics must give the same bits as one process with the same parts on devices.
// This CPU test feeds the same synthetic rows to diag_sum() in two layouts:
// - one process with G devices, as Simulation::diagnostics() builds it;
// - P ranks, gathered to rank 0 in rank order, as diagnostics_mpi() builds it (MPI_Gather, MPI_Gatherv, MPI_Bcast).
// It tests the shared function and the gather layout. It does not run MPI.
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <random>
#include <vector>
#include "check.hpp"
#include "diag_sum.hpp"

using h4nb::Diagnostics;
using h4nb::Particles;

namespace {
std::mt19937_64 rng(12345);
// Values with a wide range of magnitudes, so that a change of the sum order changes the last bits.
double val() {
  std::uniform_real_distribution<double> u(-1, 1), e(-6, 6);
  return u(rng) * std::pow(10.0, e(rng));
}

bool same_bits(const Diagnostics& a, const Diagnostics& b) { return std::memcmp(&a, &b, sizeof a) == 0; }

void run(int G, int N) {
  Particles p;
  p.resize(size_t(N));
  for (int i = 0; i < N; ++i) {
    p.m[size_t(i)] = std::fabs(val()) + 1e-3;
    p.x[size_t(i)] = val(); p.y[size_t(i)] = val(); p.z[size_t(i)] = val();
    p.vx[size_t(i)] = val(); p.vy[size_t(i)] = val(); p.vz[size_t(i)] = val();
  }
  // Part k: the same formula as Simulation::Impl (e.base, e.n, pbase, pn).
  const size_t NN = size_t(N), NG = size_t(G);  // Do not write v(size_t(N)): it parses as a function declaration.
  std::vector<int> base(NG), n(NG);
  for (int k = 0; k < G; ++k) {
    base[size_t(k)] = int(int64_t(N) * k / G);
    n[size_t(k)] = int(int64_t(N) * (k + 1) / G) - base[size_t(k)];
  }
  // The data on device (or rank) k: a phi row of N doubles and wd of its own n[k] particles.
  // Rows 0 and G-1 hold +B and -B, with B = 2^40. A positive v puts B + v above 2^40 and -B + v below it, where
  // the spacing of the doubles is two times smaller. So the bits of phi_i depend on the row order (G >= 3).
  // Random rows alone do not show an order change: the Neumaier sum over i hides 1 ulp in a term.
  const double B = std::ldexp(1.0, 40);
  std::vector<std::vector<double>> row(NG, std::vector<double>(NN)), wdk(NG);
  for (int k = 0; k < G; ++k) {
    for (auto& v : row[size_t(k)]) v = std::fabs(val()) + (k == 0 ? B : k == G - 1 ? -B : 0.0);
    wdk[size_t(k)].resize(size_t(n[size_t(k)]));
    for (auto& v : wdk[size_t(k)]) v = val();
  }

  // One process: ph row h at h * N, wd of device h at wd + base[h] (Simulation::diagnostics()).
  std::vector<double> ph(NG * NN), wd(NN);
  for (int h = 0; h < G; ++h) {
    std::copy(row[size_t(h)].begin(), row[size_t(h)].end(), ph.begin() + std::ptrdiff_t(h) * N);
    std::copy(wdk[size_t(h)].begin(), wdk[size_t(h)].end(), wd.begin() + base[size_t(h)]);
  }
  const Diagnostics one = h4nb::diag_sum(p, ph.data(), G, wd.data(), 1.0);

  // P = G ranks. MPI_Gather puts the block of rank r at r * N. MPI_Gatherv puts it at displs[r] = pbase[r].
  std::vector<double> rows(NG * NN), wall(NN);
  for (int r = 0; r < G; ++r) {
    std::memcpy(rows.data() + size_t(r) * size_t(N), row[size_t(r)].data(), size_t(N) * sizeof(double));
    std::memcpy(wall.data() + base[size_t(r)], wdk[size_t(r)].data(), size_t(n[size_t(r)]) * sizeof(double));
  }
  const Diagnostics q = h4nb::diag_sum(p, rows.data(), G, wall.data(), 1.0);
  const double out[10] = {q.K, q.U, q.E, q.P[0], q.P[1], q.P[2], q.L[0], q.L[1], q.L[2], q.W_diss};  // MPI_Bcast.
  Diagnostics mpi;
  mpi.K = out[0]; mpi.U = out[1]; mpi.E = out[2];
  for (int k = 0; k < 3; ++k) mpi.P[k] = out[3 + k], mpi.L[k] = out[6 + k];
  mpi.W_diss = out[9];

  if (!same_bits(one, mpi)) {
    std::fprintf(stderr, "G=%d N=%d: MPI layout differs: U %.17g vs %.17g, W %.17g vs %.17g\n", G, N, one.U, mpi.U,
                 one.W_diss, mpi.W_diss);
    CHECK(false);
  }
}
}  // namespace

int main() {
  for (int G : {2, 3})
    for (int N : {7, 100, 1001}) run(G, N);  // 7, 100 and 1001 are not divisible by 3; 7 and 1001 not by 2.
  std::puts("test_diag_order: all checks passed");
  return 0;
}
