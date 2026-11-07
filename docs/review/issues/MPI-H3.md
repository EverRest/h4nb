# MPI-H3. No check that MPI is CUDA-aware when mpi_host_staging=0

- Severity: HIGH
- Location: `src/simulation.cu:531-533, 551-554` (device pointers go to MPI), `src/mpi_comm.cpp` (no query).
- Problem: the default is `mpi_host_staging=0`. With an MPI library that is not CUDA-aware (or Cray MPICH without `MPICH_GPU_SUPPORT_ENABLED=1` on GH200), MPI reads a device pointer as host memory. The result is a segfault, not an MPI error. `MPI_ERRORS_RETURN` and `comm::fatal` do not catch it. The other ranks can hang until the launcher kills them.
- Fix: at construction, when `mpi_host_staging=0`, query the support: `MPIX_Query_cuda_support()` (Open MPI, `mpi-ext.h` with `MPIX_CUDA_AWARE_SUPPORT`), `MPIX_GPU_query_support` (MPICH). If the answer is no, throw `std::invalid_argument` ("set mpi_host_staging=1") through the existing constructor agreement. If no query exists, print a warning on rank 0. Record `mpi_cuda_aware: yes|no|unknown` in run_info.txt.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
