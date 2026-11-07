// Internal interface of the MPI path (task T030, docs/multi-node-design.md). Only src/mpi_comm.cpp includes mpi.h.
// This header has no MPI type. Thus simulation.cu (compiled by nvcc) does not include the MPI headers.
// Only a build with H4NB_MPI=ON compiles and links these functions. simulation.cu uses them behind H4NB_HAVE_MPI.
//
// All functions use one communicator: a copy of MPI_COMM_WORLD (MPI_Comm_dup). The library makes it at the first use.
// The functions that are marked "collective" must be called by all ranks in the same order.
// An MPI error throws std::runtime_error with the call and the rank. The communicator uses MPI_ERRORS_RETURN.
// Floating-point data goes through MPI only as a copy (gather, all-to-all, minimum). This code never adds
// floating-point values in MPI (no MPI_SUM). The caller adds the received rows in rank order (constitution IV).
#pragma once
#include <cstdint>
#include <string>

namespace h4nb {
namespace comm {

bool active();      // MPI is initialized, not finalized, and the world has more than one rank.
int rank();         // Rank in the communicator. 0 when MPI is not initialized.
int size();         // Number of ranks. 1 when MPI is not initialized.
int local_rank();   // Rank among the ranks on this node (MPI_COMM_TYPE_SHARED).

// GPU of this rank (docs/multi-node-design.md section 3.3). One visible device: 0. Otherwise the device
// (local_rank + device_offset) % count. Throws std::runtime_error when local_rank >= count (no silent sharing),
// or when there is no CUDA device.
int select_device(int device_offset);

// Collective operations. n and the counts are numbers of elements.
void min_i64(int64_t* v, int n);   // In place, MPI_MIN. Exact and independent of the order.
int max_int(int v);                // MPI_MAX.
unsigned bor(unsigned v);          // MPI_BOR.
double min_double(double v);       // MPI_MIN. Exact and independent of the order.
void allgather_int(int v, int* out);                                      // out has size() entries.
void allgather_double(const double* in, int n, double* out);              // out has n * size() entries, rank order.
// In place: the block of this rank is already at buf + displs[rank()]. The other blocks arrive at their displacements.
// d4 is 4 doubles (32 bytes). buf can be device memory only with a CUDA-aware MPI library.
void allgatherv_d4(void* buf, const int* counts, const int* displs);
void allgatherv_int(int* buf, const int* counts, const int* displs);
void alltoallv_d4(const void* send, const int* scounts, const int* sdispls, void* recv, const int* rcounts,
                  const int* rdispls);

// Flushes all C output streams, prints the message with the rank to stderr, and calls MPI_Abort(code).
// Use it when one rank fails and the other ranks can wait in a collective (docs/multi-node-design.md section 5).
[[noreturn]] void fatal(const std::string& what, int code = 1);

}  // namespace comm
}  // namespace h4nb
