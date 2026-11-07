---
description: "Task list for h4nb: configuration, speed, multi-node scale and input safety"
---

# Tasks: Direct N-body Gravity Integrator (h4nb)

**Input**: `specs/001-hermite-nbody-lib/` (plan.md, spec.md, research.md, data-model.md, contracts/).

**Prerequisites**: commit `339ce35` holds the library, the tools and the test suite (detailed plan Tasks 1 to 6). This list covers only the remaining work.

**Tests**: this list has **no test tasks**, by request. The existing CTest suite stays. Before each task is marked done, run `ctest -L cpu` (and `ctest -L gpu` on a GPU machine), as `docs/cuda-best-practices.md` section 5 requires. The acceptance runs A1 to A8 stay in `quickstart.md`. They are not repeated here.

**Speed rule** (constitution II): a task marked **Gate** starts only when its measured gate is true. Record the number before and after the change in `docs/results.md`.

**Rules for all tasks**: read `docs/cuda-best-practices.md` before a code change. Write all text in ASD-STE100. Do not commit or push unless Pavlo asks. Send a message to the other session before you edit a file that it edits.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (a different file, no dependency on an open task).
- **[Story]**: the user story in spec.md (US1 to US6). Setup, foundational and polish tasks have no story label.

---

## Phase 1: Setup

**Purpose**: example configurations, build targets and the constitution amendment.

- [x] T001 [P] Create `configs/agn.cfg`, `configs/stellar.cfg`, `configs/dev-4070ti.cfg` and `configs/gh200.cfg` with the keys of `contracts/run-config.md`. Set `eta=0.0005` in each (user decision, 2026-11-07). Add one comment line for each key that says why the value was chosen.
- [ ] T002 [P] In `CMakeLists.txt`, confirm that no flag is x86-only, so the build works on aarch64 (GH200). Add the configure examples for `89`, `90` and `"89;90"` to the comment above `CMAKE_CUDA_ARCHITECTURES`.
- [x] T003 Apply the constitution amendment 2.0.0 in `.specify/memory/constitution.md` with the text of `docs/multi-node-design.md` section 7. Add aarch64 to the platform line. Remove the GTX 1060 (compute capability 6.1). Done on 2026-11-07 with the user's approval.

---

## Phase 2: Foundational (configuration layer and input safety)

