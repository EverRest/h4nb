# MPI-M1. Diagnostics are not bit-identical to one process; the A9 test must not compare energy.dat

- Severity: MEDIUM (Pavlo's criterion "the same bits")
- Location: `src/simulation.cu:807-858` (`diagnostics_mpi`) against `src/simulation.cu:715-772` (`diagnostics`).
- Problem: one process adds `phi_i = sum_h ph[h][i]` for each particle, then one Neumaier sum over i. MPI makes one Neumaier sum for each rank and then adds the 9 partials in rank order. The sum trees differ. So `energy.dat`, `momentum.dat` and `energy_periods.dat` of `mpirun -np 2` and `devices={0,1}` differ in the last bits. Design section 2.3 accepts this (1e-12). The force path and the snapshots can be identical (confirmed by a CPU emulation, see the main report).
- Fix (cost only at diag points):
  - K, P, L: every rank has the full state from `state_mpi()`. Compute them over all i in index order, as `diagnostics()` does.
  - U: `MPI_Gather` the `phi` rows (N doubles from each rank) to rank 0. Rank 0 adds the rows in rank order for each i, then runs the one-process loop. `MPI_Bcast` the results (copy only). Cost: 8·N·P bytes to rank 0.
  - W_diss: `MPI_Gatherv` of `wd`.
  - Trade-off: MPI-M8 proposes to gather only positions. Then K, P, L need the velocities again. Choose one of the two.
- Until then: in the A9 test, compare only the snapshots and `timesteps.dat` with `cmp`. Compare energy and momentum with the 1e-12 tolerance.


Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
