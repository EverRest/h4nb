# h4nb library review (main @ 14b5a4c, without MPI)

Date: 2026-11-07. Scope: all code in `src/`, `include/`, `tools/`, `tests/`, `CMakeLists.txt`, `Makefile`, CI. MPI is not in scope; it gets a separate review (`docs/review/mpi-review.md`).

**Important:** all line numbers refer to commit `14b5a4c` (origin/main). The local Mac clone was at `dd3e89f` when this file was written. Run `git pull` before you use the line numbers.

Method: the code-review skill on the last commit, plus four parallel reviewers (accuracy, data, performance, observability and quality) over the whole tree. The findings were checked against the code. No GPU was available: A1, A2, D1, D4 and D7 were confirmed with small CPU programs. All GPU findings come from reading the code. PLAUSIBLE marks a finding that is not confirmed.

Severity: HIGH = fix first (wrong results, lost data or large waste in normal runs). MEDIUM = fix soon. LOW = clean-up.

ID prefixes: A = accuracy and physics, D = data and IO, P = performance, Q = general quality, O = observability.

## Recommended order of work

1. Accuracy: A1, A3, A5 (one guard in the step choice), A2, then the tests A4 and A8.
2. Data: D1 (atomic, checked writes), D2 (exit code 2), D3 (final snapshot).
3. Resources: Q1 (RAII in the constructor).
4. Performance: P1 (skip idle warps, small tile for small NA), P5 (honest benchmark), then P2 and P3.
5. Observability: O1 to O8. Amend spec FR-020 / plan D9 first.

## Index

| ID | Severity | Location | Title |
| --- | --- | --- | --- |
| A1 | HIGH | src/hermite.cuh:136 | Cold start (all v = 0) silently gets dt_max |
| A2 | HIGH | src/hermite.cuh:199 | LinearDrag integration is 3rd order, not 4th |
| A4 | HIGH | tests/ | Dissipation and W_diss have no test |
| D1 | HIGH | src/io.cpp:81-93 | Snapshot and table writes can fail silently; not atomic |
| D2 | HIGH | tools/settings.hpp:74-77 | Input errors exit with 1, contract says 2 |
| Q1 | HIGH | src/simulation.cu:161-243 | Constructor leaks all CUDA resources on exception |
| P1 | HIGH | src/kernels.cu:24-60 | Idle threads and warps run the full pair loop when NA < TILE |
| O1 | HIGH | include/h4nb/h4nb.hpp:54 | No per-step or per-phase metrics |
| A3 | MEDIUM | src/hermite.cuh:62, 92-101 | NaN step estimate becomes a large step |
| A5 | MEDIUM | src/hermite.cuh:136 | Zero acceleration gives a false kDtUnderflow |
| A6 | MEDIUM | src/simulation.cu:37-41 | Bit-identical results also depend on the SM count |
| A7 | MEDIUM | tests/test_gpu_vs_ref.cu:122 | GPU-vs-ref test needs exact level match (PLAUSIBLE) |
| A8 | MEDIUM | tests/ | Gaps in accuracy tests |
| D3 | MEDIUM | tools/h4nb_run.cpp:334 | No final snapshot when snap > 0 |
| D4 | MEDIUM | src/io.cpp:103 | Corrupt header forces a huge allocation |
| D5 | MEDIUM | src/io.cpp:25-52 | Coincident positions with eps = 0 are not an input error |
| D6 | MEDIUM | src/simulation.cu:161-168 | Library accepts unchecked particles; N cast to int |
| D7 | MEDIUM | src/io.cpp:65-67 | Fractional ID shifts the fields silently |
| P2 | MEDIUM | src/simulation.cu:261-293 | Two host syncs and many serial launches per step |
| P3 | MEDIUM | src/kernels.cu sum_partials | Redundant partial-sum chain |
| P4 | MEDIUM | tools/h4nb_run.cpp:136 | Diagnostics every dt_max by default |
| P5 | MEDIUM | tools/h4nb_bench.cpp:77, 97-101 | Benchmark measures overhead, not the kernel |
| P6 | MEDIUM | src/simulation.cu all-gather | No P2P on 2x RTX 4070 Ti (PLAUSIBLE) |
| Q2 | MEDIUM | src/simulation.cu:153 | Calls change the caller's current CUDA device |
| Q3 | MEDIUM | src/simulation.cu:261-350 | No defined state after an exception in step() (PLAUSIBLE) |
| Q4 | MEDIUM | src/simulation.cu:346 | Asynchronous kernel errors are hard to trace |
| Q5 | MEDIUM | CMakeLists.txt:20-33 | Commit recorded at configure time; build becomes -dirty |
| Q6 | MEDIUM | .github/workflows/ci.yml | CI only compiles |
| Q7 | MEDIUM | tests/ | Test coverage gaps |
| A9-A14 | LOW | various | See section |
| D8-D14 | LOW | various | See section |
| P7-P11 | LOW | various | See section |
| Q8-Q12 | LOW | various | See section |
| O2-O8 | design | various | Observability design steps |
| O9 | MEDIUM | tools/run_info.hpp:15-46 | Run environment missing in run_info.txt (addendum) |
| Q13 | LOW | tests/test_diagnostics.cu:19 | Real two-GPU path not in the diagnostics test (addendum) |

