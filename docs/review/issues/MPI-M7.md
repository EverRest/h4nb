# MPI-M7. Exchange on GH200: staging and overlap

- Severity: MEDIUM (performance; measure first, see MPI-M3)
- Location: `src/simulation.cu:524-559` (staging copies), `src/simulation.cu:531-543` (force after the gather).
- Problems:
  1. Small CUDA-aware messages on device pointers (Cray MPICH GTL, UCX) are often slower than host buffers below about 64 KB. Host staging adds 5-6 `cudaMemcpyAsync` per step (about 15-30 us). The staged copies also move the whole NA, including the own block (1/P waste).
  2. No overlap: the force kernel starts only after all three Allgathervs return. The force on the own targets [o, o+m) does not need the other targets, and the split is fixed once NA is known, so it can run during the gather with identical bits (the kernel needs a target-offset argument).
- Fix:
  1. On the cluster, measure `mpi_host_staging=0` against `1` for each NA bin. On GH200 (NVLink-C2C), let `gather_kernel` and `sum_partials` write straight into the pinned `h_tx`/`h_fa` buffers and let the force kernel read targets from `h_tx`. No copies. Pick the default from the measurement.
  2. Launch the own-target force before the blocking Allgatherv (it reads only the send region; legal with MPI_IN_PLACE). Gain about min(T_gather, T_force/P). Later: compute the remote slices first and use `MPI_Ialltoallv`.
- Estimated: fixes 1+2 with MPI-M2 roughly halve the break-even NA.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
