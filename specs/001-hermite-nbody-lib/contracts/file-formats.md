# Contract: file formats

## 1. Initial conditions (text)

One particle on each line: `id m x y z vx vy vz`. A line that starts with `#` is a comment. Blank lines are skipped.

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
| `energy.dat` | `time K U E W_diss rel_err max_rel_err mean_rel_err` (`rel_err` uses E − E₀ − W_diss) |
| `momentum.dat` | `time Px Py Pz Lx Ly Lz dP_rel dL_rel` |
| `timesteps.dat` | `time dt_min dt_max dt_mean mean_active_per_block_step r_min` |
| `performance.dat` | `time wall_s block_steps active pairs_per_s` |
| `study.dat` (new) | see data-model.md section 9 |
| `bench.dat` (new) | `N devices tile blocks_per_sm pairs_per_s gflops wall_s` |

## 4. Run record (new)

- `config.used`: `key=value  # source` lines. See run-config.md section 6.
- `run_info.txt`: `key: value` lines. See data-model.md section 8.
