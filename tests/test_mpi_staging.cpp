// Unit tests for the CUDA-aware check of the MPI path (MPI-H3). Pure function, no MPI and no GPU needed.
#include <string>
#include "check.hpp"
#include "mpi_comm.hpp"

using h4nb::comm::staging_error;

static void test_not_cuda_aware_without_staging_fails() {
  const std::string msg = staging_error(0, false);
  CHECK(!msg.empty());
  CHECK(msg.find("mpi_host_staging") != std::string::npos);  // The message names the fix.
}

static void test_cuda_aware_passes() {
  CHECK(staging_error(1, false).empty());
}

static void test_staging_always_passes() {
  CHECK(staging_error(0, true).empty());
  CHECK(staging_error(1, true).empty());
  CHECK(staging_error(-1, true).empty());
}

static void test_unknown_only_warns() {
  // Unknown returns "" here. The caller prints the warning once on rank 0 and continues.
  CHECK(staging_error(-1, false).empty());
}

int main() {
  test_not_cuda_aware_without_staging_fails();
  test_cuda_aware_passes();
  test_staging_always_passes();
  test_unknown_only_warns();
  std::puts("test_mpi_staging: all checks passed");
  return 0;
}
