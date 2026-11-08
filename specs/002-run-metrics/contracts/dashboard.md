# Contract: Grafana dashboards

# Part 1: dashboard "h4nb runs" (live)

File: `tools/h4nb-metrics/grafana/dashboards/h4nb-runs.json`.

Variables: `run` (multi-value, "All" included, values from `label_values(h4nb_run_info, run)`).

Each panel has a **Description**. Grafana shows it as the tooltip of the `i` icon in the panel title. The description text below is the text in the JSON file. The column "Reason" says why the panel is on the dashboard.

The x axis of each time series is the wall clock (spec.md, Assumptions).

## Row 1: Status

| # | Panel | Type | Query | Unit | Reason | Description (tooltip) |
|---|---|---|---|---|---|---|
| 1 | Run state | stat, value mappings 0 running (blue), 1 finished (green), 2 stopped early (red), 3 stalled (orange) | `h4nb_run_state{run=~"$run"}` | - | Shows at once if a run needs action. | State of the run from its files. Running: the .dat.tmp files change. Finished: t reached t_end. Stopped early: h4nb_run stopped before t_end with an error; read the screen output of the run. Stalled: the files did not change for longer than 5 segment times (minimum 300 s); the process hangs, was killed, or an MPI rank failed. |
| 2 | Progress | bar gauge, 0 to 100 % | `h4nb_progress_ratio{run=~"$run"}` | percentunit | Progress of all selected runs in one view. | Simulation time divided by t_end. |
| 3 | Time to end | stat | `h4nb_eta_seconds{run=~"$run"}` | s | Plan the next job. Check the Slurm time limit. | Estimated wall time to t_end. It uses the speed of the last 10 diag segments, because the step size changes during a run. Compare this value with the time limit of the job. |
| 4 | Wall time used | stat | `h4nb_wall_seconds_total{run=~"$run"}` | s | Total cost of the run. | Sum of the wall time of all diag segments. Multiply by the number of GPUs to get GPU hours. Start-up time is not included. |
| 5 | Last file update | stat, thresholds: green, orange at 300 s | `h4nb_last_update_age_seconds{run=~"$run"}` | s | Find a hang early. | Time since the run last wrote a .dat file. h4nb_run writes once each diag interval. A value much larger than the segment wall time means that the run does not progress. |
| 6 | Particles | stat | `h4nb_particles{run=~"$run"}` | short | The size of the system gives the scale of all speed numbers. | Number of bodies N, the central body included. Source: key n of config.used, or the header of a snapshot. |

## Row 2: Accuracy

| # | Panel | Type | Query | Unit | Reason | Description (tooltip) |
|---|---|---|---|---|---|---|
| 7 | Relative energy error | time series, log y axis, dashed threshold line | `h4nb_energy_rel_err{run=~"$run"}`; threshold: `max(h4nb_config_value{key="energy_tol",run=~"$run"})` | sci | The main accuracy goal of the project. | rel_err = abs(E - E0 - W_diss) / D at each diag time. D is abs(E0) (energy_norm=e0) or abs(K0) + abs(U0) (ku). The dashed line is energy_tol. The project goal is rel_err <= 1e-8 over one period. A line that grows steadily means drift: decrease eta or dt_max. |
| 8 | Max energy error vs tolerance | stat, thresholds: green, red at 1e-8 | `h4nb_energy_max_rel_err{run=~"$run"}` | sci | Pass or fail in one number. | Largest rel_err since t = 0. Green: below 1e-8. Red: above. A scrape can miss a short peak of rel_err; this value does not miss it. The exact verdict per period is in the panel "Error per period" at the end of the run. |
| 9 | Mean energy error | time series, log y | `h4nb_energy_mean_rel_err{run=~"$run"}` | sci | Separates drift from noise. | Mean of rel_err over all diag times. Noise gives a flat mean. A systematic error gives a mean that grows with time. |
| 10 | Momentum and angular momentum change | time series, log y | `h4nb_momentum_rel_change{run=~"$run"}`, `h4nb_angular_momentum_rel_change{run=~"$run"}` | sci | Conservation check independent of the energy. | dP_rel and dL_rel: change of the total momentum and angular momentum, divided by sum m abs(v) and sum m abs(r x v) of the initial state. Both must stay near the round-off level (about 1e-14). Growth of dP_rel can mean an asymmetric force sum, for example on several GPUs. Growth of dL_rel means an orbit error. |
| 11 | Dissipated work | time series | `h4nb_dissipated_work{run=~"$run"}` | short | Explains an energy change with dissipation on. | W_diss: work of the drag force since t = 0. It is 0 with dissipation=off. The energy error already subtracts it. A large W_diss with a small error means that the energy balance is correct. |
| 12 | Error per period | bar gauge, log | `h4nb_period_max_rel_err{run=~"$run"}` | sci | The acceptance number of the run. | Largest rel_err in each reference period T, from energy_periods.dat. h4nb_run writes this file only at the end of the run, so the panel is empty during a run. |

