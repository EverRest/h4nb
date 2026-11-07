// The MPI path of h4nb (task T030, docs/multi-node-design.md sections 1.5, 3.3 and 5).
// CMake compiles this file only with H4NB_MPI=ON. It is the only file that includes mpi.h.
// It holds the internal functions of src/mpi_comm.hpp and the public rank functions of include/h4nb/h4nb.hpp.
// The application initializes MPI (directly or with h4nb::RankScope). The library does not call MPI_Init by itself.
#include <mpi.h>
#include <cuda_runtime.h>
#include <unistd.h>
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
#include <string>
#include <vector>
#include "h4nb/h4nb.hpp"
#include "mpi_comm.hpp"

namespace h4nb {
namespace comm {
namespace {

bool initialized() {
  int init = 0, fin = 0;
  MPI_Initialized(&init);
  MPI_Finalized(&fin);
  return init && !fin;
}

// The library communicator and its data. Made at the first use after MPI_Init. RankScope frees it.
struct State {
  bool made = false;
  MPI_Comm comm = MPI_COMM_NULL;
  int rank = 0, size = 1, local_rank = 0;
  MPI_Datatype d4 = MPI_DATATYPE_NULL;  // 4 contiguous doubles: one d4 of kernels.cuh.
};
State g_state;

[[noreturn]] void fail(int rc, const char* what) {
  char text[MPI_MAX_ERROR_STRING] = "";
  int len = 0;
  if (MPI_Error_string(rc, text, &len) != MPI_SUCCESS) std::snprintf(text, sizeof text, "error code %d", rc);
  throw std::runtime_error(std::string(what) + ": " + text + " (rank " + std::to_string(g_state.rank) + ")");
}
void ck(int rc, const char* what) {
  if (rc != MPI_SUCCESS) fail(rc, what);
}
#define H4_MPI(call) ::h4nb::comm::ck((call), #call)

State& state() {
  if (g_state.made || !initialized()) return g_state;
  State& s = g_state;
  // Errors in the world communicator before the copy exists stop the job (MPI default). After the copy, the
  // library gets the error codes and throws.
  MPI_Comm_dup(MPI_COMM_WORLD, &s.comm);
  H4_MPI(MPI_Comm_set_errhandler(s.comm, MPI_ERRORS_RETURN));
  H4_MPI(MPI_Comm_rank(s.comm, &s.rank));
  H4_MPI(MPI_Comm_size(s.comm, &s.size));
  MPI_Comm node = MPI_COMM_NULL;
  H4_MPI(MPI_Comm_split_type(s.comm, MPI_COMM_TYPE_SHARED, s.rank, MPI_INFO_NULL, &node));
  H4_MPI(MPI_Comm_rank(node, &s.local_rank));
  H4_MPI(MPI_Comm_free(&node));
  H4_MPI(MPI_Type_contiguous(4, MPI_DOUBLE, &s.d4));
  H4_MPI(MPI_Type_commit(&s.d4));
  s.made = true;
  return s;
}

MPI_Comm cm() { return state().comm; }

}  // namespace

bool active() { return initialized() && state().size > 1; }
int rank() { return state().rank; }
int size() { return state().size; }
int local_rank() { return state().local_rank; }

int select_device(int device_offset) {
  int count = 0;
  const cudaError_t e = cudaGetDeviceCount(&count);
  if (e != cudaSuccess || count < 1) {
    cudaGetLastError();
    throw std::runtime_error(std::string("no CUDA device for rank ") + std::to_string(rank()) + ": " +
                             (e != cudaSuccess ? cudaGetErrorString(e) : "device count is 0"));
  }
  if (count == 1) return 0;  // The launcher gives one GPU to each task (for example srun --gpu-bind=single:1).
  const int lr = local_rank();
  if (lr >= count)
    throw std::runtime_error("rank " + std::to_string(rank()) + ": local rank " + std::to_string(lr) +
                             " >= device count " + std::to_string(count) +
                             ". Start at most one rank for each GPU on a node. The library does not share a device.");
  return (lr + device_offset) % count;
}

void min_i64(int64_t* v, int n) { H4_MPI(MPI_Allreduce(MPI_IN_PLACE, v, n, MPI_INT64_T, MPI_MIN, cm())); }
int max_int(int v) {
  H4_MPI(MPI_Allreduce(MPI_IN_PLACE, &v, 1, MPI_INT, MPI_MAX, cm()));
  return v;
}
unsigned bor(unsigned v) {
  H4_MPI(MPI_Allreduce(MPI_IN_PLACE, &v, 1, MPI_UNSIGNED, MPI_BOR, cm()));
  return v;
}
double min_double(double v) {
  H4_MPI(MPI_Allreduce(MPI_IN_PLACE, &v, 1, MPI_DOUBLE, MPI_MIN, cm()));
  return v;
}
void allgather_int(int v, int* out) { H4_MPI(MPI_Allgather(&v, 1, MPI_INT, out, 1, MPI_INT, cm())); }
void allgather_double(const double* in, int n, double* out) {
  H4_MPI(MPI_Allgather(in, n, MPI_DOUBLE, out, n, MPI_DOUBLE, cm()));
}
void allgatherv_d4(void* buf, const int* counts, const int* displs) {
  H4_MPI(MPI_Allgatherv(MPI_IN_PLACE, 0, MPI_DATATYPE_NULL, buf, counts, displs, state().d4, cm()));
}
void allgatherv_int(int* buf, const int* counts, const int* displs) {
  H4_MPI(MPI_Allgatherv(MPI_IN_PLACE, 0, MPI_DATATYPE_NULL, buf, counts, displs, MPI_INT, cm()));
}
void alltoallv_d4(const void* send, const int* scounts, const int* sdispls, void* recv, const int* rcounts,
                  const int* rdispls) {
  const MPI_Datatype t = state().d4;
  H4_MPI(MPI_Alltoallv(send, scounts, sdispls, t, recv, rcounts, rdispls, t, cm()));
}

void fatal(const std::string& what, int code) {
  std::fflush(nullptr);  // Keep the records that the tools wrote so far (energy.dat and others).
  const int r = initialized() ? state().rank : 0, n = initialized() ? state().size : 1;
  std::fprintf(stderr, "h4nb: fatal error on rank %d of %d: %s. All ranks stop (MPI_Abort).\n", r, n, what.c_str());
  std::fflush(stderr);
  if (initialized()) MPI_Abort(MPI_COMM_WORLD, code);
  std::exit(code);
}

}  // namespace comm

// Public rank functions (include/h4nb/h4nb.hpp). src/single_rank.cpp has the versions for a build without MPI.
RankScope::RankScope(int& argc, char**& argv) {
  int init = 0;
  MPI_Initialized(&init);
  if (!init) {
    if (MPI_Init(&argc, &argv) != MPI_SUCCESS) throw std::runtime_error("MPI_Init failed");
    owner_ = true;
  }
}

RankScope::~RankScope() {
  if (!owner_ || !comm::initialized()) return;
  comm::State& s = comm::g_state;
  if (s.made) {
    MPI_Type_free(&s.d4);
    MPI_Comm_free(&s.comm);
    s = comm::State{};
  }
  MPI_Finalize();
}

int rank() { return comm::rank(); }
int ranks() { return comm::size(); }
int local_rank() { return comm::local_rank(); }
int max_over_ranks(int value) { return comm::active() ? comm::max_int(value) : value; }

std::string rank_table(int device_offset) {
  if (!comm::active()) return "";
  char host[256] = "unknown";
  if (gethostname(host, sizeof host) != 0) std::snprintf(host, sizeof host, "unknown");
  host[sizeof host - 1] = '\0';
  std::string line = "rank_" + std::to_string(comm::rank()) + ": host=" + host +
                     " local_rank=" + std::to_string(comm::local_rank());
  try {
    const int id = comm::select_device(device_offset);
    cudaDeviceProp prop{};
    const cudaError_t e = cudaGetDeviceProperties(&prop, id);
    line += " device=" + std::to_string(id);
    if (e == cudaSuccess)
      line += std::string(" name=") + prop.name + " cc=" + std::to_string(prop.major) + "." + std::to_string(prop.minor);
    else
      line += std::string(" error=") + cudaGetErrorString(e);
  } catch (const std::exception& ex) {
    line += std::string(" error=") + ex.what();
  }
  cudaGetLastError();  // Clear the error. The Simulation constructor must not see it.
  line += "\n";
  // Gather the lines to rank 0 in rank order: first the lengths, then the text.
  const int n = comm::size(), len = int(line.size());
  MPI_Comm c = comm::cm();
  std::vector<int> lens(n), displs(n);  // Use (n). Do not use (size_t(n)): it parses as a function declaration.
  H4_MPI(MPI_Gather(&len, 1, MPI_INT, lens.data(), 1, MPI_INT, 0, c));
  int total = 0;
  for (int k = 0; k < n; ++k) displs[size_t(k)] = total, total += lens[size_t(k)];
  std::string all(comm::rank() == 0 ? size_t(total) : 0, '\0');
  H4_MPI(MPI_Gatherv(line.data(), len, MPI_CHAR, &all[0], lens.data(), displs.data(), MPI_CHAR, 0, c));
  if (comm::rank() != 0) return "";
  char lib[MPI_MAX_LIBRARY_VERSION_STRING] = "";
  int liblen = 0;
  MPI_Get_library_version(lib, &liblen);
  lib[sizeof lib - 1] = '\0';
  std::string first(lib);  // Do not use liblen. Some libraries count the terminating zero in it.
  first = first.substr(0, first.find_first_of("\r\n"));
  return "mpi_library: " + first + "\n" + all;
}

void abort_ranks(int code, const std::string& what) { comm::fatal(what, code); }

}  // namespace h4nb
