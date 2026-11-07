# Quickstart and acceptance runs: h4nb

The tests in `tests/` (run with `ctest`) check the code. The acceptance runs below check the physics goals. Do each acceptance run on a GPU machine (Linux, CUDA 12.0 or newer, CMake 3.24 or newer). Record each result in `docs/results.md` before a release.

Markers: **✅** works on `main` now. **🚧** needs the task in brackets from [tasks.md](tasks.md). Until then, use the ✅ form of the same step.

## Which machine for which run

| Machine | Runs |
|---|---|
| RTX 4070 Ti (compute capability 8.9) | A1, A2, A3 and A4 at 128k, A6, A7, A8 up to 131 072, A10 |
| GH200 (9.0) | A5 (1M), A8 at 1M, A9 (several nodes), A10 |

GPUs below compute capability 7.0 are not supported (constitution 2.0.0). The number of GH200 per node and the number of nodes come from the launcher. The scaling runs use 1, 2, 4 and 8 GPUs, as far as the cluster allows.

## Before you start

1. Check the machine. Run `nvidia-smi` (driver and GPU list). Run `nvcc --version` (CUDA 12.0 or newer).
2. Copy the results template: `cp docs/results-template.md docs/results.md`. Fill in section 1 (hardware).
3. 🚧 (T001) Select the config file for the machine: `configs/dev-4070ti.cfg` or `configs/gh200.cfg`. Add `preset=agn` (ε = 0.01) or `preset=stellar` (ε = 0.0001) for the model type. Each run writes `config.used`. Copy it into `docs/results.md`.
4. Use the **mean** orbital period from `h4nb_mkdisk` as the acceptance period. The TZ (section 1) asks for the characteristic mean period. This is the default until the project owner decides otherwise. If the decision changes, change this step. Write the period that you used in `docs/results.md`.

## Build

```bash
make build            # cmake Release build in build/
```

`make build` uses `CMAKE_CUDA_ARCHITECTURES=native`. This works only if the build machine has the GPU. To build for a different card, configure the build by hand. Example: `cmake -S . -B build -DCMAKE_CUDA_ARCHITECTURES=80`. Use 70 for V100, 80 for A100, 86 for RTX 30xx, 89 for RTX 40xx (RTX 4070 Ti) and 90 for H100 and GH200. Use `"89;90"` for both. Then run `cmake --build build -j`. Write the value in `docs/results.md`.

✅ (T029) For several nodes, add `-DH4NB_MPI=ON`. The machine needs an MPI library (example: `openmpi-bin` and `libopenmpi-dev`). Use `mpi_host_staging=1` when the MPI library is not CUDA-aware. The MPI path is compiled and its error paths ran without a GPU. A9 is the first GPU run of this path.

Tools: `build/h4nb_run`, `build/h4nb_mkdisk`, `build/h4nb_bench`, `build/h4nb_order`.

## Acceptance runs