---

## A1. Cold start (all v = 0) silently gets dt_max

- Severity: HIGH
- Location: `src/hermite.cuh:136`
- Problem: when all velocities are 0, dv = 0 and r.v = 0, so the jerk is exactly 0. The first-step estimate `eta_init * |a| / |j|` is +inf. `choose_level` returns level 0 (dt_max). No status bit is set.
- Evidence (CPU): 3 equal masses at rest, dt_max = 1/4, eta = 0.01. After one step |dE/E| = 3.7e-4. With a fine fixed step: 3e-14.
- Fix: when |j| = 0 or the ratio is not finite, use a free-fall estimate `eta_init * sqrt(sqrt(r2min) / |a|)` (r2min is already available). Or compute snap and crackle at t = 0 and use the full Aarseth formula. Add a cold-start test.

## A2. LinearDrag integration is 3rd order, not 4th

- Severity: HIGH
- Location: `src/hermite.cuh:163-169, 199`; `specs/001-hermite-nbody-lib/research.md` R7
- Problem: the drag is computed from the predicted velocity vp (accurate to O(h^3)). The h/2 * a1 term of the corrector then adds a local error O(h^4), so the global error is O(h^3).
- Evidence (CPU, pure drag, tau = 1, fixed steps h = 1/8 ... 1/256): the velocity error and the balance E - E0 - W_diss go down by about 8 when h halves, not 16. A second correction (P(EC)^2) gives 16 again.
- Fix: for D != Off, do one more correction: compute a_diss and j_diss again at the corrected v and correct again. This costs O(N_active) and does not change the force kernel. Alternative: exact exponential factor or operator splitting for the drag. Minimum: correct the R7 text ("4th order").
- Related: A14.

## A4. Dissipation and W_diss have no test

- Severity: HIGH
- Location: `tests/` (no test sets `Dissipation::LinearDrag`; `ref::Ref::w_diss()` is never called)
- Problem: the j_tot formula, W_diss bookkeeping, "particle 0 has no drag" and GPU-vs-reference agreement with drag are not checked.
- Fix: add a drag-only analytic test (v = v0 * exp(-t / tau), W = delta K), a Kepler + drag energy-balance test, and a drag case in `test_gpu_vs_ref`.

## D1. Snapshot and table writes can fail silently; not atomic

- Severity: HIGH
- Location: `src/io.cpp:81-93` (write_snapshot); `tools/h4nb_run.cpp:246-345` (fprintf/fflush/fclose of energy, momentum, timesteps, performance, energy_periods); `tools/h4nb_mkdisk.cpp` (fclose not checked)
- Problem: the stream state is checked before the final flush; close happens in the destructor without a check. There is no temp file + rename.
- Evidence (CPU): `write_snapshot("/dev/full", 2 particles)` reports no error.
- Scenario: disk full or quota at the end of a long GH200 run gives a truncated `snap_final.snap` and exit 0. A crash during the write also destroys the old file at that path.
- Fix: write to `path.tmp`, call `f.close()`, check `f.fail()`, then `std::filesystem::rename`. Check every `fclose` return value; on failure throw (exit 1).

## D2. Input errors exit with 1, contract says 2

