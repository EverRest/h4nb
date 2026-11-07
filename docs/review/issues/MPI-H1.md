# MPI-H1. Ranks do not check that they use the same settings and the same input

- Severity: HIGH
- Location: `tools/h4nb_run.cpp:186-278` (only an error code is agreed, `agree_setup` line 172), `tools/h4nb_run.cpp:187-190` (help), `tools/h4nb_run.cpp:250` (each rank reads `ic`), `tools/settings.hpp:126` (each rank reads `H4NB_<KEY>`), `src/simulation.cu:194-226, 241-246, 257`.
- Problem: each rank resolves its settings and reads the input itself. Nothing compares them. Ways they can differ: an env variable that the launcher does not pass to remote nodes (Open MPI over ssh needs `-x`), a node-local config or input file, a stale copy on a non-shared FS, MPMD launches, different glibc (default `r_close` uses `std::cbrt`).
- Effects:
  - Different `t_end`, `diag`, `snap`, `snap_times`: different numbers of collectives. Deadlock, or collectives of different phases pair up.
  - Different `dt_max` or `max_level`: `tick` differs, the MPI_MIN of Tn mixes units. Silently wrong physics.
  - Different `eta` etc.: the run completes, but breaks FR-022. `config.used` shows only rank 0.
  - Different N: `pbase`/`pn` differ. Allgatherv overflows `e.tx`/`h_tx` (size local N) or gives MPI_ERR_TRUNCATE.
  - Same N, different content: `state()` pairs the local ids of rank 0 with the positions of other ranks. No error.
  - `help=1` on one rank only: that rank returns before agreement point 1; the other ranks hang.
- Evidence (ran, no GPU): MPMD `mpirun -n 1 h4nb_run ... : -n 1 -x H4NB_DT_MAX=0.0078125 -x H4NB_SNAP=0.5 h4nb_run ...` and MPMD with N=1000 against N=500: both passed agreement point 1 without an error and reached the constructor. `timeout 20 mpirun -n 1 h4nb_run help=1 : -n 1 h4nb_run ...` hung (rc 124).
- Fix:
  1. Tool, agreement point 1: hash the resolved key=value list (canonical text, for example FNV-1a 64) and compare MIN and MAX over ranks (`max_over_ranks(h)`, `max_over_ranks(-h)`, or a new int64 helper). Mismatch: settings error, exit 2, print the keys of rank 0 and of the first different rank. Move the `help()` return behind the agreement.
  2. Library, `construct_mpi`: before `setup`, compute one int64 fingerprint of N, the bits of all Config fields except `devices` and `device_offset`, and a hash of the bytes of id, m, x, y, z, vx, vy, vz. Compare with `comm::min_i64` on {v, -v}. Mismatch: `std::invalid_argument` on all ranks. Cost: O(N) one time.
  3. Optional: print the fingerprint in each `rank_<r>` line of run_info.txt.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
