# h4nb

h4nb is a C++17/CUDA library for direct N-body simulation of gravitational systems. It uses the 4th-order Hermite integrator with Aarseth block time steps in FP64. It runs on one or more NVIDIA GPUs. The target is one massive central body that moves, plus 128 000 to 1 024 000 lighter particles.

- [1. The problem](#1-the-problem)
- [2. The approach](#2-the-approach)
- [3. Architecture of the library](#3-architecture-of-the-library)
- [4. Build](#4-build)
- [5. Configuration](#5-configuration)
- [6. Run](#6-run)
- [7. Use the library from C++](#7-use-the-library-from-c)
- [8. Output files](#8-output-files)
- [9. Hardware](#9-hardware)
- [10. Tests and acceptance runs](#10-tests-and-acceptance-runs)
- [11. Documents](#11-documents)

> **Status of this README.** Sections marked **✅ available** describe the code on `main` now. Sections marked **🚧 planned** describe the agreed design in [`specs/001-hermite-nbody-lib/contracts/`](specs/001-hermite-nbody-lib/contracts/). The task numbers (T0xx) point to [`tasks.md`](specs/001-hermite-nbody-lib/tasks.md). When a task is done, its marker changes to ✅.

---

## 1. The problem

A researcher studies a disk or a cluster around one heavy body: for example gas clouds around an active galactic nucleus (AGN), or stars around a central mass. The total mass of the particles can be 10 % to 100 % of the central mass. So the central body is not fixed. It moves in the field of all other particles.

The researcher needs these results:

- **Exact forces.** Every particle pulls on every other particle. No tree or grid approximation is used. One full force pass at N = 1 024 000 is about 10¹² pair interactions.
- **Controlled accuracy.** The maximum relative energy error over one mean orbital period must be **1e-8 or less**. A measured run must show this value. A setting cannot replace the measurement ([constitution](.specify/memory/constitution.md), principle I).
- **Speed.** Long runs of large systems must finish in hours on data-centre GPUs, not in weeks.
- **Reproducible runs.** The same input, configuration, devices and build give the same output, bit for bit.

The full requirements are in [`spec.md`](specs/001-hermite-nbody-lib/spec.md). The original technical specification (in Ukrainian) is in [`docs/superpowers/specs/2026-11-07-h4nb-tz-original.md`](docs/superpowers/specs/2026-11-07-h4nb-tz-original.md).

## 2. The approach

| Topic | Decision | Reason |
|---|---|---|
| Integrator | 4th-order Hermite predictor-corrector ([Makino & Aarseth 1992](https://ui.adsabs.harvard.edu/abs/1992PASJ...44..141M)). Each step: predict, compute the acceleration **a** and the jerk **j** = d**a**/dt, correct. | 4th order with only one force pass per step. The error falls by about 16 when the step is halved. |
| Time steps | Individual steps from the Aarseth criterion with the accuracy parameter η. Each step is a power-of-two fraction of `dt_max` (block steps). | Particles on wide, slow orbits take large steps. Particles in close encounters take small steps. Only the active particles get a new force. |
| Time | Integer ticks (`int64`). `tick = dt_max / 2^max_level`. | Block times are exact. "Is this particle active?" is an integer compare. |
| Prediction | All particles are predicted to the block time before the force pass. Predicted and corrected states are separate buffers. | No force uses an old or half-updated position. |
| Central body | Particle 0. It is a full participant with its own step. | Momentum stays conserved. A fixed centre would break it. `fixed_center=1` exists only for tests. |
| Precision | FP64 for all physical values. No fast-math. No mixed precision. No floating-point atomics. | Accuracy is the contract. Fixed summation order gives bit-identical runs. |
| Softening | Optional Plummer softening ε. Off by default. Presets: ε = 0.01 (AGN gas), ε = 0.0001 (stars). The same ε is used in the force and in the potential energy. | Softening changes the physical model. It is not a tool to hide an energy error. |
| Several GPUs | **Split sources** (j-parallel). Each GPU owns N/G particles. The active targets go to every GPU. Each GPU computes the partial force of its own sources. The owner adds the partials in a fixed order. | With block steps only 10² to 10⁴ particles are active. Split targets would give each GPU too few threads. Split sources give each GPU the same work, and the traffic for each step is only O(N_active). |
| Several nodes 🚧 | One MPI rank per GPU, same j-parallel layout, CUDA-aware MPI ([design](docs/multi-node-design.md)). | The target is 4 to 8 GH200. |
| Diagnostics | Energy, momentum and angular momentum only at sync points (multiples of `dt_max`). Potential on the GPU over unique pairs. Host sums with Neumaier summation. | One energy check costs N²/2 pairs. So it runs at a set interval, not at each step. |
| Accuracy parameter | η is chosen by measurement for each system. The 1e-8 goal needs about **η = 5e-4** (plan decision D11). | The range 0.001–0.02 of the original TZ does not reach 1e-8. |
| Speed work | Each optimisation needs a measured gate: a profile or benchmark shows the need. | On GPUs, guesses about speed are often wrong (constitution, principle II). |

All design decisions with their reasons are in the [detailed plan](docs/superpowers/plans/2026-11-07-h4nb.md) (D1 to D11, O1 to O9) and in [`research.md`](specs/001-hermite-nbody-lib/research.md) (R1 to R8).

## 3. Architecture of the library

### 3.1 Files

```text
include/h4nb/h4nb.hpp     Public API: Particles, Config, Diagnostics, Stats, Simulation, snapshot I/O
src/hermite.cuh           Per-particle math (__host__ __device__): predict, pair force, corrector, Aarseth step, levels
src/kernels.cuh/.cu       CUDA kernels: predict, gather, force, partial sums, correct, potential
src/simulation.cu         Simulation: device buffers, block-step loop, multi-GPU exchange, diagnostics
src/io.cpp                Text initial conditions, binary snapshots
tools/                    Thin command-line clients of the public API (h4nb_run, h4nb_mkdisk, h4nb_bench, h4nb_order)
tests/                    CPU oracle (same math header), CPU and GPU tests
```

The library has **one public header** and **one class**, `Simulation`. The public API exposes no CUDA type. The GPU kernels and the CPU reference in the tests use the same math header `src/hermite.cuh`. So the GPU result is checked against an oracle that runs the same formulas.

### 3.2 One block step

```text
          ┌──────────────────────────────────────────────────────────────┐
          │ 1. Tn = min(next) over all particles (each GPU, then host)   │
          │ 2. Predict all owned particles to Tn         (predict_kernel)│
          │ 3. Select the active particles: next == Tn   (CUB select)    │
          │ 4. All-gather the active targets to every GPU                │
          │ 5. Each GPU: partial a, j of ITS sources on ALL targets      │
          │                                               (force_kernel) │
          │ 6. Send each slice to the owner GPU                          │
          │ 7. Owner: add the partials in device order, correct, choose  │
          │    the new level (Aarseth, power of two)     (correct_kernel)│
          └──────────────────────────────────────────────────────────────┘
```

The force kernel is the hot path. Each thread owns one target and keeps **a**, **j** in registers. A block loads a tile of sources into shared memory, and all threads of the block reuse the tile. Each target has exactly one owner, so no atomic add is needed. The source range is split into chunks so that a launch has about `blocks_per_sm` blocks per SM, also when few targets are active.

### 3.3 Memory

About 220 bytes of owned state per particle and about 200 bytes of work buffers per global particle on each GPU. N = 1 024 000 needs about 0.4 GB per GPU. Compute is the limit, not memory. See [`data-model.md`](specs/001-hermite-nbody-lib/data-model.md).

## 4. Build

You need Linux (x86_64 or aarch64), CUDA 12.0 or newer, CMake 3.24 or newer and an NVIDIA GPU with compute capability 7.0 or higher.

```bash
make build                      # Release build in build/, CMAKE_CUDA_ARCHITECTURES=native
```

`native` works only on a machine that has the GPU. To build for other cards, set the architecture:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=89        # RTX 4070 Ti
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=90        # GH200 / H100
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES="89;90"   # both
cmake --build build -j
```

🚧 MPI build (T029): add `-DH4NB_MPI=ON`. Without this option the build has no MPI dependency.

Never build with `--use_fast_math` or `-ffast-math`. The NaN checks and the accuracy depend on IEEE arithmetic.

## 5. Configuration

### 5.1 ✅ Available now: command-line keys

Each tool reads `key=value` arguments. These keys work in `h4nb_run` today:

| Key | Default | Meaning |
|---|---|---|
| `ic` | required | Initial conditions: text `id m x y z vx vy vz`, or a `.snap` file. |
| `out` | required | Output directory. |
| `t_end` | required | End time. A multiple of `dt_max`. |
| `eta` | 0.01 | Aarseth accuracy parameter. Use about 0.0005 for 1e-8. |
| `eta_init` | 0.01 | First step: `eta_init·|a|/|j|`. |
| `dt_max` | 0.015625 (1/64) | Largest step (level 0). |
| `max_level` | 40 | Finest level: `dt_min = dt_max / 2^max_level`. |
| `eps` | 0 | Plummer softening length ε. |
| `mode` | `block` | `block` (individual steps) or `fixed` (one shared step). |
| `fixed_level` | 0 | Level of all particles in `fixed` mode. |
| `fixed_center` | 0 | 1: particle 0 does not move (tests only). |
| `devices` | `0` | CUDA device list, for example `0,1`. |
| `diag` | `dt_max` | Interval of the energy and momentum records. A multiple of `dt_max`. |
| `snap` | 0 | Snapshot interval. A multiple of `diag`. 0: no snapshots. |
| `r_close` | auto | Close-pair warning radius. Default `0.1·R_rms/N^(1/3)`. 0: off. |

Note: today an unknown key is ignored. Check the spelling of each key. 🚧 T005 makes an unknown key an error.

### 5.2 🚧 Planned: one key table, five sources (T004 to T013)

Every parameter gets one key name. The same name works in a file, in the environment and on the command line. The tools read the sources in this order. A later source replaces an earlier value:

1. Default value.
2. `preset=none|agn|stellar`.
3. `config=<file>`: a file of `key=value` lines.
4. Environment variables `H4NB_<KEY>`, for example `H4NB_ETA=0.0005`.
5. Command-line `key=value`.

Rules:

- An unknown key, a bad value or a value out of range stops the tool with exit code 2. The message names the key, the value and the source (for example `file:run.cfg:7`).
- `t_end`, `diag` and the snapshot times must be multiples of `dt_max`. The tool does not round them.
- Each run writes `<out>/config.used`. It lists every key, its final value and its source. `h4nb_run config=<out>/config.used` repeats the run.
- `<tool> help=1` prints the key table with the defaults and the ranges.

Config file format (no sections, no INI, no YAML):

```text
# configs/agn.cfg
preset=agn                    # eps=0.01
eta=0.0005                    # measured value for 1e-8 (D11)
dt_max=0.015625
diag=0.0625
period=6.283185307179586      # reference period 2*pi for M=1, a=1, G=1
```

New keys in the plan:

| Group | Keys |
|---|---|
| Input | `n` (expected count), `central_id`, `period`, `period_kind` (`mean`, `median`, `mass_weighted`) |
| Physics | `preset`, `G`, `eps`, `eps2`, `dissipation` (`off`, `linear_drag`), `drag_tau`, `drag_vbg` |
| Execution | `tile` (64, 128, 256), `blocks_per_sm` (1 to 16), `device_offset` (MPI), `mpi_host_staging` (MPI) |
| Output | `snap_times`, `energy_tol` (verdict threshold, default 1e-8), `perf` |
| Benchmark | `sizes`, `tiles`, `bpsm`, `fp64_peak` |
| Study | `etas`, `dt_maxes`, `t_ends` |

The full contract with types, defaults and ranges: [`contracts/run-config.md`](specs/001-hermite-nbody-lib/contracts/run-config.md).

### 5.3 How to choose the main values

| Value | Advice |
|---|---|
| `eta` | Measure it for your system with the η study (A3 in the [quickstart](specs/001-hermite-nbody-lib/quickstart.md)). Start near 0.0005. A smaller η costs about 1/√η more steps. |
| `dt_max` | About 1/64 to 1/16 of the shortest orbital period that you care about. |
| `max_level` | Large enough that no particle needs a step below `dt_min`. The warning `dt < dt_min` tells you to raise it. |
| `eps` | 0 for point masses. `preset=agn` or `preset=stellar` for the two model types. State ε in each report. |
| `diag` | Each energy check costs N²/2 pairs. At 1M particles, use `T/16` or larger. |
| `tile`, `blocks_per_sm` 🚧 | Measure with `h4nb_bench tiles=64,128,256 bpsm=2,4,8`. Put the best values in your machine config. |
| GPU count, node count | Set by the launcher (`devices=`, `mpirun -np`, `srun`). The code does not need to know the cluster in advance. |

## 6. Run

### 6.1 ✅ Single process, one or more GPUs

```bash
# Make a disk: 127 999 particles + the central body, disk mass = 10 % of the central mass.
build/h4nb_mkdisk n=127999 frac=0.1 out=disk128k.snap
# The tool prints the mean, median and mass-weighted periods. Use the mean period T.

# Integrate one period on two GPUs. t_end and diag are multiples of dt_max (1/64).
build/h4nb_run ic=disk128k.snap out=run128k t_end=6.3125 diag=0.0625 eta=0.0005 devices=0,1

# Kepler check and 4th-order convergence.
build/h4nb_order e=0.5

# Benchmark.
build/h4nb_bench n=16384,131072,1024000 devices=0,1

# eta study (today a shell script; T015 replaces it with h4nb_study).
DT_MAX="0.015625 0.0078125" tools/eta_scan.sh disk128k.snap 6.3125 0.0625 0,1
```

### 6.2 🚧 With a config file (T011)

```bash
build/h4nb_run config=configs/agn.cfg ic=disk128k.snap out=run128k t_end=6.3125 devices=0,1
H4NB_ETA=0.00025 build/h4nb_run config=configs/agn.cfg ic=disk128k.snap out=run_eta025 t_end=6.3125
build/h4nb_run config=run128k/config.used out=run128k_repeat        # repeat a run exactly
```

### 6.3 🚧 Several nodes with MPI (T029 to T036)

One rank per GPU. The keys stay the same.

```bash
# OpenMPI, 2 nodes with 4 GPUs each
mpirun -np 8 --map-by ppr:4:node --bind-to core \
  build/h4nb_run config=configs/gh200.cfg ic=disk1m.snap out=run1m t_end=6.3125

# Slurm: each task sees one GPU
srun --ntasks-per-node=4 --gpus-per-task=1 --gpu-bind=single:1 \
  build/h4nb_run config=configs/gh200.cfg ic=disk1m.snap out=run1m t_end=6.3125
```

Launch details: [`docs/multi-node-design.md`](docs/multi-node-design.md) section 3.

## 7. Use the library from C++

✅ Available now:

```cpp
#include <cmath>
#include <h4nb/h4nb.hpp>

int main() {
  h4nb::Particles p = h4nb::read_snapshot("disk128k.snap");  // or h4nb::load_text("ic.txt")

  h4nb::Config c;
  c.eta = 5e-4;               // measured for 1e-8
  c.dt_max = 1.0 / 64;
  c.eps2 = 0.01 * 0.01;       // the library takes eps^2; the tools take eps
  c.devices = {0, 1};

  h4nb::Simulation sim(p, c);              // uploads, computes a and j, chooses the first steps
  const h4nb::Diagnostics e0 = sim.diagnostics();
  for (int k = 1; k <= 64; ++k) {
    sim.advance_to(k * 0.0625);            // a multiple of dt_max; all particles are synchronized on return
    const h4nb::Diagnostics e = sim.diagnostics();
    const double rel = std::abs((e.E - e0.E) / e0.E);
    if (sim.status() & h4nb::kNaN) break;  // also kDtUnderflow, kClosePair
  }
  h4nb::write_snapshot("final.snap", sim.state(), sim.time());
}
```

Rules:

- `advance_to(t)` and `diagnostics()` work only at multiples of `dt_max`.
- `diagnostics()` costs N²/2 pair evaluations. Call it at an interval.
- `Simulation` is not copyable. One object owns the GPU buffers.
- 🚧 New `Config` fields: `tile`, `blocks_per_sm` (T008), `dissipation`, `drag_tau`, `drag_vbg` (T041). The defaults give the current results bit for bit. See [`contracts/public-api.md`](specs/001-hermite-nbody-lib/contracts/public-api.md).

## 8. Output files

`h4nb_run` writes these files to `out`:

| File | Columns |
|---|---|
| `energy.dat` | `time K U E rel_err max_rel_err mean_rel_err` |
| `momentum.dat` | `time Px Py Pz Lx Ly Lz dP_rel dL_rel` (changes divided by scales from the initial state) |
| `timesteps.dat` | `time dt_min dt_max dt_mean mean_active_per_block_step r_min` |
| `performance.dat` | `time wall_s block_steps active pairs_per_s` |
| `snap_NNNNNN.snap` | Binary snapshot: header + `id m x y z vx vy vz` arrays |
| `config.used` 🚧 | Final configuration (T007) |
| `run_info.txt` 🚧 | Commit, CUDA, driver, GPUs, ranks, host (T028) |

Formats: [`contracts/file-formats.md`](specs/001-hermite-nbody-lib/contracts/file-formats.md).

## 9. Hardware

| GPU | Use | Note |
|---|---|---|
| RTX 4070 Ti (compute capability 8.9) | Development, correctness runs, N ≤ 131 072 | FP64 is 1/64 of FP32. One 1M orbital period takes about 17 h (estimate). |
| GH200 (9.0) | 1M acceptance and production runs | Full FP64 rate. About 18 min for one 1M period on one GPU (estimate). |
| GPUs below 7.0 (for example GTX 1060) | Not supported | Constitution 2.0.0. |

The estimates are in [`research.md`](specs/001-hermite-nbody-lib/research.md) R6. Measure the real values with `h4nb_bench`. Check your GPUs with `nvidia-smi` and record them in `docs/results.md`.

## 10. Tests and acceptance runs

```bash
make test                         # all tests (the gpu tests need a GPU)
ctest --test-dir build -L cpu     # only the tests that need no GPU
```

- Tests labelled `cpu` run without a GPU. CI runs them on each push ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)). This shows that the code compiles and that the CPU reference is correct. It does not show that the GPU code is correct.
- Tests labelled `gpu` need a CUDA device.
- The acceptance runs A1 to A8 check the physics goals on a GPU machine: [`quickstart.md`](specs/001-hermite-nbody-lib/quickstart.md). Record the results in `docs/results.md` with [`docs/results-template.md`](docs/results-template.md).
- Never loosen a test threshold to make a test pass. A failing test is a finding.

## 11. Documents

| Document | Content |
|---|---|
| [Constitution](.specify/memory/constitution.md) | Project rules. They have priority. |
| [Spec](specs/001-hermite-nbody-lib/spec.md) | Requirements, user stories, success criteria |
| [Plan](specs/001-hermite-nbody-lib/plan.md) | Remaining work: configuration, speed, MPI, input checks; user decisions |
| [Research](specs/001-hermite-nbody-lib/research.md) | Decisions R1 to R8 with reasons and cost estimates |
| [Data model](specs/001-hermite-nbody-lib/data-model.md) | Entities, device buffers, memory |
| [Contracts](specs/001-hermite-nbody-lib/contracts/) | Public API, run configuration, file formats |
| [Tasks](specs/001-hermite-nbody-lib/tasks.md) | Task list T001 to T043 |
| [Quickstart](specs/001-hermite-nbody-lib/quickstart.md) | Acceptance runs |
| [Detailed plan](docs/superpowers/plans/2026-11-07-h4nb.md) | Design decisions D1 to D11, gated optimisations O1 to O9 |
| [Multi-node design](docs/multi-node-design.md) | MPI layout, launch, determinism across ranks |
| [CUDA best practices](docs/cuda-best-practices.md) | Rules for kernels, numerics and errors. Read it before you change code. |

## License

MIT. See [`LICENSE`](LICENSE).