## Row 3: Time steps

| # | Panel | Type | Query | Unit | Reason | Description (tooltip) |
|---|---|---|---|---|---|---|
| 13 | Block time steps | time series, log y | `h4nb_dt_min`, `h4nb_dt_mean`, `h4nb_dt_max` (each `{run=~"$run"}`) | sci | Shows the step hierarchy and close encounters. | Smallest, mean and largest individual time step at each diag time. Steps are dt_max / 2^k. A fast fall of dt_min means a close encounter, and the run becomes slower. dt_min near dt_max / 2^max_level means the step limit is near. |
| 14 | Active particles per block step | time series | `h4nb_active_per_block_step{run=~"$run"}` | short | Explains a low speed. | Mean number of particles that move in one block step. Each block step starts the force kernel once for these particles. A value below a few thousand does not fill the GPU, and pairs/s becomes lower. This is normal for the small levels. |
| 15 | Minimum pair distance | time series, log y, threshold line | `h4nb_r_min{run=~"$run"}`; threshold: `max(h4nb_config_value{key="eps",run=~"$run"})` | sci | Explains a small dt_min and a large error. | Smallest pair distance seen in the diag segment. The dashed line is the softening length eps. Below eps, the force is softened. A value below r_close gives a warning in the screen output. |

## Row 4: Performance

| # | Panel | Type | Query | Unit | Reason | Description (tooltip) |
|---|---|---|---|---|---|---|
| 16 | Pair interactions per second | time series | `h4nb_pairs_per_second{run=~"$run"}` | short | The main speed number. | Force pair evaluations per second in the last diag segment: active x N / wall_s. Compare with bench.dat of the same N and GPU. A fall can mean a small active count (see "Active particles per block step"), GPU throttling, or another job on the GPU. |
| 17 | GFLOP/s | stat | `h4nb_gflops{run=~"$run"}` | GFLOP/s | Compare with the GPU data sheet. | 60 x pairs/s / 1e9. 60 FP64 operations for each pair (research.md R6). Divide by the FP64 peak of the GPU to get the efficiency. |
| 18 | Particle updates per second | time series | `h4nb_particle_updates_per_second{run=~"$run"}` | short | Speed that does not depend on N. | Particles advanced per second in the last diag segment: active / wall_s. Use it to compare runs with different N. |
| 19 | Block steps per second | time series | `rate(h4nb_block_steps_total{run=~"$run"}[5m])` | short | Shows the kernel launch rate. | Block steps per second, averaged over 5 minutes. Many block steps with few active particles means launch overhead dominates. |
| 20 | Segment wall time | time series | `h4nb_segment_wall_seconds{run=~"$run"}` | s | Expected interval between file updates. | Wall time of the last diag interval. The files update once in this time. Use it to read the panel "Last file update". |

## Row 5: Run record

| # | Panel | Type | Query | Unit | Reason | Description (tooltip) |
|---|---|---|---|---|---|---|
| 21 | Run record | table | `h4nb_run_info{run=~"$run"}` (labels as columns) joined with `h4nb_config_value{key=~"eta|eps|dt_max|diag|energy_tol|tile|blocks_per_sm",run=~"$run"}` | - | Explains differences between runs. | Code, machine and settings of each run, from run_info.txt and config.used. A commit that ends with -dirty was built with local changes. Compare eta, eps and dt_max before you compare errors or speed. |

## Rules

- A panel with a threshold line from a metric uses a second query with the style "dashed line, no fill".
- All error panels use a log y axis, because the values go from 1e-16 to 1e-6.
- The dashboard does not use a plugin that is not in the default Grafana image.

# Part 2: dashboard "h4nb past runs"

File: `tools/h4nb-metrics/grafana/dashboards/h4nb-past-runs.json`.

Purpose: look at one finished run in detail, from a backfill (spec.md User Story 4) or from the Prometheus history of a watched run.

Variables: `run` (single value, values from `label_values(h4nb_run_info, run)`). Default time range: the last 1 year. Reason: a backfilled run can be old. Prometheus finds a sample only inside the time range.

Prometheus finds a sample for an instant query only in the last 5 minutes before the query time. Therefore the stat and table panels of this dashboard use `last_over_time(<metric>[$__range])`.