| # | Run | Command | Pass criterion | Spec |
|---|-----|---------|----------------|------|
| A1 | Kepler orbit and 4th order | `build/h4nb_order e=0.1` and `e=0.5` | The last line is `PASS`. The position error is small. The ratio is 16 ± 2. | SC-003, SC-004, US1 |
| A2 | Three bodies, conservation | `build/h4nb_run ic=<3-body file> out=run3 t_end=10 diag=0.25` | `dP_rel` and `dL_rel` in `momentum.dat` stay below the tolerance in `docs/results.md`. | SC-005, US1 |
| A3 | η and step study, 128k disk | First: `build/h4nb_mkdisk n=127999 frac=0.1 out=disk.snap`. Then: ✅ `build/h4nb_study ic=disk.snap out=study etas=0.002,0.001,0.0005,0.00025 dt_maxes=0.015625,0.0078125 t_ends=<T> diag=<T/64> devices=0,1` | Read `study.dat`, or the last line of the output. Find the largest η with `pass=1` (max_rel_err of 1e-8 or less). Repeat with `frac=0.5` and `frac=1.0`. | SC-001, FR-015, US2, US3 |
| A4 | Long run and drift | `build/h4nb_run ic=disk.snap out=run128k t_end=<10 T> diag=<T/16> eta=<from A3>` | Record `max_rel_err` for each period from `energy.dat`. Report if the drift is linear. | US2 |
| A5 | 1M disk | `build/h4nb_mkdisk n=1023999 frac=0.5 out=disk1m.snap`, then `build/h4nb_run ic=disk1m.snap out=run1m t_end=<T> diag=<T/16> eta=<from A3> devices=<all>` | The run ends without NaN. Record the maximum relative energy error and the wall time. | SC-002, US4 |
| A6 | 1 GPU and 2 GPUs | Run the A3 settings for a small disk (`n=2047`) with `devices=0` and with `devices=0,1`. Compare `energy.dat` and `momentum.dat`. | The results agree within the numerical error. For large N, the step time becomes shorter with more GPUs. | SC-006, US5 |
| A7 | Reproducibility | Run the same command two times into two directories. Use `cmp` on each `.dat` and `.snap` file. | All files are identical. | SC-007, US6 |
| A8 | Benchmark | `build/h4nb_bench sizes=16384,131072,1024000 devices=0 out=bench1`, then run it with all GPUs (example: `devices=0,1 out=bench2`). | The table and `bench.dat` have at least three sizes. | SC-009, FR-024 |
| A9 | Several nodes (T029–T036; MPI build) | `srun --ntasks-per-node=<GPUs per node> --gpus-per-task=1 --gpu-bind=single:1 build/h4nb_run config=configs/gh200.cfg ic=disk1m.snap out=run_<ranks> t_end=<T> diag=<T/16>`. Run with 1, 2, 4 and 8 ranks, and with 2 ranks on one node and on two nodes. First check on one node with 2 GPUs: `mpirun -np 2 build/h4nb_run ic=disk.snap out=mpi2 t_end=<T> diag=<T/16>` and `build/h4nb_run ic=disk.snap out=dev2 t_end=<T> diag=<T/16> devices=0,1`. Compare the snapshots, `energy.dat`, `momentum.dat`, `energy_periods.dat` and `timesteps.dat` with `cmp`. Repeat the `mpirun` run with `mpi_host_staging=1`. | `mpi2` and `dev2` give the same snapshots and the same `.dat` files that the step above compares (expected, `docs/multi-node-design.md` section 2.2; record the first difference if not). `mpi_host_staging=1` gives the same files as 0. Two nodes agree with one node within the tolerance of section 2.3. The time per step falls with more ranks. `run_info.txt` has `ranks:` and one `rank_<r>` line for each rank. Record the MPI stack. | SC-006, SC-010, US5 |
| A10 | Kernel tuning (T019–T021) | `build/h4nb_bench sizes=131072,1024000 tiles=64,128,256 bpsm=2,4,8 devices=0 fp64_peak=<TFLOP/s> segments=0 out=tune` | `tune/bench.dat` has one row for each combination and the column `pct_peak`. The last lines of the output give the best combination for each N. Write the best `tile` and `blocks_per_sm` into the machine config. | FR-025 |

`<T>` is the agreed mean orbital period from `h4nb_mkdisk`. For the dimensionless units (G = 1, central mass 1, radius 1), the reference Kepler period is 2π ≈ 6.2832. Rounded up to a multiple of 1/64, this is 6.296875. With `diag=<T/16>`, choose `t_end` and `diag` so that `diag` divides `t_end` (example: `t_end=6.3125 diag=0.0625`). Round it up to a multiple of `dt_max` (default 1/64). `diag` and `t_end` must be multiples of `dt_max`.

## Send the results back

Do these steps for each acceptance run:

1. Create the output directory before the run: `mkdir -p run128k`.
2. Save the screen output in it: add `2>&1 | tee run128k/stdout.log` to the command.
3. After the runs, pack all directories into one archive: `make pack RUN="run3 study run128k run1m"` (or `tools/h4nb_pack.sh run3 study run128k run1m`).
4. Send the archive `h4nb_logs_<host>_<UTC time>.tar.gz`.

The archive contains `config.used`, `run_info.txt` (commit, CUDA versions, GPUs), all `.dat` files, the logs, the Nsight profiles, the Slurm logs and `MANIFEST.txt` with the `nvidia-smi` output. Snapshots are not in it. Add `--snap` when you also need them, for example for A7.

## Without a GPU

CI compiles the library and the tools. CI runs the CPU tests (`ctest -L cpu`) and `h4nb_mkdisk`. This shows that the code compiles. It does not show that the code is correct.
