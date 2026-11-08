# Contract: Prometheus metrics of h4nb-metrics

All metrics have the label `run` (see spec.md, Key Entities). A gauge has the value of the last complete line of its table. "Segment" is one `diag` interval: one line of `performance.dat` and `timesteps.dat`.

A metric is not exposed for a run when its source does not exist. Example: no `performance.dat` (`perf=0`) gives no performance metrics.

Each metric has a reason. The reason says which question of the user the metric answers.

## 0. Metric table (single source of truth)

This table lists every exposed metric. Sections 1 to 8 give the reason and the rule for each metric. A name that is not in this table is not exposed.

Rules for this table:

- The name column is the name that Prometheus stores. A counter ends with `_total`.
- The `run` label is on every metric of a run. Exporter metrics have no `run` label, except `h4nb_exporter_read_errors_total`.
- A live series (from the exporter) has no `origin` label.
- A backfilled series (from `h4nb-metrics backfill`) has the label `origin="backfill"`.
- The prototype (`tools/h4nb-metrics/src/h4nb_metrics/metrics.py`) defines the same names. It writes the counter names without `_total`. The client library adds the suffix.

| Metric | Type | Labels (besides `run`) | Unit | Source file (column or field) |
|---|---|---|---|---|
| `h4nb_run_info` | gauge, value 1 | `host`, `commit`, `build_type`, `gpu`, `ranks`, `mpi`, `start_utc`, `preset` | - | `run_info.txt`; `config.used` (`preset`) |
| `h4nb_run_state` | gauge | - | enum (section 5) | file names and last time, section 5 |
| `h4nb_sim_time` | gauge | - | sim time | `energy.dat` `time` (last line) |
| `h4nb_t_end` | gauge | - | sim time | `config.used` `t_end` |
| `h4nb_progress_ratio` | gauge | - | 1 (0 to 1) | derived: `h4nb_sim_time` / `h4nb_t_end` |
| `h4nb_wall_seconds_total` | counter | - | s | `performance.dat` `wall_s` (sum) |
| `h4nb_eta_seconds` | gauge | - | s | derived, section 6 |
| `h4nb_last_update_age_seconds` | gauge | - | s | modification time of the `.dat` files |
| `h4nb_run_start_timestamp_seconds` | gauge | - | Unix s | `run_info.txt` `start_utc` |
| `h4nb_run_end_timestamp_seconds` | gauge | - | Unix s | live: modification time of `energy.dat`; backfill: time stamp of its last line (section 8) |
| `h4nb_particles` | gauge | - | count | `config.used` `n`, else snapshot header (section 1) |
| `h4nb_config_value` | gauge | `key` | key unit | `config.used` (numeric keys only) |
| `h4nb_energy_rel_err` | gauge | - | 1 | `energy.dat` `rel_err` |
| `h4nb_energy_max_rel_err` | gauge | - | 1 | `energy.dat` `max_rel_err` |
| `h4nb_energy_mean_rel_err` | gauge | - | 1 | `energy.dat` `mean_rel_err` |
| `h4nb_energy_total` | gauge | - | energy | `energy.dat` `E` |
| `h4nb_dissipated_work` | gauge | - | energy | `energy.dat` `W_diss` |
| `h4nb_momentum_rel_change` | gauge | - | 1 | `momentum.dat` `dP_rel` |
| `h4nb_angular_momentum_rel_change` | gauge | - | 1 | `momentum.dat` `dL_rel` |
| `h4nb_period_max_rel_err` | gauge | `period` | 1 | `energy_periods.dat` `max_rel_err` (written at the end of the run) |
| `h4nb_dt_min` | gauge | - | sim time | `timesteps.dat` `dt_min` |
| `h4nb_dt_mean` | gauge | - | sim time | `timesteps.dat` `dt_mean` |
| `h4nb_dt_max` | gauge | - | sim time | `timesteps.dat` `dt_max` |
| `h4nb_active_per_block_step` | gauge | - | count | `timesteps.dat` `mean_active_per_block_step` |
| `h4nb_r_min` | gauge | - | length | `timesteps.dat` `r_min` |
| `h4nb_block_steps_total` | counter | - | count | `performance.dat` `block_steps` (sum) |
| `h4nb_active_updates_total` | counter | - | count | `performance.dat` `active` (sum) |
| `h4nb_pairs_per_second` | gauge | - | 1/s | `performance.dat` `pairs_per_s` (last segment) |
| `h4nb_gflops` | gauge | - | GFLOP/s | derived: 60 × `pairs_per_s` / 1e9 |
| `h4nb_particle_updates_per_second` | gauge | - | 1/s | derived: `active` / `wall_s` (last segment) |
| `h4nb_segment_wall_seconds` | gauge | - | s | `performance.dat` `wall_s` (last segment) |
| `h4nb_exporter_runs` | gauge | - | count | exporter: number of runs found |
| `h4nb_exporter_read_errors_total` | counter | `run` | count | exporter: read errors per run (FR-013) |
| `h4nb_exporter_scrape_seconds` | gauge | - | s | exporter: time of the last collection |

