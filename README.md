# h4nb

h4nb is a direct N-body library for CUDA. It uses the 4th-order Hermite integrator, Aarseth block time steps and FP64. It runs on one or more NVIDIA GPUs. The target is one moving central body and 128k to 1024k lighter particles.

## Contents

- Public API: `include/h4nb/h4nb.hpp` (`Config`, `Simulation`, snapshot I/O).
- Tools:
  - `h4nb_run` runs a simulation. It writes `energy.dat`, `momentum.dat`, `timesteps.dat`, `performance.dat` and snapshots.
  - `h4nb_mkdisk` makes disk initial conditions and prints period estimates.
  - `h4nb_bench` measures the speed.
  - `h4nb_order` checks the Kepler orbit and the 4th order of the method.
  - `tools/eta_scan.sh` studies the effect of η and `dt_max`.
- Tests: `tests/`. Tests with the label `cpu` run without a GPU. Tests with the label `gpu` need a CUDA device.

## Documents

- Spec: `specs/001-hermite-nbody-lib/spec.md`.
- Acceptance runs: `specs/001-hermite-nbody-lib/quickstart.md`.
- Plan: `docs/superpowers/plans/2026-11-07-h4nb.md`.
- Project rules: `.specify/memory/constitution.md`.
- Code rules: `docs/cuda-best-practices.md`.
- Results template: `docs/results-template.md`.

## Build

You need Linux, CUDA 12.0 or newer, and CMake 3.24 or newer.

```bash
make build
```

The build never uses fast-math. The measured runs in the quickstart show the 1e-8 energy goal. A setting cannot replace the measurement.

## Test

```bash
make test                       # build, then run all tests (the gpu tests need a GPU)
ctest --test-dir build -L cpu   # run only the tests that need no GPU
```

## Run

```bash
build/h4nb_mkdisk n=127999 frac=0.1 out=disk.snap     # prints mean, median and mass-weighted periods
build/h4nb_run ic=disk.snap out=run t_end=6.25 diag=0.1 eta=0.0005 devices=0,1
```

`t_end`, `diag` and `snap` must be multiples of `dt_max` (default 1/64).

## License

h4nb uses the MIT license. See the file `LICENSE`.
