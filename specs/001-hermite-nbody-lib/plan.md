# Implementation Plan: Direct N-body Gravity Integrator (h4nb)

**Branch**: `001-hermite-nbody-lib` | **Date**: 2026-11-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-hermite-nbody-lib/spec.md`. Extra input: the second technical specification (STE) that Pavlo sent on 2026-11-07, and Pavlo's request on the same day: "make it flexible, so that the parameters are configurable".

**Related documents**: the detailed task-by-task plan `docs/superpowers/plans/2026-11-07-h4nb.md` (design decisions D1 to D11, gated optimisations O1 to O9), the multi-node design `docs/multi-node-design.md`, and the constitution `.specify/memory/constitution.md`. This file does not repeat them. It adds the items that the new STE and the configuration request change.

## Summary

h4nb is a C++17/CUDA library for direct N-body simulation. It uses a 4th-order Hermite integrator with Aarseth block time steps in FP64. Particle 0 is the central body. It moves as a full participant. Commit `339ce35` holds the library, the tools and the CPU and GPU tests (plan Tasks 1 to 6).

This plan covers the remaining work. The work has four parts:

1. **Configuration.** All run parameters become configurable from one place, with a fixed precedence: defaults, a config file, environment variables, command-line arguments. Each run writes the final values to `config.used`. Physics presets for the two system types of the STE are added (AGN gas clouds: ε = 0.01; stellar systems: ε = 0.0001).
2. **Speed.** The force pass is the hot path (constitution II). The plan makes the kernel tuning parameters configurable at run time. Then a measurement can select them without a rebuild. The gated optimisations O1 to O4 follow, each with its gate.
3. **Scale.** The MPI path of `docs/multi-node-design.md` (one rank per GPU, j-parallel layout) for 4 to 8 GH200.
4. **Input safety.** The loader checks the input as the STE requires.

## Technical Context

**Language/Version**: C++17 and CUDA C++17. CUDA ≥ 12.0. CMake ≥ 3.24.

**Primary Dependencies**: CUDA toolkit (CUB, Thrust). MPI only as an optional dependency (`H4NB_MPI=ON`), after the constitution amendment to 2.0.0. No other dependency. The config-file parser is about 30 lines in `tools/`. No YAML or INI library is used.

**Storage**: files. Text initial conditions (`id m x y z vx vy vz`), binary snapshots (version 1), `.dat` diagnostic tables, `config.used`.

**Testing**: CTest with the `cpu` and `gpu` labels (constitution 1.1.0). The test suite exists. `tasks.md` adds no test tasks, by request.

**Target Platform**: Linux x86_64 and Linux aarch64 (GH200 has a Grace CPU). NVIDIA GPUs with compute capability ≥ 7.0.

| Configuration | Role | Compute capability | FP64 note |
|---|---|---|---|
| 2 × RTX 4070 Ti | Development and correctness | 8.9 | FP64 is 1/64 of FP32. A 1M run is slow. |
| 4–8 × GH200 | Production | 9.0 | Full FP64 rate. Probably several nodes, so MPI. |

The GPU models are a working assumption. Each tester confirms them with `nvidia-smi` and records them in `docs/results.md`.

**Project Type**: library with thin command-line tools.

**Performance Goals**: the force kernel reaches 40 to 70 % of the FP64 peak of the card for N ≥ 131 072 (plan Task 7, step 1). Two GPUs give a speed-up of 1.8 or more for N ≥ 131 072. One mean period at N = 1 024 000 takes about 16 min on one H100-class GPU (estimate; see research R6).

**Constraints**: max |ΔE/E₀| ≤ 1e-8 over one mean period, shown by a measured run. FP64 only. No fast-math. No floating-point atomics. Bit-identical results for the same input, configuration, device list, rank count and build.

**Scale/Scope**: 128 000 to 1 024 000 particles plus the central body. About 220 bytes of owned state per particle plus about 200 bytes of work buffers per global particle on each GPU (data-model.md). 1M particles need about 0.4 GB per GPU. Memory is not the limit. Compute is the limit.

## Constitution Check

*GATE: checked before Phase 0 and again after Phase 1.*

| Principle | Status | Note |
|---|---|---|
| I. Accuracy is the contract | Pass | The presets set ε. They do not change η to reach 1e-8. The report states the softening value. Dissipation is `off` by default. When it is on, the energy verdict uses the balance E − E₀ − W_diss (research R7). |
| II. Speed by measurement | Pass | Run-time tuning keys (`tile`, `blocks_per_sm`) make the measurement cheap. They add no new arithmetic. O1 to O4 keep their gates. |
| III. Library first, small API | Pass, with one addition | `Config` gets two plain `int` fields (`tile`, `blocks_per_sm`). No CUDA type is exposed. The user asked for configurable parameters, so the need exists. The file parser stays in `tools/`. |
| IV. Deterministic results | Pass | `tile` and `blocks_per_sm` change the reduction tree. Bit-identical results are claimed only for the same values. `config.used` records them. |
| V. Simplicity | Pass | The parser is about 30 lines. No new dependency. |
| Hardware: several nodes | Pass | Constitution 2.0.0 (applied 2026-11-07) allows MPI as an optional dependency. |
| Hardware: compute capability ≥ 7.0 | Pass | The GTX 1060 is removed from the hardware list (user, 2026-11-07). |
| Hardware: x86_64 or aarch64 | Pass | Constitution 2.0.0 adds aarch64 for GH200. |

Re-check after Phase 1: no violation.

## Configuration design (Pavlo's request)

Full contract: [contracts/run-config.md](contracts/run-config.md).

- **One set of keys.** Every parameter of the run has one key name. The same name works in the file, in the environment and on the command line.
- **Precedence.** Later sources win: (1) defaults in `h4nb::Config` and in the tool, (2) `preset=`, (3) the file of `config=<path>`, (4) environment variables `H4NB_<KEY>`, (5) command-line `key=value`.
- **File format.** One `key=value` per line. `#` starts a comment. No sections. This keeps the user decision of 2026-11-07 (key=value format, no INI). The user confirmed the file format on 2026-11-07.
- **Strict.** An unknown key is an error. A bad value is an error. A value out of range is an error. The message names the key and the source.
- **Recorded.** Each run writes `config.used` to the output directory. It holds every key, its final value and its source. The file can be passed back as `config=` to repeat the run.
- **Softening as ε.** The key `eps` is the softening length ε. The tool sets `Config::eps2 = eps * eps`. The key `eps2` stays for the library users. Both keys together are an error.
- **Presets.** `preset=agn` sets `eps=0.01`. `preset=stellar` sets `eps=0.0001`. `preset=none` (default) sets `eps=0`. A preset sets only defaults. A later source can change each key.
- **Units.** The system of units is dimensionless with G = 1. The keys `G` and `period` are configurable. `period` is the reference period for the energy verdict (default: the mean period that the tool computes; the STE reference value is 2π for M = 1, a = 1).
- **Dissipation.** The key `dissipation` selects the model: `off` (default) or `linear_drag` (a = −(v − v_bg)/τ, with `drag_tau`). The model is a per-particle term in the corrector. It adds no pair work. Other models are added as new values of the same key (research R7).
- **Tuning keys.** `tile` (64, 128 or 256 targets per block) and `blocks_per_sm` (1 to 16, default 4) select the launch shape of the force kernel and the potential kernel at run time. The kernels are templates. The three tile sizes are compiled. A run selects one.

