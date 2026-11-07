# Contract: run configuration of the h4nb tools

Applies to `h4nb_run`, `h4nb_bench`, `h4nb_study`, `h4nb_mkdisk` and `h4nb_order`. Each tool uses the keys that apply to it. A key of another tool is an error for this tool.

## 1. Sources and precedence

The tool reads the sources in this order. A later source replaces the value of an earlier source.

1. Default value (table below).
2. `preset=<name>` (section 4).
3. `config=<path>`: a file of `key=value` lines.
4. Environment variables `H4NB_<KEY>`, with the key in upper case. Example: `H4NB_ETA=0.0005`.
5. Command-line arguments `key=value`.

`config` and `preset` can appear on the command line or in the environment. A config file cannot contain `config=` (no nesting).

## 2. File format

```text
# comment
key=value
key = value        # spaces around '=' are allowed; a trailing comment is allowed
```

- One key on each line. No sections. Blank lines are skipped.
- A list value uses commas: `devices=0,1`.
- A key that appears two times in one file is an error.

## 3. Validation

- An unknown key is an error.
- A value that does not parse is an error.
- A value out of range is an error.
- Each error message names the key, the value and the source (for example `file:run.cfg:7`). The tool exits with code 2.
- Exit codes of `h4nb_run`: 0 = done, 1 = runtime error (for example CUDA or file I/O), 2 = settings or input error, 3 = numerical failure (NaN or Inf).
- Several ranks (MPI build, task T034): all ranks return the same exit code for a settings, input or file error and for a NaN. The ranks agree on the code before they stop. Only one copy of a settings error is printed. A CUDA error, an MPI error or an error on one rank only stops all ranks with `MPI_Abort` and a message that names the rank. `mpirun` then reports the abort code.
- `h4nb_study` and `h4nb_bench` run as one process only. With more than one rank, they print an error and return 2.
- An environment variable for a key that the tool does not declare is ignored, because one environment serves several tools. An unknown key in a file or on the command line is an error.
- A relative path in `config.used` is relative to the working directory of the run, not to the file.
- `t_end`, `diag` and each snapshot time must be multiples of `dt_max`. Otherwise it is an error. The tool does not round them.

## 4. Presets

| Preset | Sets | Use |
|---|---|---|
| `none` (default) | `eps=0` | Point masses (Newtonian gravity). |
| `agn` | `eps=0.01` | Gas and particle clouds in AGN. |
| `stellar` | `eps=0.0001` | Stellar systems. |

A preset sets defaults only. A file, the environment or the command line can change each key after it.

## 5. Keys

### Input and run

| Key | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `ic` | string | — (required) | — | Initial conditions. `.snap` is binary. Other names are text `id m x y z vx vy vz`. |
| `n` | int | 0 | ≥ 0 | Expected particle count, central body included. 0 turns the check off. |
| `central_id` | int | 0 | — | The ID that record 0 must have. |
| `out` | string | — (required) | — | Output directory. |
| `t_end` | real | — (required) | > 0 | End time. |
| `period` | real | 0 | ≥ 0 | Reference orbital period for the energy verdict. 0: the tool computes the mean period from the initial state. The STE reference value is 2π. |
| `period_kind` | enum | `mean` | `mean`, `median`, `mass_weighted` | The estimate used when `period=0`. |

### Physics

| Key | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `preset` | enum | `none` | `none`, `agn`, `stellar` | Section 4. |
| `G` | real | 1 | > 0 | Gravitational constant. |
| `eps` | real | 0 | ≥ 0 | Plummer softening length ε. The library receives ε². |
| `fixed_center` | bool | 0 | 0, 1 | Particle 0 does not move. Tests and comparisons only. |
| `dissipation` | enum | `off` | `off`, `linear_drag` | Dissipation model. With a model on, the verdict uses E − E₀ − W_diss. |
| `drag_tau` | real | 0 | ≥ 0, and > 0 with `linear_drag` | `linear_drag` only. Drag time τ. Required for this model. |
| `drag_vbg` | real list | `0,0,0` | 3 finite values | `linear_drag` only. Background velocity. |

### Integrator

