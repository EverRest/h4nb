# MPI-M6. The NaN halt exists only on the MPI path

- Severity: MEDIUM (determinism between paths)
- Location: `src/simulation.cu:502-508, 598` against `src/simulation.cu:604`.
- Problem: under MPI, `advance_to()` stops at the first block step after kNaN. One process continues to the target time with NaN values. So `devices={0,1}` and `mpirun -np 2` give different `time()`, `performance.dat` and `timesteps.dat` on this path. The contract documents the MPI behavior, but not the difference.
- Fix: put the same check in `step()`: copy `status` together with `h_min` (the sync is already there) and set `halted`. Then both paths stop at the same block step.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