The table has 34 metrics. The set of names equals the names in the prototype (`metrics.py`, with `_total` added to the counters). The test `test_exposes_contract_metrics` in `tools/h4nb-metrics/tests/test_exporter.py` checks that the exporter exposes each name of `metrics.py`. It does not read this table. A change to this table needs the same change in `metrics.py`.

## 1. Run status

| Metric | Type | Unit | Source | Reason |
|---|---|---|---|---|
| `h4nb_run_info` | gauge, value 1 | - | `run_info.txt`: labels `host`, `commit`, `build_type`, `gpu` (name of `device_0` or `rank_0`), `ranks`, `mpi`, `start_utc`; `config.used`: label `preset` | Which code, which machine and which GPU made this run. Needed to compare runs and to find a run that used a dirty build. |
| `h4nb_run_state` | gauge | enum | file names and times, see section 5 | Is the run alive? Shows a stop or a hang before the Slurm time limit wastes GPU hours. |
| `h4nb_sim_time` | gauge | sim time | `energy.dat` `time` | How far the run is. |
| `h4nb_t_end` | gauge | sim time | `config.used` `t_end` | The target of the run. Gives the scale for the progress. |
| `h4nb_progress_ratio` | gauge | 0 to 1 | `h4nb_sim_time / h4nb_t_end` | Progress in one number. |
| `h4nb_wall_seconds_total` | counter | s | sum of `performance.dat` `wall_s` | Time used by the integration. With the progress it gives the total cost in GPU hours. |
| `h4nb_eta_seconds` | gauge | s | section 6 | When the run will end. Needed to plan the next job and to check the Slurm time limit. |
| `h4nb_last_update_age_seconds` | gauge | s | now minus the newest modification time of the `.dat` files | How long ago the run wrote data. A value much larger than the segment wall time means a hang. |
| `h4nb_particles` | gauge | count | spec.md FR-008 | The size N of the system. Needed to read the speed numbers and to compare runs. |
| `h4nb_config_value` | gauge | key unit | each numeric key of `config.used`; label `key` | The run settings that change the accuracy and the cost: `eta`, `eps`, `dt_max`, `diag`, `energy_tol`, `G`, `tile`, `blocks_per_sm`. Needed to explain a difference between two runs. |

## 2. Accuracy

| Metric | Type | Unit | Source | Reason |
|---|---|---|---|---|
| `h4nb_energy_rel_err` | gauge | 1 | `energy.dat` `rel_err` | The main accuracy result: \|E − E₀ − W_diss\| / D. The project goal is ≤ 1e-8 over one period (spec 001, User Story 2). |
| `h4nb_energy_max_rel_err` | gauge | 1 | `energy.dat` `max_rel_err` | The largest error since t = 0. A scrape can miss a short peak of `rel_err`. This value does not miss it. |
| `h4nb_energy_mean_rel_err` | gauge | 1 | `energy.dat` `mean_rel_err` | Shows a slow drift. A mean that grows linearly means a systematic error, not noise. |
| `h4nb_energy_total` | gauge | energy | `energy.dat` `E` | The raw total energy, to check the sign and the scale of D. |
| `h4nb_dissipated_work` | gauge | energy | `energy.dat` `W_diss` | The work of the drag force. The energy balance needs it. It is 0 with `dissipation=off`. |
| `h4nb_momentum_rel_change` | gauge | 1 | `momentum.dat` `dP_rel` | Momentum must stay constant. Growth means a force asymmetry, for example a bug in the multi-GPU sum. |
| `h4nb_angular_momentum_rel_change` | gauge | 1 | `momentum.dat` `dL_rel` | Angular momentum must stay constant. Growth means an orbit integration error. |
| `h4nb_period_max_rel_err` | gauge | 1 | `energy_periods.dat` `max_rel_err`; label `period` | The acceptance number per reference period. `h4nb_run` writes this file only at the end of the run. |

## 3. Time steps

| Metric | Type | Unit | Source | Reason |
|---|---|---|---|---|
| `h4nb_dt_min` | gauge | sim time | `timesteps.dat` `dt_min` | The smallest block step. A fast fall means a close encounter. It also sets the cost of the run. |
| `h4nb_dt_mean` | gauge | sim time | `timesteps.dat` `dt_mean` | The typical step. With `dt_min` it shows how wide the block hierarchy is. |
| `h4nb_dt_max` | gauge | sim time | `timesteps.dat` `dt_max` | The largest step in use. Compare it with the `dt_max` key. |
| `h4nb_active_per_block_step` | gauge | count | `timesteps.dat` `mean_active_per_block_step` | The number of i-particles per kernel launch. A small number does not fill the GPU and explains a low pair rate. |
| `h4nb_r_min` | gauge | length | `timesteps.dat` `r_min` | The minimum pair distance. Compare with `eps` and `r_close`. A very small value explains a small `dt_min`. |