| Key | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `mode` | enum | `block` | `block`, `fixed` | Block steps or one shared step. |
| `eta` | real | 0.01 | > 0 | Aarseth accuracy parameter. 1e-8 needs about 5e-4 (D11). |
| `eta_init` | real | 0.01 | > 0 | First step: `eta_init·|a|/|j|`. |
| `dt_max` | real | 0.015625 | > 0, power of two | Step of level 0. |
| `max_level` | int | 40 | 1 to 50 | `dt_min = dt_max / 2^max_level`. |
| `fixed_level` | int | 0 | 0 to `max_level` | Level of all particles in `fixed` mode. |
| `r_close` | real | −1 | −1 or ≥ 0 | Close-pair radius. −1: `0.1·R_rms/N^(1/3)`. 0: off. |

### Execution

| Key | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `devices` | int list | `0` | valid CUDA IDs | Single process only. Ignored under MPI. |
| `device_offset` | int | 0 | ≥ 0 | MPI only. Added to the local rank to pick the GPU: `(local rank + device_offset) % device count`. With one visible GPU per task, the rank uses device 0. |
| `tile` | int | 128 | 64, 128, 256 | Targets per block in the force and potential kernels. |
| `blocks_per_sm` | int | 4 | 1 to 16 | Target blocks per SM for the source split. |
| `mpi_host_staging` | bool | 0 | 0, 1 | MPI only. Stage the MPI buffers through pinned host memory. Use 1 when the MPI library is not CUDA-aware. Cost: about N × 132 B + 2 × N × 32 B of pinned memory for each rank. |

### Diagnostics and output

| Key | Type | Default | Range | Meaning |
|---|---|---|---|---|
| `diag` | real | `dt_max` | multiple of `dt_max` | Interval of the energy and momentum records. Each record costs N²/2 pairs. |
| `snap` | real | 0 | multiple of `diag` | Snapshot interval. 0 and no `snap_times`: only the final snapshot (`snap_final.snap`). |
| `snap_times` | real list | — | multiples of `diag`, ≤ `t_end` | Explicit snapshot times. Do not set it with `snap` > 0. |
| `energy_tol` | real | 1e-8 | > 0 | Threshold for the pass or fail verdict in the report. It does not change the integration. |
| `perf` | bool | 1 | 0, 1 | Write `performance.dat`. |

### Benchmark and study only

| Key | Tool | Type | Default | Meaning |
|---|---|---|---|---|
| `sizes` | `h4nb_bench` | int list | `16384,131072,1024000` | Particle counts N, central body included. Each value ≥ 2. The old key `n` is not accepted. |
| `tiles` | `h4nb_bench` | int list | `128` | Tile sizes to measure. Each value is 64, 128 or 256. |
| `bpsm` | `h4nb_bench` | int list | `4` | `blocks_per_sm` values to measure. Each value is 1 to 16. |
| `fp64_peak` | `h4nb_bench` | real | 0 | FP64 peak of all devices in TFLOP/s. 0: not set. When > 0, `bench.dat` has the column `pct_peak`. |
| `segments` | `h4nb_bench` | int | 1 | Block-step time after each force pass, in units of `dt_max` = 1/16. The block-step rate is in the output only. 0: no block steps. |
| `seed` | `h4nb_bench` | int | 1 | Seed of the disk initial conditions. |
| `out` | `h4nb_bench` | string | `bench` | Output directory for `bench.dat`, `config.used` and `run_info.txt`. |
| `etas` | `h4nb_study` | real list | `0.002,0.001,0.0005,0.00025` | η grid. |
| `dt_maxes` | `h4nb_study` | real list | `0.015625` | `dt_max` grid. |
| `t_ends` | `h4nb_study` | real list | `period` | Duration grid. |

## 6. Output of the configuration

Each run writes `<out>/config.used`:

```text
# h4nb_run config.used  2026-11-07T16:00:00Z
eta=0.0005            # file:configs/agn.cfg:4
eps=0.01              # preset:agn
devices=0,1           # cli
tile=128              # default
...
```

The file lists every key of the tool. `h4nb_run config=<out>/config.used` repeats the run.

`<tool> help=1` prints the key table with the defaults and the ranges.

## 7. Examples

`configs/agn.cfg`:

```text
preset=agn
eta=0.0005
dt_max=0.015625
diag=0.0625
period=6.283185307179586
```

Run on two development GPUs, with one change on the command line:

```bash
build/h4nb_run config=configs/agn.cfg ic=disk.snap out=run1 t_end=6.3125 devices=0,1
```

Under Slurm (MPI build):

```bash
H4NB_ETA=0.0005 srun --ntasks-per-node=4 --gpus-per-task=1 --gpu-bind=single:1 \
  build/h4nb_run config=configs/gh200.cfg ic=disk1m.snap out=run1m t_end=6.3125
```
