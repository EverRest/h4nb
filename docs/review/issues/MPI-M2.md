# MPI-M2. Seven blocking collectives and four host syncs for each block step

- Severity: MEDIUM
- Location: `src/simulation.cu:491-577`. Collectives at lines 504, 519, 531, 532, 533, 551, 553. Host syncs at 501, 516, 529, 548. Four `std::vector<int>(P)` allocations at 518.
- Problem: with block steps NA is often 1e2 to 1e4, so a step is latency-bound. Estimated fixed overhead on GH200 at P=8: about 120-150 us per step. Break-even NA (force time = overhead) is about 30·P at N=1M. At NA=1e2, P=8: about 30% strong-scaling efficiency.
- Evidence (measured, container CPU-only microbenchmark, host buffers, Open MPI 4.1.6 shared memory, not cluster numbers): 7 collectives against 3 packed: P=2 NA=1e3: 69.6 us against 34.7 us; P=4 NA=1e2: 27.8 us against 14.1 us; P=4 NA=1e4: 302 us against 234 us. About 2x in the latency regime, 1.2-1.3x in the bandwidth regime.
- Fix (MPI still only copies values, so the bits do not change):
  1. Merge phase 1 and the count gather: select with the local minimum of `next`, then one `MPI_Allgather` of {local_min, count_at_local_min, nan_flag}. `Tn = min(local_min)`, `na[r] = local_min[r] == Tn ? count[r] : 0`. Removes one collective and one host sync.
  2. Pack tx, tv, tid in one record. One `Allgatherv` in place of three.
  3. Pack fa and fj in one record (interleaved output of `sum_partials` or a small pack kernel). One `Alltoallv` in place of two.
  4. Make `na`, `off`, `rc`, `rd` members of `Impl`.
  - Result: 3 collectives and 3 syncs. Optional: drop the unused tx.w, tv.w, fj.w (132 B to 108 B per target).
- Also fix the comment at line 489 ("five collectives") and `docs/multi-node-design.md:33, :295`.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
