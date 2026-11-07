# Quickstart and acceptance runs: h4nb

The tests in `tests/` (run with `ctest`) check the code. The acceptance runs below check the physics goals. Do each acceptance run on a GPU machine (Linux, CUDA 12.0 or newer, CMake 3.24 or newer). Record each result in `docs/results.md` before a release.

## Before you start

1. Check the machine. Run `nvidia-smi` (driver and GPU list). Run `nvcc --version` (CUDA 12.0 or newer).
2. Copy the results template: `cp docs/results-template.md docs/results.md`. Fill in section 1 (hardware).
3. Use the **mean** orbital period from `h4nb_mkdisk` as the acceptance period. The TZ (section 1) asks for the characteristic mean period. This is the default until the project owner decides otherwise. If the decision changes, change this step. Write the period that you used in `docs/results.md`.

## Build

```bash
make build            # cmake Release build in build/
```

`make build` uses `CMAKE_CUDA_ARCHITECTURES=native`. This works only if the build machine has the GPU. To build for a different card, configure the build by hand. Example: `cmake -S . -B build -DCMAKE_CUDA_ARCHITECTURES=80`. Use 70 for V100, 80 for A100, 86 for RTX 30xx, 89 for RTX 40xx and 90 for H100. Then run `cmake --build build -j`. Write the value in `docs/results.md`.

Tools: `build/h4nb_run`, `build/h4nb_mkdisk`, `build/h4nb_bench`, `build/h4nb_order`.

## Acceptance runs

| # | Run | Command | Pass criterion | Spec |
|---|-----|---------|----------------|------|
| A1 | Kepler orbit and 4th order | `build/h4nb_order e=0.1` and `e=0.5` | The last line is `PASS`. The position error is small. The ratio is 16 ± 2. | SC-003, SC-004, US1 |
| A2 | Three bodies, conservation | `build/h4nb_run ic=<3-body file> out=run3 t_end=10 diag=0.25` | `dP_rel` and `dL_rel` in `momentum.dat` stay below the tolerance in `docs/results.md`. | SC-005, US1 |
| A3 | η and step study, 128k disk | First: `build/h4nb_mkdisk n=127999 frac=0.1 out=disk.snap`. Then: `DT_MAX="0.015625 0.0078125" tools/eta_scan.sh disk.snap <T> <T/64> 0,1` | Find the largest η with max_dE_E of 1e-8 or less. Repeat with `frac=0.5` and `frac=1.0`. | SC-001, FR-015, US2, US3 |
| A4 | Long run and drift | `build/h4nb_run ic=disk.snap out=run128k t_end=<10 T> diag=<T/16> eta=<from A3>` | Record `max_rel_err` for each period from `energy.dat`. Report if the drift is linear. | US2 |
| A5 | 1M disk | `build/h4nb_mkdisk n=1023999 frac=0.5 out=disk1m.snap`, then `build/h4nb_run ic=disk1m.snap out=run1m t_end=<T> diag=<T/16> eta=<from A3> devices=<all>` | The run ends without NaN. Record the maximum relative energy error and the wall time. | SC-002, US4 |
| A6 | 1 GPU and 2 GPUs | Run the A3 settings for a small disk (`n=2047`) with `devices=0` and with `devices=0,1`. Compare `energy.dat` and `momentum.dat`. | The results agree within the numerical error. For large N, the step time becomes shorter with more GPUs. | SC-006, US5 |
| A7 | Reproducibility | Run the same command two times into two directories. Use `cmp` on each `.dat` and `.snap` file. | All files are identical. | SC-007, US6 |
| A8 | Benchmark | `build/h4nb_bench n=16384,131072,1024000 devices=0`, then run it with all GPUs. | The table has at least three sizes. | SC-009, FR-024 |

`<T>` is the agreed mean orbital period from `h4nb_mkdisk`. Round it up to a multiple of `dt_max` (default 1/64). `diag` and `t_end` must be multiples of `dt_max`.

## Without a GPU

CI compiles the library and the tools. CI runs the CPU tests (`ctest -L cpu`) and `h4nb_mkdisk`. This shows that the code compiles. It does not show that the code is correct.