**Purpose**: one key table and strict configuration for all tools (Pavlo's request). All later phases use it.

**⚠️ CRITICAL**: finish this phase before the user-story phases.

- [x] T004 Create `tools/settings.hpp`: the `Setting` entry (name, type, default, range, help, value, source) and the typed getters. Types: real, int, bool, string, int list, real list, enum (data-model.md section 5).
- [x] T005 In `tools/settings.hpp`, add the sources and the precedence: default, `preset=`, `config=<file>`, `H4NB_<KEY>`, command line. Reject an unknown key, a bad value, a value out of range, a repeated key in one file and a nested `config=`. Exit with code 2. Name the key, the value and the source in each message (contracts/run-config.md sections 1 to 3).
- [x] T006 In `tools/settings.hpp`, add the presets `none`, `agn` (eps=0.01) and `stellar` (eps=0.0001) (contracts/run-config.md section 4).
- [x] T007 In `tools/settings.hpp`, add `write_used(path)` for `config.used` (key, value, source) and `help=1` (prints the key table).
- [x] T008 Add `tile` and `blocks_per_sm` to `h4nb::Config` in `include/h4nb/h4nb.hpp`, with the defaults 128 and 4 (contracts/public-api.md).
- [x] T009 In the `Simulation` constructor in `src/simulation.cu`, validate every `Config` field (eta > 0, dt_max a power of two, max_level 1 to 50, fixed_level range, tile in {64, 128, 256}, blocks_per_sm 1 to 16, eps2 ≥ 0, a known device list). Throw `std::invalid_argument` with the field name. Do not clamp.
- [x] T010 [P] In `src/io.cpp`, make `load_text` and `read_snapshot` reject a repeated ID, m ≤ 0, a non-finite value and N < 2. Name the file, the line or index, and the field (research R5).
- [x] T011 Move `tools/h4nb_run.cpp` to `settings.hpp`. Add the keys `n`, `central_id`, `period`, `period_kind`, `dissipation`, `drag_tau`, `drag_vbg`, `snap_times`, `energy_tol`, `perf`, `tile`, `blocks_per_sm`. Reject `t_end`, `diag` and snapshot times that are not multiples of `dt_max`. Write `config.used` in the output directory.
- [x] T012 [P] Move `tools/h4nb_mkdisk.cpp` and `tools/h4nb_order.cpp` to `settings.hpp`. Keep the current key names and defaults.
- [ ] T013 Delete `tools/args.hpp` when no tool includes it. (Deletion needs Pavlo's permission on the device.)

**Checkpoint**: every tool reads defaults, presets, files, environment and command line in the same way. Each run writes `config.used`.

---

## Phase 3: User Stories 1, 2 and 3 – accuracy and convergence study (Priority: P1) 🎯 MVP

**Goal**: the energy verdict and the convergence study use the configuration layer. The researcher gets one table and a pass or fail answer.

**Independent check**: `h4nb_study config=configs/agn.cfg ic=<small disk>` writes `study.dat` with one row for each grid point and prints the cheapest passing setting.

- [x] T014 [US2] In `tools/h4nb_run.cpp`, compute the max and mean relative energy error over the reference period (`period`, or the estimate of `period_kind`). Print `PASS` or `FAIL` against `energy_tol`. Print ε and the preset in the report header (spec edge case "Softening is enabled").
- [x] T015 [US3] Create `tools/h4nb_study.cpp`. It runs the grid `etas × dt_maxes × t_ends` in one process. It reuses one particle set and constructs one `Simulation` for each grid point. It writes `study.dat` (data-model.md section 9). It prints the cheapest point that passes, by `pair_evals`.
- [x] T016 [US3] Register `h4nb_study` in `CMakeLists.txt`. Change `tools/eta_scan.sh` to call `h4nb_study`, or mark it as replaced in a comment.

**Checkpoint**: US1 to US3 run from config files. The η value for a system comes from a table, not from a guess.

---

## Phase 4: User Story 4 – speed on 1M particles (Priority: P2)

**Goal**: the force pass reaches 40 to 70 % of the FP64 peak. The tuning values are selected by measurement, without a rebuild.

**Independent check**: `h4nb_bench sizes=131072,1024000 tiles=64,128,256 bpsm=2,4,8` writes `bench.dat` with one row for each combination.

- [ ] T017 [US4] In `src/kernels.cuh` and `src/kernels.cu`, make `force_kernel` and `potential_kernel` templates over the tile size. Instantiate 64, 128 and 256. Keep the arithmetic and the order of the sums unchanged.
- [ ] T018 [US4] In `src/simulation.cu`, dispatch the kernel instance from `Config::tile`. Use `Config::blocks_per_sm` in `split()` in place of the constant 4. Compute `pcap` from both values. With the defaults, the results must stay bit-identical to commit `339ce35`.
- [ ] T019 [US4] Move `tools/h4nb_bench.cpp` to `settings.hpp`. Add `sizes`, `tiles`, `bpsm` and an optional `fp64_peak` (TFLOP/s). Write `bench.dat` with `N devices tile blocks_per_sm pairs_per_s gflops wall_s` and the percent of peak when `fp64_peak` is set.
- [ ] T020 [US4] Measure the baseline on the RTX 4070 Ti: `h4nb_bench sizes=16384,131072,262144 tiles=64,128,256 bpsm=2,4,8 devices=0` and `devices=0,1`. Record the table and `run_info.txt` in `docs/results.md`. Write the best `tile` and `blocks_per_sm` into `configs/dev-4070ti.cfg`.
- [ ] T021 [US4] Do T020 again on one GH200 with `sizes=131072,524288,1024000`. Write the best values into `configs/gh200.cfg`.
- [ ] T022 [US4] Profile one block-step run of 131 072 particles with `nsys profile` on each machine. Record the share of `predict_kernel`, `DeviceSelect`, the force kernel, the copies and the host syncs. These numbers are the gates of T023 to T025.
- [ ] T023 [US4] **Gate: `predict_kernel` > 10 % of the step time (T022).** O1: predict the sources inside the tile load of the force kernel. Remove `predict_kernel` from the step. Measure before and after.
- [ ] T024 [US4] **Gate: `DeviceSelect` + `predict_kernel` > 10 % of the step time.** O3: keep the particles sorted by level, or keep one list for each level. Select and predict only the needed range. Measure before and after.
- [ ] T025 [US4] **Gate: median N_active < about 5000 and the step time is dominated by latency.** O4: compute `Tn` and the counts on the device and capture the block step in a CUDA graph. Remove the two host syncs for each block step. Measure before and after.
- [ ] T026 [US4] **Gate: the force kernel is below 40 % of the FP64 peak after T020/T021.** Read the Nsight Compute report (registers, occupancy, FP64 pipe use). Try `__launch_bounds__` and `#pragma unroll` values in the force kernel. Keep a change only when `bench.dat` shows a gain.

**Checkpoint**: tuned values are in the config files. Each optimisation that was done has its before and after numbers in `docs/results.md`.

---

## Phase 5: User Story 6 – reproducible runs (Priority: P2)

**Goal**: each result carries the full record that a person needs to repeat it.

**Independent check**: `h4nb_run config=<out>/config.used out=<out2>` gives identical `.dat` and `.snap` files.

- [x] T027 [P] [US6] Add `h4nb::build_info()` to `include/h4nb/h4nb.hpp` and `src/simulation.cu`. Pass the commit and the architectures from CMake as compile definitions.
- [x] T028 [US6] In `tools/h4nb_run.cpp`, `h4nb_bench.cpp` and `h4nb_study.cpp`, write `run_info.txt` (data-model.md section 8): build info, driver and runtime versions, GPU names and compute capabilities, rank count, host and start time.
- [x] T044 [US6] Add `tools/h4nb_pack.sh`. It packs the logs and the results of one or more run directories into one `.tar.gz` archive with `MANIFEST.txt` (Pavlo, 2026-11-07). Document it in README.md and quickstart.md.

---

## Phase 6: User Story 5 – several GPUs on several nodes (Priority: P2)

**Goal**: one run uses 4 to 8 GH200 through MPI, with the j-parallel layout (plan D2, `docs/multi-node-design.md`).

**Prerequisite**: T003 (constitution 2.0.0).

**Independent check**: the same input on 2 GPUs of one node and on 2 nodes gives results within the tolerance of `docs/multi-node-design.md` section 2.3.

- [ ] T029 [US5] In `CMakeLists.txt`, add the option `H4NB_MPI` (default OFF) and an optional `find_package(MPI)`. With OFF, the build has no MPI dependency.
- [ ] T030 [US5] Create `src/mpi_comm.cpp` (built only with `H4NB_MPI=ON`). Wrap the communicator, the rank, the size and the local rank (`MPI_COMM_TYPE_SHARED`). Select the device as in `docs/multi-node-design.md` section 3.3 with `device_offset`.
- [ ] T031 [US5] In `step()` in `src/simulation.cu`, add the four collective phases: `MPI_Allreduce` (MIN) for `Tn`; `MPI_Allgather` of the counts and `MPI_Allgatherv` of the active targets in rank order; `MPI_Alltoallv` of the partial forces; the owner sum in rank order. Keep the device-order sum for the single-process case.
- [ ] T032 [US5] Add the key `mpi_host_staging` (bool, default 0, contracts/run-config.md) to `h4nb_run`. When it is 1, stage the MPI buffers through pinned host memory. Use it when the MPI library is not CUDA-aware.
- [ ] T033 [US5] In `diagnostics()`, compute N²/G potential pairs on each rank. Sum the rank partials on rank 0 in rank order. Gather K, P and L with fixed-order sums.
- [ ] T034 [US5] Add the error path: `MPI_Allreduce` (BOR) of the status bits at each sync point; `MPI_Abort` with a clear message on a CUDA error or a fatal status (pending Q6 of the multi-node design).
- [ ] T035 [US5] In `tools/h4nb_run.cpp`, write all output files on rank 0 only. Gather the snapshots to rank 0. Read the input and the configuration on each rank.
- [ ] T036 [P] [US5] Add a CI job in `.github/workflows/` that compiles with `H4NB_MPI=ON` (compile only; no GPU).

**Checkpoint**: `srun ... h4nb_run config=configs/gh200.cfg ...` runs on several nodes with no change to the keys.

---

## Phase 6b: Configurable dissipation (Pavlo, 2026-11-07)

**Goal**: dissipation is selected by configuration. The default `off` keeps the current results bit for bit.

**Independent check**: a run with `dissipation=off` gives the same files as before. A run with `dissipation=linear_drag drag_tau=10` reports a balance E − E₀ − W_diss near zero.

- [x] T041 Add the enum `Dissipation { Off, LinearDrag }` and the fields `dissipation`, `drag_tau`, `drag_vbg` to `h4nb::Config` in `include/h4nb/h4nb.hpp`. Validate them in the `Simulation` constructor.
- [x] T042 Add `dissipation_term()` to `src/hermite.cuh` (research R7). Call it in `correct_kernel` and in `tests/reference.hpp` through a template parameter, so that `Off` adds no instruction. Add `W_diss` to `Diagnostics` and integrate it for each particle step.
- [x] T043 In `tools/h4nb_run.cpp`, write the `W_diss` column to `energy.dat`. Use E − E₀ − W_diss for the verdict. Print the model and τ in the report header.

---

## Phase 7: Polish and cross-cutting

- [x] T037 [P] Update `specs/001-hermite-nbody-lib/quickstart.md`: config files, presets, `config.used`, the build lines for `89` and `90`, the GH200 Slurm line, and the use of `h4nb_study` in A3.
- [x] T038 [P] Update `README.md`: a config-file example, the presets and `help=1`.
- [x] T039 Update `checklists/requirements.md` for the spec changes of 2026-11-07 (spec.md is already updated).
- [x] T040 Update the detailed plan `docs/superpowers/plans/2026-11-07-h4nb.md`: D1 (config file in the tools), D3 and O7 (MPI in v1), O2 (now done through T017 to T021).

---

## Dependencies and execution order

- **Phase 1**: T001 and T002 have no dependency. T003 needs Pavlo's approval.
- **Phase 2**: T004 → T005 → T006 → T007 → T011 and T012. T008 → T009. T010 is independent. T013 is last.
- **Phase 3**: needs T011. T014 → T015 → T016.
- **Phase 4**: T017 → T018 → T019 → T020 and T021 → T022 → the gated tasks T023 to T026 (each only when its gate is true).
- **Phase 5**: T027 → T028. It can run in parallel with Phase 4.
- **Phase 6**: needs T003 and T018. T029 → T030 → T031 → T033 → T034 → T035. T032 after T031. T036 after T029.
- **Phase 6b**: needs T009 and T011. T041 → T042 → T043. It can run in parallel with Phase 4.
- **Phase 7**: after the phases that it documents.

## Parallel opportunities

- T001, T002 and T010 at the start.
- T012 in parallel with T011 (different files).
- Phase 5 in parallel with Phase 4.
- T036, T037 and T038 in parallel with the late tasks.

## Implementation strategy

1. **MVP**: Phases 1 to 3. Then every run is configurable and the η study gives a measured answer for 1e-8.
2. **Speed**: Phase 4 on the RTX 4070 Ti first, then on GH200. Do the gated tasks only when the profile shows the need.
3. **Scale**: Phase 6 after the amendment. Measure 1, 2, 4 and 8 GH200.
4. **Record**: Phase 5 early, so every measured number has its run record.