- Severity: HIGH
- Location: `tools/settings.hpp:74-77` (settings_main_error); `src/simulation.cu:97, 171-173`
- Problem: run-config.md section 3 says "2 = settings or input error". The loaders throw `std::runtime_error` (repeated ID, m <= 0, NaN, malformed line, truncated snapshot) and the library throws `std::invalid_argument` (bad device id, empty devices). Both map to 1. The `n` and `central_id` checks give 2, so the codes are not consistent.
- Scenario: a Slurm script that separates "fix the input" (2) from "node failure" (1) classifies a bad IC wrongly.
- Fix: catch loader and validation errors in the tools and rethrow them as `SettingsError` or a new `InputError` that maps to 2. Check device ids against `cudaGetDeviceCount` in the tool.

## Q1. Constructor leaks all CUDA resources on exception

- Severity: HIGH
- Location: `src/simulation.cu:161-243` (Impl constructor); `Dev` struct has no destructor; `~Impl` at `:245` does not run when the constructor throws
- Scenario: cudaMalloc out of memory on the second device, or `step(true)` fails. All buffers, streams, events and pinned memory leak. In an `h4nb_study` or `h4nb_bench` sweep, or any user that catches the exception, the next Simulation objects fail too.
- Breaks: `docs/cuda-best-practices.md` (RAII on all exit paths).
- Fix: give `Dev` an RAII destructor (move-only), or wrap the constructor body in try/catch and call a shared `release()`.

## P1. Idle threads and warps run the full pair loop when NA < TILE

- Severity: HIGH
- Location: `src/kernels.cu:24-60` (force_kernel); grid at `src/simulation.cu:315`
- Problem: threads with `i >= na` use xi = 0 and still run the whole pair loop. Whole warps past `na` also run it. With tile = 128 and NA = 2..4, 3 of 4 warps do useless FP64 work.
- Scenario: `stellar` preset (eps = 1e-4) with a hard binary at deep levels: tens of thousands of block steps with NA = 2.
- Fix, cheapest first:
  1. Warp-uniform skip of the compute for warps with `blockIdx.x*TILE + warp*32 >= na`. These warps still load shared memory and reach `__syncthreads`. Gain: about TILE/32 (x4 at tile 128).
  2. Use tile = 64 when NA is small. NA is deterministic, so results stay deterministic.
  3. Small-NA kernel: lanes of a warp split j for the same i, then a fixed-order shuffle tree (keeps constitution IV). Only this removes the remaining waste inside a warp.
- Note: an upper estimate of TILE/NA (up to x64) is too high, because idle lanes inside one warp save nothing in SIMT.

## O1. No per-step or per-phase metrics

