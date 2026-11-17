# MPI-M3. No per-phase metrics, no rank imbalance, no NA histogram, no NVTX

- Severity: MEDIUM (Pavlo's criterion: metrics and statistics; needed for the GH200 scaling runs)
- Location: `include/h4nb/h4nb.hpp` (`Stats`), `tools/h4nb_run.cpp:391-398` (`performance.dat`), no NVTX in src or tools.
- Problem: `Stats` has only `block_steps`, `active_total`, `min_r2`. `performance.dat` has the wall time of rank 0 for `advance_to` only. You cannot see compute against communication, which rank is slow, bytes, or the many small block steps that make the exchange latency-bound. Not timed at all: `diagnostics()`, `state()`, `levels()`, snapshot writes, total wall. `t_init` includes allocation and agreement, but is printed as "pairs/s of one force pass".
- Fix (design; deterministic-safe):
  - Rules: timing never changes control flow. No new host sync, no new collective inside the MPI branch of `step()`. Aggregate only at diag points. Gate: `profile=0` and `profile=1` give byte-identical snapshots and timesteps.dat.
  - New `struct RankProfile` (local, not collective), next to `Stats`: steps, na_total, own_active_total/max, `na_hist[32]` (log2 bins), bytes_sent/recv/h2d/d2h (from na[] on the host), t_tn, t_select, t_gather, t_force, t_xchg, t_correct, t_diag, t_state, t_setup, t_init_force (steady_clock at the existing sync points); optional gpu_force_ms (cudaEvent, profile=2). `Simulation::profile()`. The one-process `step()` fills the same fields (peer copies as t_gather/t_xchg).
  - Phase limits in the MPI branch of `step()`: t_tn, t_select, t_gather (+ staging), t_force, t_xchg, t_correct (counted at the next sync). Line numbers moved when `step_mpi()` was merged into `step()` (2026-11-08).
  - Bytes per step and rank: Allreduce 16 B; counts 4P B; Allgatherv send 68m·(P-1), recv 68(NA-m); Alltoallv send 64(NA-m), recv 64(P-1)m.
  - Tool, rank 0, one gather (about 30 doubles per rank) per diag point:
    - `performance.dat` schema 2 (old columns first): + wall_max wall_min compute_imb (max/mean of select+force+correct) comm_frac t_diag_max bytes_max.
    - `perf_ranks.dat`: time rank host_idx m_total m_max t_tn t_select t_gather t_force t_xchg t_correct t_diag t_state bytes_sent bytes_recv gpu_force_ms.
    - `na_hist.dat`: time bin_lo count (deterministic, comparable across rank counts).
  - NVTX: option `H4NB_NVTX` (default ON, nvtx3 is header-only in the CUDA toolkit). Domain `h4nb`, ranges tn, select, gather, force, xchg, correct, diag, state, setup, with the rank in the payload. Quickstart A9: `nsys profile -o rep_%q{OMPI_COMM_WORLD_RANK} --trace=cuda,nvtx,mpi`.
  - Cost: about 12 clock reads per block step (< 1 us), against 3 syncs of about 10 us.
- See also MPI-M4 (run record) and MPI-M8 (diag-point cost).

**Partly closed 2026-11-08:** `RankProfile` + `Simulation::profile()`; host phase timers and byte counts in `step()` (no new sync/collective); `performance.dat` schema 2 columns on rank 0. Still open: multi-rank gather for `wall_max`/`compute_imb`, `perf_ranks.dat`, `na_hist.dat`, NVTX, `profile=2` cudaEvents, tool-side `t_diag`/`t_state`.

Source: docs/review/mpi-review.md (main @ 1e26eaa). Line numbers refer to 1e26eaa. Run `git pull` first.
