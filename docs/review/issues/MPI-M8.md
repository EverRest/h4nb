# MPI-M8. Cost of a diag point: not measured, unbalanced, extra traffic

- Severity: MEDIUM
- Location: `src/simulation.cu:786-858`, `tools/h4nb_run.cpp:383, 392-418`.
- Problems:
  1. About 9-10 collectives and 7 device syncs per diag point (stats x2, status x1-2, diagnostics 2 Allgatherv + 1 Allgather, levels, max_over_ranks).
  2. Potential pairs j > i with contiguous parts: rank r does about n·(base_r + n/2) pairs. Most-loaded / least-loaded = 2P-1 (15x at P=8); last rank about 2x the mean. Estimated at N=1M, P=8: about 0.12 s on the last rank. With the default diag = dt_max, the diag overhead is about 2-6% of the run, doubled by the imbalance. Nothing records it (MPI-M3).
  3. `state_mpi` sends positions and velocities (2·(N-n)·32 B, about 56 MB per rank at 1M) to every rank, converts d4 to Particles and back, then uploads 32 MB from pageable memory. `levels()` sends N ints to every rank for 3 numbers on rank 0. Snapshots use Allgatherv though only rank 0 writes.
- Fix:
  - Measure t_diag, t_state per rank (MPI-M3).
  - Diagnostics: Allgatherv only the positions as d4, CUDA-aware, straight into `e.tx` (K, P, L, W use own particles only). Keep it compatible with MPI-M1 (choose: bit-identity needs all velocities on rank 0, or a gather of the K, P, L terms per particle).
  - Use pinned buffers for `phi`.
  - Balance the j > i triangle: cyclic or mirrored source order, or split the triangle in equal areas.
  - `levels()`: dt_min, dt_max and the dt sum locally, gathered to rank 0 in rank order. Snapshots: `MPI_Gatherv` to rank 0.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