## Project Structure

### Documentation (this feature)

```text
specs/001-hermite-nbody-lib/
├── spec.md              # Feature specification (exists)
├── plan.md              # This file
├── research.md          # Phase 0: decisions for the new STE input
├── data-model.md        # Phase 1: entities, device layout, memory
├── quickstart.md        # Acceptance runs (exists; T037 updates it for config files)
├── contracts/
│   ├── public-api.md    # h4nb.hpp contract and the planned additions
│   ├── run-config.md    # all keys, sources, precedence, validation
│   └── file-formats.md  # initial conditions, snapshot, .dat files, config.used
├── checklists/
│   └── requirements.md  # exists
└── tasks.md             # Phase 2: task list (no test tasks)
```

### Source Code (repository root)

```text
include/h4nb/h4nb.hpp     # public API; Config gets tile, blocks_per_sm
src/hermite.cuh           # per-particle math (unchanged by this plan)
src/kernels.cuh, .cu      # kernels become templates over the tile size
src/simulation.cu         # launch shape from Config; MPI collectives behind H4NB_MPI
src/io.cpp                # loader validation (unique id, m > 0, finite values, count)
src/mpi_comm.cpp          # new, only with H4NB_MPI=ON
tools/args.hpp            # replaced by tools/settings.hpp
tools/settings.hpp        # new: key table, sources, precedence, presets, config.used
tools/h4nb_run.cpp        # uses settings.hpp; writes config.used and run_info.txt
tools/h4nb_bench.cpp      # uses settings.hpp; sweeps tile and blocks_per_sm
tools/h4nb_study.cpp      # new: convergence study grid (FR-015); replaces eta_scan.sh
tools/h4nb_mkdisk.cpp     # uses settings.hpp
tools/h4nb_order.cpp      # uses settings.hpp
configs/                  # new: example config files (agn.cfg, stellar.cfg, dev-4070ti.cfg, gh200.cfg)
tests/                    # exists; no change in this plan
```

**Structure Decision**: keep the single-project layout of commit `339ce35`. The library stays in `src/` with one public header. The configuration layer lives in `tools/`, because configuration files belong to the application (plan D1).

## Decisions by the user (2026-11-07)

- Multi-GPU layout: keep split sources (D2). The STE layout with replicated sources is not used.
- Configuration: a file of `key=value` lines. No YAML and no INI.
- Dissipation: a configurable model (`dissipation=off|linear_drag`), default `off` (research R7).
- η: `eta=0.0005` in the example configs. The library default stays 0.01. Each system gets a measured η.
- GTX 1060: removed. RTX 4070 Ti: development and N ≤ 131 072. GH200: 1M runs.
- Constitution 2.0.0: applied.
- Kernel tile size and blocks per SM: run parameters.
- GH200 per node and number of nodes: not known. They come from the launcher and the configuration. The scaling runs use 1, 2, 4 and 8 ranks. Open until the cluster is known.

The spec was updated on 2026-11-07 for these decisions: FR-008, FR-010, FR-019, FR-022, new FR-025 and FR-026, new SC-010, and the Assumptions.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|---|---|---|
| Three compiled tile sizes (template kernels) | Tuning by configuration without a rebuild (Pavlo's request, constitution II) | One compile-time `BI` needs a rebuild for each measurement, and the GPU machine owners may not build. |
| Config sources: file, environment, CLI | Pavlo's request; `docs/multi-node-design.md` 3.1 already specifies it for MPI launches | CLI only: long command lines under `srun` are hard to repeat. |
| MPI (optional) | 4–8 GH200 are probably on several nodes | Single process: cannot use more than one node. |
