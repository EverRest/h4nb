# MPI code review (phase 6, tasks T029 to T036)

Date: 2026-11-07. Commit: `1e26eaa` on `main` (github.com/EverRest/h4nb). All line numbers refer to this commit.
The local clone on the Mac is at `dd3e89f`. Run `git pull` before you use the line numbers.
The whole-library review (without MPI) is in `docs/review/library-review.md`. Its issue files are `docs/review/issues/<A|D|O|P|Q><n>.md`.
The MPI issue files are `docs/review/issues/MPI-<H|M><n>.md`. One file for each HIGH and MEDIUM finding. Start one local session on one file.

## Method

- Code-review skill (high) on commit 1e26eaa, plus a full read of the MPI path.
- Four parallel reviews of the whole MPI path: (1) accuracy and determinism, (2) data and error path, (3) exchange performance, (4) observability, API, tests and CI.
- Criteria aligned with the library review: accuracy and determinism; data correctness (buffers, counts, staging, exit codes); performance (collectives, syncs, bytes, memory, diag cost); observability (per-phase metrics, histograms, NVTX, run_id, hashes, schema, summary); quality (RAII, current device, async errors, state after a failed step, commit stamp, CI, tests, doc drift). MPI-only: deadlock (divergent collective sequence), one-rank exceptions, exit-code agreement, rank-0 output, device selection, CUDA-aware MPI, host staging.

## What ran and what did not

- Built in a container without a GPU: nvcc 12.0, Open MPI 4.1.6, `-DH4NB_MPI=ON`, sm_80. No warnings. `ctest -L cpu`: 3/3 pass.
- Ran `h4nb_run` with `mpirun -np 1..4`, and MPMD launches with different settings and inputs on each rank. All runs stop in the `Simulation` constructor ("no CUDA device").
- CPU emulation of the force path (`src/mpi_comm.cpp` linked, host copies of `split`, the force row and chunk order and `sum_partials`): the single-process peer path of `step()` with G parts against the MPI collective path of `step()` on P ranks, P = 2, 3, 4, 8, N = 37, 1000, 2051, 3 seeds, also m = 0 on rank 0. All 36 cases give identical bits of the forces, the same Tn and the same NA.
- CPU microbenchmark of the collectives (host buffers, shared memory; not cluster numbers): 7 collectives against 3 packed.
- Not run: the GPU kernels, CUDA-aware exchange, host staging on a GPU, the NaN halt, MPI_Abort after a CUDA error.

## Summary

The force path of the MPI branch of `step()` is correct. It gives the same bits as one process with `devices={0,1}` (emulated on the CPU; the GPU check A9 is still open). Counts, displacements, the in-place Allgatherv, the Alltoallv rows, the rank-order owner sum and the stream syncs are correct. No data race. No int overflow up to N of about 67M. **Closed 2026-11-08:** `step_mpi()` is removed; both exchange paths live in one `step()` (T031).

The main problems:

1. Ranks never check that they use the same settings and the same input. This can deadlock, overflow buffers or give silently wrong physics (MPI-H1).
2. A setup error on a non-root rank loses its message (MPI-H2).
3. A library that is not CUDA-aware crashes with the default `mpi_host_staging=0` (MPI-H3).
4. Diagnostics are not bit-identical to one process (MPI-M1).
5. Seven collectives and four host syncs per block step. Packing to three gives about 2x in the latency regime (MPI-M2).
6. No MPI metrics, no run record, no NVTX (MPI-M3, MPI-M4).

## Findings, ordered by severity

| ID | Severity | Title | Location |
|---|---|---|---|
| MPI-H1 | HIGH | Ranks do not check the same settings and input (deadlock, overflow, silent errors; `help=1` on one rank hangs) | `tools/h4nb_run.cpp:186-278`, `src/simulation.cu:194-246` |
| MPI-H2 | HIGH | A constructor error on a non-root rank is not printed | `tools/h4nb_run.cpp:323-327` |
| MPI-H3 | HIGH | No check that MPI is CUDA-aware when `mpi_host_staging=0` | `src/simulation.cu:531-554` |
| MPI-M1 | MEDIUM | Diagnostics not bit-identical; A9 must not `cmp` energy.dat | `src/simulation.cu:807-858` |
| MPI-M2 | MEDIUM | 7 collectives and 4 host syncs per block step | `src/simulation.cu:491-577` |
| MPI-M3 | MEDIUM | No per-phase metrics, rank imbalance, NA histogram, NVTX | `include/h4nb/h4nb.hpp`, `tools/h4nb_run.cpp:391-398` |
| MPI-M4 | MEDIUM | Run record: no run_id, hashes, schema, end status, MPI environment | `tools/run_info.hpp`, `src/mpi_comm.cpp:150-185` |
| MPI-M5 | MEDIUM | Silent GPU sharing in `select_device` | `src/mpi_comm.cpp:83` |
| MPI-M6 | MEDIUM | NaN halt only on the MPI path | `src/simulation.cu:502-508, 604` |
| MPI-M7 | MEDIUM | GH200 exchange: staging against device pointers, no overlap | `src/simulation.cu:524-559` |
| MPI-M8 | MEDIUM | Diag-point cost: not measured, up to (2P-1)x imbalance, extra traffic | `src/simulation.cu:786-858` |
| MPI-M9 | MEDIUM | CI does not run MPI; `-dirty` commit stamp; tests and A9 test spec | `.github/workflows/ci.yml:17-30`, `CMakeLists.txt:39-43` |

The details and the fixes of HIGH and MEDIUM are in the issue files.

### LOW findings