## 4. Performance

| Metric | Type | Unit | Source | Reason |
|---|---|---|---|---|
| `h4nb_block_steps_total` | counter | count | sum of `performance.dat` `block_steps` | The work done. `rate()` gives block steps per second. |
| `h4nb_active_updates_total` | counter | count | sum of `performance.dat` `active` | The number of particle updates. `rate()` gives particle updates per second. |
| `h4nb_pairs_per_second` | gauge | 1/s | `performance.dat` `pairs_per_s` of the last segment | The main speed number. Compare it with `bench.dat` of the same N and GPU. |
| `h4nb_gflops` | gauge | GFLOP/s | 60 × `pairs_per_s` / 1e9 (research.md R6) | The speed in the unit of the GPU data sheet. Compare it with the FP64 peak. |
| `h4nb_particle_updates_per_second` | gauge | 1/s | `active` / `wall_s` of the last segment | The speed that does not depend on N. It shows the effect of small blocks. |
| `h4nb_segment_wall_seconds` | gauge | s | `performance.dat` `wall_s` of the last segment | The wall time of one `diag` interval. Gives the expected update interval of the files. |

## 5. Run state values

| Value | Name | Condition |
|---|---|---|
| 0 | running | `energy.dat.tmp` exists, and `h4nb_last_update_age_seconds` ≤ `stale_after`. |
| 1 | finished | `energy.dat` exists, and the last `time` ≥ `t_end` × (1 − 1e-12). |
| 2 | stopped early | `energy.dat` exists, and the last `time` < `t_end`. `h4nb_run` stopped with an error (exit code 1, 2 or 3). Read the screen output of the run. |
| 3 | stalled | `energy.dat.tmp` exists, and `h4nb_last_update_age_seconds` > `stale_after`. The process hangs, was killed, or an MPI rank failed. |

`stale_after` = max(`stale_min` (default 300 s), 5 × the largest `wall_s` of the last 10 segments). Reason: the segment time of a large run can be many minutes. A fixed limit would report a slow run as stalled.

## 6. Time to the end

`h4nb_eta_seconds` = (`t_end` − `time`) / v. v is the simulation time per wall second over the last 10 segments of `performance.dat`: (sum of the segment lengths in sim time) / (sum of `wall_s`). Reason: the step size changes during a run. The last segments give a better estimate than the mean over the whole run. With fewer than 2 segments, the metric is not exposed. For a run in state 1 or 2, the value is 0. For a run in state 3, the metric is not exposed, because the run does not progress.

## 7. Exporter metrics

| Metric | Type | Reason |
|---|---|---|
| `h4nb_exporter_runs` | gauge | The number of runs found. Shows a wrong path at once. |
| `h4nb_exporter_read_errors_total` | counter, label `run` | Files that could not be read or lines that could not be parsed. |
| `h4nb_exporter_scrape_seconds` | gauge | The time of the last scrape. Checks SC-003. |

## 8. Backfill (`h4nb-metrics backfill`)

The backfill writes the OpenMetrics text format with a time stamp on each sample. `promtool tsdb create-blocks-from openmetrics` reads this format.

- Each sample has the label `origin="backfill"` (spec.md FR-017).
- The metrics of sections 1 to 4 get one sample for each line of their source table. Metrics from `config.used` and `run_info.txt` get one sample at each time stamp of `energy.dat`, so that a range query finds them. The counters (`*_total`) are the sums up to the line. `h4nb_eta_seconds` and `h4nb_last_update_age_seconds` are not written: they have no meaning after the run.
- `h4nb_run_state` gets the value 0 at all time stamps except the last. The last sample gets the final state of section 5. A run with only `*.dat.tmp` files gets 3.
- Two more gauges, one sample at each time stamp of `energy.dat`:

| Metric | Unit | Reason |
|---|---|---|
| `h4nb_run_start_timestamp_seconds` | Unix s | The start of the run. The run list of "h4nb past runs" uses it to open the time range of the run. |
| `h4nb_run_end_timestamp_seconds` | Unix s | The time stamp of the last line. |

The live exporter also exposes these two gauges. For a live run, `h4nb_run_end_timestamp_seconds` is the modification time of `energy.dat`. It is not the time stamp of its last line. Section 0 lists the source of each metric.

Live series have no `origin` label. Backfilled series always have `origin="backfill"`. A query that must select one kind of series uses the label: `origin!="backfill"` selects live series, and `origin="backfill"` selects backfilled series.

### Backfill time stamps

The time stamp of a line with simulation time t is `start_utc` + (sum of `wall_s` of the `performance.dat` lines with time ≤ t). The line with t = 0 gets `start_utc`. Reason: this gives the real wall-clock shape of the run, so the panels look the same as for a watched run.

Without `performance.dat`, the time stamps are spread evenly from `start_utc` to the modification time of `energy.dat` (`h4nb_pack.sh` keeps the modification times).

The time stamps depend only on the files. A second backfill of the same run gives the same samples (spec.md FR-017).