- Severity: HIGH (for the owner's goal: trace into metrics, group runs, collect statistics)
- Location: `include/h4nb/h4nb.hpp:54` (Stats has only block_steps, active_total, min_r2); `src/simulation.cu:185-186` (events use `cudaEventDisableTiming`)
- Missing: per-step data; histograms of active-block size and dt level (`timesteps.dat` has only min/max/mean dt); time per phase; GFLOP/s in run logs; centre-of-mass drift; NVTX ranges; callback API; log levels; schema version, units, run_id, config hash in .dat files; machine-readable verdict (it goes to stdout only, `tools/h4nb_run.cpp:343`); end time and exit status. A second run into the same `out=` overwrites the first silently.
- Spec conflict: FR-020 / plan D9 (`spec.md:144`) does not allow kernel or transfer times in `performance.dat` until they are requested. The owner has now requested them. Amend the spec first.
- Fix: design O2-O8 below.

---

## A3. NaN step estimate becomes a large step

- Severity: MEDIUM
- Location: `src/hermite.cuh:62, 92-101`
- Problem: `aarseth_dt` returns 0/0 = NaN when j1 = s1 = 0 (for example all source masses 0; at init when a = j = 0). `while (d > NaN)` does not run. The particle goes one level coarser when time is aligned (level 0 at init). No flag.
- Fix: if `!(dt_want > 0)` or not finite, keep `k_old` (at init: `max_level`) and set a status bit. Same guard as A1 and A5.

## A5. Zero acceleration gives a false kDtUnderflow

- Severity: MEDIUM
- Location: `src/hermite.cuh:136`
- Problem: a body exactly at the centre of a symmetric start: `eta_init * 0 / |j| = 0`. It starts at `max_level` and `kDtUnderflow` is set, but nothing is wrong.
- Fix: same guard as A1.

## A6. Bit-identical results also depend on the SM count

- Severity: MEDIUM
- Location: `src/simulation.cu:37-41` (split uses `e.sms`); `plan.md` (bit-identical claim)
- Problem: `nj`, `chunk` and the order of partial sums change with the SM count. The same `config.used` on RTX 4070 Ti and GH200 gives different bits. The docs mention only tile and blocks_per_sm.
- Fix: document it and write the SM count to `run_info.txt`, or make `nj` a function of N only.

## A7. GPU-vs-ref test needs exact level match (PLAUSIBLE)

- Severity: MEDIUM
- Location: `tests/test_gpu_vs_ref.cu:122`
- Problem: GPU `::rsqrt`, fmad and a different summation order can flip one level at a power-of-two boundary. The trajectories then differ by more than 1e-10. Unlikely at N = 777 over 2 time units, more likely for larger N or t_end.
- Fix: allow a small number of level mismatches, or build this test with `-fmad=false`, or document it.

## A8. Gaps in accuracy tests

- Severity: MEDIUM
- Location: `tests/`
- Problem: convergence order is checked only in Fixed mode. No energy-conservation test with eps > 0. No N >> 3 (Plummer) test against the 1e-8 goal.
- Fix: block-mode eta scan (error about eta^2), softened Plummer N = 64-256 energy test, cold-start case (A1).

## D3. No final snapshot when snap > 0

- Severity: MEDIUM
- Location: `tools/h4nb_run.cpp:334`
- Problem: `snap_final` is written only when `snap` and `snap_times` are not set. `snap=10 t_end=6.3125` writes only t = 0.
- Fix: always write the final state when the last segment was not a snapshot time, or require `t_end % snap == 0`.

## D4. Corrupt header forces a huge allocation

- Severity: MEDIUM
- Location: `src/io.cpp:103` (read_snapshot)
- Problem: `p.resize(h.n)` runs before a size check. n about 1e9 tries 64 GB (OOM killer). n = 2^61 gives a cryptic `length_error`. Trailing bytes after valid data are accepted; `reserved` is not checked.
- Fix: before resize, compare the file size with exactly `32 + 64*n`; reject n > SIZE_MAX/64; treat trailing bytes as an error.

## D5. Coincident positions with eps = 0 are not an input error

- Severity: MEDIUM
- Location: `src/io.cpp:25-52` (validate); `tools/h4nb_run.cpp:252-288`
- Problem: two particles at the same point load without error. `rsqrt(0) = inf` gives NaN in the first force pass. `h4nb_run` does not check `status()` after the constructor; it writes an inf/NaN row and runs a full diag segment before exit 3.
- Fix: check `sim.status() & kNaN` right after the constructor and treat it as an input error. When eps2 == 0, optionally find duplicate (x, y, z) with a hash set.

## D6. Library accepts unchecked particles; N cast to int

- Severity: MEDIUM
- Location: `src/simulation.cu:161-168`
- Problem: the constructor checks only array sizes. m > 0, finite values and unique IDs are not checked for API users. `N(int(p.size()))` runs before any check (n = 2^32 + 3 simulates 3 particles).
- Fix: expose `validate()` from io.cpp and call it in the constructor (O(N)); reject n > INT_MAX.

## D7. Fractional ID shifts the fields silently

- Severity: MEDIUM
- Location: `src/io.cpp:65-67` (load_text)
- Evidence (CPU): the line `1.5 1 0 0 1 0 0` (7 tokens) loads as id = 1, m = 0.5, and all other fields shift by one.
- Fix: read each field as a token and parse it with strtoll/strtod plus an end-pointer check, as `tools/settings.hpp` does.

## P2. Two host syncs and many serial launches per step

- Severity: MEDIUM
- Location: `src/simulation.cu:261-293`
- Problem: the pipeline drains twice per step (Tn, then NA): about 20-40 us per step plus launch latency. After P1 this is the floor for small-NA steps.
- Fix: keep Tn and NA in device memory (predict and IsActive read Tn there); size the force grid for an upper bound with early exit; then capture the step in a CUDA graph. Estimate: x2-5 on steps with NA < about 1000.

## P3. Redundant partial-sum chain

- Severity: MEDIUM
- Location: `src/kernels.cu` (sum_partials); `src/simulation.cu:317, 334`
- Problem: one thread per target loops over nj rows (up to about 528 on GH200). With G = 1 the second sum_partials and the fa -> ra copy only copy data. With nj = 1 the first sum is only a copy.
- Fix: write fa directly when nj == 1; skip the second sum when G == 1 or fuse it into correct_kernel; for large nj use a fixed tree over several threads per target (deterministic).

## P4. Diagnostics every dt_max by default

- Severity: MEDIUM
- Location: `tools/h4nb_run.cpp:136` (diag default = dt_max); `src/simulation.cu:437-470`
- Problem: each call is potential_kernel (N^2/2 pairs) + `state()` (64 MB pageable D2H at N = 1e6) + several syncs. Estimate: 10-15 % of run time.
- Fix: a coarser default (for example period/100), document the cost, K/P/L reduction on the GPU. Open question for the owner: change the default?

## P5. Benchmark measures overhead, not the kernel

- Severity: MEDIUM
- Location: `tools/h4nb_bench.cpp:77, 97-101`
- Problem: the timer covers the whole constructor (about 25 cudaMalloc, upload, lazy module load). The warm-up loads only tile = 128, so 64 and 256 pay the module load in the timer and "best tile" moves to 128. One sample, no repeats. `step_pair/s` counts only useful pairs and hides P1.
- Fix: warm up each tile/bpsm; time a second force pass with CUDA events; median of 3-5 repeats; also report computed pairs `ceil(NA/T)*T*N`.

## P6. No P2P on 2x RTX 4070 Ti (PLAUSIBLE)

- Severity: MEDIUM
- Location: `src/simulation.cu` all-gather and slice copies (about :297-325); peer setup :223-234
- Problem: GeForce Ada has no P2P, so each cross-device `cudaMemcpyAsync` goes through the host. About 10 copies per step (tx, tv, tid, fa, fj), 10-30 us each.
- Fix: pack tx+tv+tid and fa+fj into one buffer each; explicit pinned staging buffers.

## Q2. Calls change the caller's current CUDA device

- Severity: MEDIUM
- Location: `src/simulation.cu:153` (use() calls cudaSetDevice), all public methods including const ones
- Fix: RAII DeviceGuard that saves and restores `cudaGetDevice`.

## Q3. No defined state after an exception in step() (PLAUSIBLE)

- Severity: MEDIUM
- Location: `src/simulation.cu:261-350`
- Problem: if a check throws in the middle, some devices have corrected their particles and T has not moved. The next `advance_to` runs on a broken state.
- Fix: a `failed_` flag; after it is set, every call throws.

## Q4. Asynchronous kernel errors are hard to trace

- Severity: MEDIUM
- Location: `src/simulation.cu:346` (one cudaGetLastError per step); `ck()` at :19
- Problem: an execution fault shows up later in an unrelated `cudaStreamSynchronize`, with no kernel name and no device id.
- Fix: build option or env `H4NB_DEBUG_SYNC` (sync + check after each launch); add the device id to `ck()`.

## Q5. Commit recorded at configure time; build becomes -dirty

- Severity: MEDIUM
- Location: `CMakeLists.txt:20-33`; `Makefile:10, 16`; `.gitignore`
- Problem: a rebuild after a commit records the old commit, so runs are grouped under the wrong build. `make bench` writes `bench/` and `make pack` writes `h4nb_logs_*.tar.gz` into the tree; `.gitignore` does not cover them, so the next configure marks the build `-dirty`.
- Fix: generate the header at build time (`add_custom_target` + `cmake -P`); add `bench/` and `h4nb_logs_*.tar.gz` to `.gitignore`.

## Q6. CI only compiles

- Severity: MEDIUM
- Location: `.github/workflows/ci.yml`
- Problem: CUDA is built (arch 80) and only `ctest -L cpu` runs. No sm_89 / sm_90 build, no `-Wall -Wextra`, no tool smoke runs (`help=1`, pack). GPU tests and compute-sanitizer never run automatically.
- Fix: add sm_89 and sm_90 to the CI build, warning flags, tool smoke runs; a self-hosted runner on the RTX 4070 Ti machine for `ctest -L gpu` + compute-sanitizer.

## Q7. Test coverage gaps

- Severity: MEDIUM
- Location: `tests/`
- Not tested: Config validation (T009), kDtUnderflow bit, `build_info()`, Settings (about 400 lines), PeriodTracker (verdict and drift), `h4nb_pack.sh`, `potential_kernel` for tile 64 and 256. All except the last are plain C++ or shell and can run in CI as cpu tests.
- IO tests to add (`tests/test_io.cpp`): write to /dev/full; header with n = 2^40 or n larger than the file; trailing bytes; fractional ID / 7-token line; coincident positions; exit 2 for a repeated ID; final snapshot when snap > t_end.

---

## Low: accuracy (A9-A14)

- **A9.** NaN does not stop `advance_to` (`src/simulation.cu:356-366`): kNaN is only a bit. Check status in advance_to and stop early.
- **A10.** Cancellation in dx = xj - xi for close pairs far from the origin (R = 1e3, d = 1e-8 gives a force direction good to about 1e-5). FP64 limit, not a bug. Document it; keep the central body at the origin.
- **A11.** Per-particle phi sums on the GPU (potential_kernel, sum_phi) and the cross-device sum (`simulation.cu:468`) have no compensation: about 1e-13 at N = 1e6, acceptable. The Neumaier comment applies to the host only.
- **A12.** `|E - E0 - W| / |E0|` has no meaning when E0 is about 0. Add normalisation by |K0| + |U0| as an option.
- **A13.** `time() = double(T) * tick` is not exact for T > 2^53 (reported time only; integration uses tick differences).
- **A14.** W_diss uses P1 from v1, but a1 came from a_diss(vp): O(h^3) inconsistency. Goes away with A2.

## Low: data (D8-D14)

- **D8.** `std::max(max_err, err)` drops NaN (`tools/h4nb_run.cpp:277`, `tools/h4nb_study.cpp:170`, PeriodTracker::add): a NaN only in diagnostics can give PASS. Add `if (!std::isfinite(err)) return 3`.
- **D9.** No `static_assert` for a little-endian host; `write_snapshot` does not check that the 8 arrays have the same size (`src/io.cpp:87-91`).
- **D10.** Disk IC is not reproducible across libstdc++ / libc++ / MSVC: `uniform_real_distribution` and `normal_distribution` are implementation-defined (`tools/disk.hpp:15-17`). Derive values from raw `mt19937_64` bits, own Box-Muller.
- **D11.** `is_multiple` has relative tolerance 1e-9 (`tools/settings.hpp:68-71`): `t_end=1.0000000001` is accepted, the run stops at 1.0, `config.used` records the other value.
- **D12.** `study.dat` and `bench.dat` write eta, dt_max, eps2 with `%g` (`tools/h4nb_study.cpp:139, 189`; `tools/h4nb_bench.cpp:83`): grouping keys lose precision. Use `%.17g`.
- **D13.** `central_id` and `n` are int, IDs are int64; `h4nb_mkdisk` with n = INT_MAX overflows the loop; a level error in `h4nb_order` gives exit 1, not 2.
- **D14.** `r_min` in `timesteps.dat` is the minimum since t = 0, not per interval; the close-pair warning is shown once and does not name the particle IDs (`tools/h4nb_run.cpp:325-326`; FR-017).

## Low: performance (P7-P11)

- **P7.** predict_kernel, DeviceSelect and DeviceReduce run over all N each step (about 60 us at N = 131k on RTX 4070 Ti). Per-level counters in correct_kernel can give Tn without a reduction. Matters only after P1 and P2.
- **P8.** No `__launch_bounds__(TILE)` on the templated kernels (`src/kernels.cu:24`), although `docs/cuda-best-practices.md` asks for it; `#pragma unroll 4` over a run-time nt (add an nt == TILE fast path); `shv[k].w` and `vi.w` are loaded but not used. 0-10 %, PLAUSIBLE. Check spills with `-Xptxas -v`.
- **P9.** `atomicMin(minr2)` on one address from every active thread (correct_kernel): about 0.5 ms at init with N = 1e6. Do a warp min with shuffles first.
- **P10.** No `-lineinfo` (needed by Nsight source view and compute-sanitizer, no speed cost); `CMAKE_CUDA_ARCHITECTURES native` (`CMakeLists.txt:11-12`) fails on a GPU-less GH200 login node. Document `-DCMAKE_CUDA_ARCHITECTURES="89;90"` for release.
- **P11.** `state()`, `levels()` and the phi / wd buffers in diagnostics() use pageable host memory: D2H about x2 slower. Matters together with P4.

## Low: quality (Q8-Q12)

- **Q8.** `launch_force` and `launch_potential` repeat the same tile switch (`src/simulation.cu:44-64`); the set {64, 128, 256} is hard-coded in about 7 places. One `dispatch_tile` helper + one constexpr list.
- **Q9.** h4nb_bench: settings errors from the library exit with 1, not 2; `nan` in the %peak column when fp64_peak is not set (print `-`); sizes/tiles/bpsm lists are not de-duplicated; `Row::wall` is not used.
- **Q10.** `h4nb_pack.sh`: RUN_DIR with a trailing `/` gives `run1/run1/...` in the archive (`rel=${f#"$d"/}`; strip with `d=${d%/}`); in the Makefile `$(OUT)` and `$(RUN)` are not quoted and `SNAP` accepts only `1`; the `*.txt` pattern packs large IC text files.
- **Q11.** Doc drift: `contracts/file-formats.md:37` and the `h4nb_bench.cpp:7` comment say wall_s includes "first time steps", but it is only the first force pass; README does not list `h4nb_study` among the tools.
- **Q12.** No `H4NB_VERSION`, no install/export target, no `h4nb::h4nb` alias; tools reach CUDA through `CUDAToolkit_INCLUDE_DIRS` instead of `CUDA::cudart`; thread safety of Simulation is not documented; peer access is enabled process-wide and never disabled.

---

## Observability design (O2-O8)

Each step hooks into existing code. Order: O2, O3, O6, O8 give most of the value.

### O2. Host counters, always on (no GPU cost)

In `Impl::step()` after NA is summed (`src/simulation.cu:287-293`) and at `++st.block_steps` (`:347-348`):
- log2 histogram of NA;
- block level `L = max_level - ctz(Tn)` (dt-level distribution of block steps).

Expose `struct Metrics { block_steps, active_total, active_hist[64], step_level_hist[51], PhaseTimes t; }` and `Metrics Simulation::metrics(bool reset = false)` next to `stats()` in `include/h4nb/h4nb.hpp`. New structs keep source compatibility.

### O3. Phase timers (opt-in, `Config::timing`, default off)

Separate timing events per device at the phase limits in `step()`: predict/select (:279), gather/transfer (:299), force + partial sums (:315-317), reduce + correct (:334-345). Read `cudaEventElapsedTime` only at the sync in `advance_to` (:365), so no new syncs. Also time `diagnostics()` (:435) and the first force pass in the constructor (:242).

### O4. NVTX ranges

Header-only nvtx3 (CUDA 12), RAII `H4_RANGE("force")` on the same phases plus `advance_to` and `diagnostics`. CMake option `H4NB_NVTX` (default ON), link `CUDA::nvtx3`. Near-zero cost without a profiler. Also serves T022.

### O5. Callback and centre of mass

- `void Simulation::on_step(std::function<void(const StepInfo&)>)`, called at :348 with {T, time, NA, level, block_step}. Host data only.
- `com[3]`, `vcom[3]` in `Diagnostics`, Neumaier sums in the existing loop in `diagnostics()`.

### O6. Run outputs in h4nb_run

- `run_id = <start_utc>-<host>-<pid>`; `config_hash = sha256(config.used body + commit + IC sha256)`. Write both into `run_info.txt` (`tools/run_info.hpp`), plus GPU UUID, PCI bus, memory, clocks, SM count (A6), compiler flags.
- `metrics.jsonl`: one record per diag interval from the loop at `tools/h4nb_run.cpp:303-331`. Fields: `"schema":"h4nb.metrics/1"`, run_id, t, wall_s, block_steps, active, pairs_per_s, gflops, rel_err, dP_rel, dL_rel, W_diss, com drift, active_hist, level_hist, phase_s.
- `summary.json` at :338-345 and on the NaN exit path (:315): verdict, max/mean error, drift, init/step/diag/total wall time, step time mean/p50/p95, exit code, end_utc.
- `# schema:` and `# units:` header lines in all .dat files.
- Do not overwrite an existing run directory silently (refuse, or add a suffix).
- Make pairs_per_s consistent: `performance.dat` uses active*N, `bench.dat` uses N(N-1).

### O7. h4nb_study and h4nb_bench

Same run_id and schema lines. Write the `segments` step rate into `bench.dat` (now stdout only, `tools/h4nb_bench.cpp:107-115`).

### O8. Aggregation script

New `tools/h4nb_collect.py` (stdlib only). It walks run directories and pack archives, reads `run_info.txt`, `config.used` and the JSON files, and writes one long-format CSV. It groups by (commit, gpu_name, N, devices, eta, dt_max, tile, bpsm, eps) and reports n, mean, p50, p95.

---

## Verified correct

- Predictor dt^2/2, dt^3/6 (`src/hermite.cuh:30-35`); Makino-Aarseth 4th-order corrector (`:66-74`); snap/crackle coefficients -6/-4/-2 and 12/6, snap moved to t1 (`:77-84`); Aarseth criterion (`:62`).
- Jerk and Plummer softening: eps^2 used the same way in force, potential and CPU reference; U = -G sum mi*mj / sqrt(r^2 + eps^2) over pairs j > i.
- Time in int64 ticks, steps from tick differences: no time drift. `choose_level` keeps block commensurability.
- Self-interaction excluded by global index; partial sums over devices in a fixed order; bit-pattern atomicMin on non-negative doubles is correct.
- Dissipation: j_tot = j_grav - a_tot/tau and P' = m(a.a_diss - v.a/tau) are correct; W_diss skipped at init; particle 0 has no drag on all devices; the Off path has no extra instructions.
- GPU split N/G has no gaps; IDs and order are kept; no N*N int overflow; settings precedence default < preset < file < env < CLI with strict number parsing; no fast-math.

---

## Addendum: criteria from the MPI review (single-node part)

Added on 2026-11-07 after a criteria exchange with the MPI review. These criteria were not in the first pass.

### Memory footprint per device (no issue)

From the allocations in `src/simulation.cu:189-205`, with n = N/G on each device:

```
bytes per device ~= 268*N + 288*n + 64*blocks_per_sm*sms*tile   (+ small CUB temp)
```

- N-sized buffers on every device: tx, tv (64N), tid (4N), fa, fj (64N), phi (8N), pa/pj base (64N), ra/rj (64*G*n = 64N).
- n-sized: x, v, a, j, xp, vp (192n), t, next (16n), level, act (8n), ca, cj (64n), wd (8n).
- N = 131072, G = 1 on RTX 4070 Ti (60 SM, bpsm 16, tile 256 worst case): about 73 MB + 16 MB = 0.09 GB of 12 GB.
- N = 1e6, G = 1: about 0.56 GB. Memory does not limit any realistic run; O(N^2) time does.
- Note: per-device memory does not go down with more GPUs, because the N-sized buffers are on every device. This is acceptable now.

### Bytes per block step between GPUs (no issue, see P6)

All-gather of active targets: (G-1)*NA*68 B (tx, tv, tid). Force slices back to owners: (G-1)*NA*64 B (fa, fj). Total about 132*(G-1)*NA bytes per block step, plus 2*G small D2H copies (Tn, NA). Without P2P all of it goes through host memory, with no overlap with compute.

### Stream and buffer reuse hazards (no issue)

Checked: cross-device writes into tx/tv/tid and ra/rj use disjoint ranges per device; consumers wait on ev_tx / ev_f; each step starts with a full host sync, so there is no WAR hazard on the next step. `diagnostics()` runs after `state()`, which syncs. Work is balanced: each device owns N/G sources and computes all NA targets.

### Input read cost (no issue)

Measured on CPU with g++ -O2: `load_text` for N = 1e6 takes 1.6 s; `write_snapshot` 0.02 s; `read_snapshot` 0.08 s. Strictness gaps are D4 and D7.

### O9. Run environment missing in run_info.txt

- Severity: MEDIUM (needed to group and compare runs)
- Location: `tools/run_info.hpp:15-46`
- Problem: run_info.txt has device name and cc, but not: `CUDA_VISIBLE_DEVICES`, GPU UUID and PCI bus id, total memory, SM count (see A6), clocks and application clocks, persistence mode, ECC, power limit, P2P capability between the listed devices, `CUDA_MODULE_LOADING`. Two runs on "device 0" can be different physical GPUs.
- Fix: add these keys from `cudaGetDeviceProperties` (uuid, pciBusID, totalGlobalMem, multiProcessorCount, clockRate), `getenv`, and `cudaDeviceCanAccessPeer`. Clocks, persistence and ECC need NVML (optional, `#ifdef`), or keep them in `h4nb_pack.sh`, which already stores nvidia-smi output.

### Q13. Real two-GPU path not covered by the diagnostics test

- Severity: LOW
- Location: `tests/test_diagnostics.cu:19`
- Problem: the test uses only `{0}` and virtual `{0, 0, 0}`. `test_gpu_vs_ref.cu:31` adds `{0, 1}` when 2 GPUs exist, but diagnostics() with real peer copies is not tested. Also `devices=0,0` is accepted in production configs without a warning.
- Fix: add `{0, 1}` to test_diagnostics when `cudaGetDeviceCount >= 2`; print a warning in the tools when a device id repeats.