- **L1.** `comm::fatal` calls `state()`. If the communicator is not made yet, it runs `MPI_Comm_dup` (collective) on one rank, and the abort can hang. `src/mpi_comm.cpp:121-128`. Fix: use `MPI_Comm_rank`/`MPI_Comm_size` of `MPI_COMM_WORLD`.
- **L2.** Exit codes. Library `std::invalid_argument` maps to 1, not 2 (`tools/h4nb_run.cpp:325-326`). Input-file errors gave 1 at 1e26eaa, but `contracts/run-config.md:35` says 2 (ran: missing `ic` on rank 3 of 4, malformed `ic`). Commit 5ac5b22 fixes the input part (`tools/input.hpp`). Open: map the library `invalid_argument` to 2.
- **L3.** `if (std::ferror(*f) || std::fclose(*f) != 0)` skips `fclose` and leaks the FILE. `tools/h4nb_run.cpp:452-455`. Fix: close first, then check.
- **L4.** Async CUDA errors name the wrong call or phase. `predict_kernel` and `gather_kernel` launches (`simulation.cu:511, 523`) are checked only at line 530, after a collective. `correct_kernel` faults show up at the next step's sync. Fix: `cudaGetLastError()` after each launch; put the step and phase in the message to `fatal`.
- **L5.** The current CUDA device is changed for the caller (`use()` in `setup`, `release`, all getters). `release()` also clears a pending error of the caller. Fix: a scope guard, or document it.
- **L6.** Lost at `MPI_Abort`: `energy_periods.dat` is empty (written only at the end, `h4nb_run.cpp:297, 447`); a snapshot that rank 0 writes is truncated (no temp file and rename); rank-0 stdout is fully buffered under srun or a pipe. Fix: write the header early, write snapshots to `.tmp` and rename, `fflush(stdout)` at each diag point.
- **L7.** `advance_to(NaN)` passes all checks. `int64_t(NaN)` is undefined; on x86 target = 0. Ran. `simulation.cu:589-593`. Fix: `if (!std::isfinite(t)) throw`.
- **L8.** Config contract drift: the header says a single process ignores `device_offset`, but `validate()` rejects < 0 there (`simulation.cu:102`); an empty `devices` is rejected under MPI though MPI ignores it (`:101`); `rank_table(-1)` gives a negative id.
- **L9.** `abort_ranks` text differs between builds (`mpi_comm.cpp:123` against `single_rank.cpp`). Use one format.
- **L10.** The library is always collective when the world has more than one rank (`simulation.cu:180`). An application with one independent `Simulation` per rank cannot use an MPI build. Fix if needed: a Config field or a communicator argument.
- **L11.** ~~Code duplication: the `correct_kernel` dispatch~~ **Closed 2026-11-08** (`launch_correct` in `step()`). Still open: host-name code in `mpi_comm.cpp:161` and `tools/run_info.hpp`. Doc drift: "five collectives" vs "three collectives" (`docs/multi-node-design.md:33`).
- **Cross-reference.** The one-process constructor leaks CUDA resources when it throws (`simulation.cu:179-188`). This is in the library review. The MPI constructor is correct: it calls `release()` after a failed setup.

## Cost model of one block step (estimate)

- Compute: T_f = NA·(N/P)/R. Wire bytes per rank: 132·NA·(P-1)/P (68 B gather + 64 B return). Bandwidth never limits: NA=1e4, P=8 is about 1.2 MB, about 58 us, against T_f about 6 ms at N=1M.
- Latency: about (P-1)·α for each ring collective. Fixed overhead now about 120-150 us at P=8 on GH200, about 50-60 us after MPI-M2.
- Break-even NA about 30·P at N=1M. Strong-scaling efficiency at P=8: about 30% at NA=1e2, 75% at 1e3, 96% at 1e4.
- The dev box (2x 4070 Ti, N=131072) is always compute-bound (T_f about 650 us at NA=1e2). Measure the MPI overhead only on the cluster.
- Memory per rank on the device: about 268·N B replicated + 288·n B owned + about 4 MB. N=1M: about 0.3 GB. Pinned staging: about 196·N B. Memory does not limit.

## Checked and correct

- Allgatherv: own block at `off[rank]`, counts `na`, in place. Global target order = rank order, as in `step()`.
- Alltoallv: send `na[g]` at `off[g]`, receive `m` from each rank at `h*m`. Row h = rank h.
- Owner sum `sum_partials(m, P, ...)` in rank order. MPI adds no floating-point value. MPI_MIN only on integers and `min_r2` bits; MPI_BOR on status.
- Partition `N*k/P`, `fixed_center`, `nodrag`, `split()` with the rank SM count, `make_params`, `tick`, init step: the same as one process.
- Stream syncs before each MPI call; buffers are reused only after the next sync. Staging order is correct.
- `h4nb_run`: all collectives are called by all ranks in the same order, if the settings and input are the same (see MPI-H1).
- Ran: settings error (exit 2, one message), settings error on one rank only (exit 2, that rank prints), `help=1` on all ranks, unwritable `out` (exit 1), no GPU (exit 1 on all ranks), `-np 1` (one-process path), `h4nb_bench`/`h4nb_study` at np 2 (exit 2).
- Teardown: `Simulation` is destroyed before `MPI_Finalize`.

## Order of work (proposal)

1. MPI-H1, MPI-H2, L1, L3, L7 (small, testable with `mpirun` on the CPU).
2. MPI-H3 and the run record MPI-M4 (CUDA-aware flag, UUIDs, end status).
3. MPI-M3 metrics and NVTX, before any performance work.
4. MPI-M2 packing, then MPI-M7 and MPI-M8, measured with MPI-M3.
5. Decide MPI-M1 (bit-identical diagnostics) with Pavlo. Fix MPI-M6 with it.
6. MPI-M9: CI and cpu-mpi tests, then the A9 GPU test on 2x 4070 Ti, then 2/4/8 ranks on GH200.
