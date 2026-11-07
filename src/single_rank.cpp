// The public rank functions of include/h4nb/h4nb.hpp for a build without MPI (H4NB_MPI=OFF).
// There is always one rank. src/mpi_comm.cpp has the MPI versions.
#include <cstdio>
#include <cstdlib>
#include <string>
#include "h4nb/h4nb.hpp"

namespace h4nb {

RankScope::RankScope(int&, char**&) {}
RankScope::~RankScope() = default;
int rank() { return 0; }
int ranks() { return 1; }
int local_rank() { return 0; }
int max_over_ranks(int value) { return value; }
std::string rank_table(int) { return ""; }

void abort_ranks(int code, const std::string& what) {
  std::fflush(nullptr);
  std::fprintf(stderr, "%s (rank 0 of 1)\n", what.c_str());
  std::exit(code);
}

}  // namespace h4nb