## Row 1: Runs

| # | Panel | Type | Query | Unit | Reason | Description (tooltip) |
|---|---|---|---|---|---|---|
| 1 | Run list | table, one row per run, data link on the run name | `last_over_time(h4nb_run_start_timestamp_seconds[$__range])`, `last_over_time(h4nb_run_end_timestamp_seconds[$__range])`, `last_over_time(h4nb_run_state[$__range])`, `last_over_time(h4nb_particles[$__range])`, `last_over_time(h4nb_energy_max_rel_err[$__range])` | - | Find a run and open its time range with one click. | All runs with data in the selected time range. Click a run name to select it and to set the time range to the start and the end of the run. If a run is missing, make the time range larger or load the run with h4nb-metrics backfill. |

## Row 2: Result of the selected run

| # | Panel | Type | Query | Unit | Reason | Description (tooltip) |
|---|---|---|---|---|---|---|
| 2 | Final state | stat, same mappings as part 1 panel 1 | `last_over_time(h4nb_run_state{run="$run"}[$__range])` | - | Did the run reach t_end? | Final state of the run. Finished: t reached t_end. Stopped early: h4nb_run stopped with an error before t_end. Stalled: the archive has only .dat.tmp files; the process hung, was killed, or an MPI rank failed. |
| 3 | Max energy error | stat, thresholds: green, red at 1e-8 | `last_over_time(h4nb_energy_max_rel_err{run="$run"}[$__range])` | sci | Pass or fail of the run. | Largest relative energy error from t = 0 to the end of the run. Green: below 1e-8. Red: above. |
| 4 | Final dP_rel and dL_rel | stat | `last_over_time(h4nb_momentum_rel_change{run="$run"}[$__range])`, `last_over_time(h4nb_angular_momentum_rel_change{run="$run"}[$__range])` | sci | Conservation at the end of the run. | Relative change of the total momentum and of the angular momentum at the last diag time. Both must be near the round-off level (about 1e-14). |
| 5 | Mean pair rate | stat | `avg_over_time(h4nb_pairs_per_second{run="$run"}[$__range])` | short | One speed number for the whole run. | Mean of pairs/s over all diag segments in the time range. Compare it between runs with the same N and GPU. |
| 6 | Wall time | stat | `last_over_time(h4nb_wall_seconds_total{run="$run"}[$__range])` | s | Cost of the run. | Sum of the wall time of all diag segments. Multiply by the number of GPUs to get GPU hours. |
| 7 | Error per period | bar gauge, log | `last_over_time(h4nb_period_max_rel_err{run="$run"}[$__range])` | sci | The acceptance number per period. | Largest relative energy error in each reference period T, from energy_periods.dat. The goal is <= 1e-8 in period 1. A period with complete = 0 was not finished by the run. |

## Row 3: Curves of the selected run

| # | Panel | Type | Query | Unit | Reason | Description (tooltip) |
|---|---|---|---|---|---|---|
| 8 | Energy error against simulation time | XY chart, log y | `h4nb_energy_rel_err{run="$run"}` and `h4nb_sim_time{run="$run"}`, joined by time | sci | The physics view: error against orbits, not against the wall clock. | Relative energy error at each diag time, plotted against the simulation time. One reference period is T (key period). Steps in the curve at close encounters are normal. A slope that does not stop means drift. |
| 9 | Relative energy error | time series, log y | as part 1 panel 7, with `run="$run"` | sci | The same view as during the run. | as part 1 panel 7 |
| 10 | Momentum and angular momentum change | time series, log y | as part 1 panel 10 | sci | as part 1 panel 10 | as part 1 panel 10 |
| 11 | Block time steps | time series, log y | as part 1 panel 13 | sci | as part 1 panel 13 | as part 1 panel 13 |
| 12 | Active particles per block step | time series | as part 1 panel 14 | short | as part 1 panel 14 | as part 1 panel 14 |
| 13 | Minimum pair distance | time series, log y | as part 1 panel 15 | sci | as part 1 panel 15 | as part 1 panel 15 |
| 14 | Pair interactions per second | time series | as part 1 panel 16 | short | as part 1 panel 16 | as part 1 panel 16 |

## Row 4: Run record

| # | Panel | Type | Query | Unit | Reason | Description (tooltip) |
|---|---|---|---|---|---|---|
| 15 | Run record | table | as part 1 panel 21, with `last_over_time(...[$__range])` and `run="$run"` | - | as part 1 panel 21 | as part 1 panel 21 |
