# Contract: file formats

## 1. Initial conditions (text)

One particle on each line: `id m x y z vx vy vz`. A line that starts with `#` is a comment. A `#` after the eight fields starts a comment to the end of the line. Other extra text on a line is an error. Blank lines are skipped.

- The first record is the central body. It has the ID `central_id` (default 0) and its own mass, position and velocity. The program does not add a central body.
- N counts all records, the central body included.
- IDs are unique integers. They need not be consecutive.
- Masses are positive. All values are finite.
- The units are dimensionless. G is set by the key `G` (default 1). With M_central = 1 and a = 1, the Kepler period is 2π.

Example (structure only, not a prepared test set):

```text
0 1.0    0.0  0.0 0.0  0.0  0.0 0.0
1 0.001  1.0  0.0 0.0  0.0  1.0 0.0
2 0.001  0.0  1.0 0.0 -1.0  0.0 0.0
```

## 2. Snapshot (binary, version 1)

Header of 32 bytes: `magic[8] = "H4NBSNAP"`, `uint32 version = 1`, `uint32 reserved`, `uint64 n`, `double time`. Then eight arrays of n values each, in this order: `id` (int64), `m`, `x`, `y`, `z`, `vx`, `vy`, `vz` (double). Little-endian. A reader can read one array without the others (FR-020, partial reading).

## 3. Diagnostic tables

All tables are text with one header line that starts with `#`.

| File | Columns |
|---|---|
| `energy.dat` | `time K U E rel_err max_rel_err mean_rel_err W_diss`. `rel_err` = \|E − E₀ − W_diss\| / D. D is \|E₀\| with `energy_norm=e0` (default). D is \|K₀\| + \|U₀\| with `energy_norm=ku`. `max_rel_err` and `mean_rel_err` use the same D. W_diss is the last column, so the columns 1 to 7 of older files do not move. |
| `momentum.dat` | `time Px Py Pz Lx Ly Lz dP_rel dL_rel` |
| `timesteps.dat` | `time dt_min dt_max dt_mean mean_active_per_block_step r_min` |
| `performance.dat` | `time wall_s block_steps active pairs_per_s` |
| `energy_periods.dat` (new) | `period t_start t_end max_rel_err mean_rel_err complete`. The errors use the same D as `energy.dat`. One row for each reference period k that the run touches. The row uses the diag points with time in ((k−1)T, kT]. `complete` is 1 when the run reached kT, else 0. A period with no diag point has `nan` in `max_rel_err` and `mean_rel_err`. |
| `study.dat` (new) | see data-model.md section 9 |
| `bench.dat` (new) | `N devices tile blocks_per_sm pairs_per_s gflops wall_s init_force_s init_levels_s`, then `pct_peak` when `fp64_peak` > 0. `devices` is the number of device IDs. The first header line gives the device IDs. `pairs_per_s` and `gflops` (60 × `pairs_per_s` / 1e9, research.md R6) use `init_force_s`: the first force pass, with its sync. `init_levels_s` is the initial levels. `wall_s` is the time of the whole constructor. |

## 4. Run record (new)

- `config.used`: `key=value  # source` lines. See run-config.md section 6.
- `run_info.txt`: `key: value` lines. See data-model.md section 8.
- Log archive: `tools/h4nb_pack.sh RUN_DIR...` writes `h4nb_logs_<host>_<UTC time>.tar.gz`. It contains one top directory with one subdirectory for each RUN_DIR, `slurm/` for Slurm logs, and `MANIFEST.txt` (host, time, `nvidia-smi` output, file sizes, sha256 sums). Snapshots are in it only with `--snap`.

## 4. Files after an MPI error

When an MPI run stops because of an error on a rank other than rank 0, the records of rank 0 stay in the `*.dat.tmp` files. Rank 0 does not rename them to `*.dat`.
