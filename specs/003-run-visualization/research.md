# Research: Visualization of run results (h4nb-viz)

## R1 Where to render

- **Decision**: in the browser with WebGL. The server only reads and slices arrays.
- **Reason**: a laptop GPU draws 200 000 point sprites at 60 fps. Rendering on the server (matplotlib, VTK offscreen) needs much more CPU and gives no interaction.
- **Alternatives**:
  - matplotlib movies are slow for 1M points and give no interaction.
  - ParaView is strong, but it is a large program for end users. It is kept as an export in Phase 3.
  - Blender gives the best images, but it needs much work.
  - A Grafana panel plugin has no good 3D view and is a large project.

## R2 Glow effect

- **Decision**: `THREE.Points` with a soft round sprite texture made in code, `AdditiveBlending`, `depthWrite=false`, color from a colormap texture. The point size depends on the screen height.
- **Reason**: dense regions become bright without a bloom pass. No extra library.
- **Alternatives**: `UnrealBloomPass` needs more GPU work and more code. A density texture works only in 2D.

## R3 Decimation subset

- **Decision**: keep particle `i` when `splitmix64(id_i ^ seed) < 2^64 · k / N`. Also keep the central body. With `numpy`, one vector pass over the `id` array per run gives the subset. Cache the index list.
- **Reason**: deterministic, the same set in each frame, needs no state on disk.
- **Alternatives**: `random.sample` with a seed. It needs a stored list. Every k-th index is another option. It shows visible patterns if the IC generator orders particles by radius.

## R4 Curves library

- **Decision**: `uPlot` 1.6.30.
- **Reason**: about 50 KB, draws 10^5 points fast, ES module, MIT.
- **Alternatives**: Plotly is about 3.5 MB. Chart.js is slower for large series. D3 needs much more code.

## R5 Movie export

- **Decision**: use `canvas.captureStream(30)` and `MediaRecorder`. The recorder writes VP9 WebM. Safari writes MP4. With `ffmpeg`, run `ffmpeg -i in.webm -c:v libx264 -pix_fmt yuv420p -crf 18 out.mp4`.
- **Reason**: No extra program is needed for a first movie. MP4 works in PowerPoint and Keynote.
- **Alternative**: Send frame-by-frame PNG files to the server, and encode them with `ffmpeg`. This gives an exact frame rate, but it sends more data. Keep it as the option `--exact` in Phase 2. Use it only if the real-time recording drops frames.

## R6 Prometheus queries

- **Decision**: `GET /api/v1/query_range?query=<expr>&start=<s>&end=<s>&step=<s>`, `step` = max(15 s, range/2000). `urllib` from the stdlib. The `<expr>` is a metric name from the table below with the selector `{run="<label>",origin!="backfill"}`.
- **Reason**: no client library. 2000 points per curve is enough for a plot.
- **Note**: Prometheus stores wall time. The page plots against simulation time.
  - The server also queries `h4nb_sim_time{run="<label>",origin!="backfill"}`.
  - It joins each series with that query on the step timestamp of the response.
  - Both series use the same step grid.
  - The join pairs the points that have the same timestamp.

### Metric name table (checked 2026-11-08)

Source of the names: `specs/002-run-metrics/contracts/metrics.md`. The names were checked against two prototype files: `tools/h4nb-metrics/src/h4nb_metrics/metrics.py` and the dashboard queries in `tools/h4nb-metrics/grafana/build_dashboards.py`. The prototype and the contract use the same names.

A counter has the suffix `_total` in Prometheus. The prototype stores the name without this suffix. The client library adds it.

All metrics have the label `run`. The value of `run` is the run label of specs/002 (see the run name rule in contracts/http-api.md).

| h4nb-viz name | Prometheus metric | Type | Extra labels | Used by |
|---|---|---|---|---|
| `sim_time` | `h4nb_sim_time` | gauge | - | join key of all series. Used by D1 and D5 |
| `t_end` | `h4nb_t_end` | gauge | - | run card, progress |
| `progress_ratio` | `h4nb_progress_ratio` | gauge | - | D5 |
| `eta_seconds` | `h4nb_eta_seconds` | gauge | - | D5 |
| `run_state` | `h4nb_run_state` | gauge | - | `/api/runs` state (0 running, 1 finished, 2 stopped early, 3 stalled) |
| `run_info` | `h4nb_run_info` | gauge, value 1 | `host`, `commit`, `build_type`, `gpu`, `ranks`, `mpi`, `start_utc`, `preset` | `in_prometheus`, run card |
| `particles` | `h4nb_particles` | gauge | - | run card, `n` |
| `wall_seconds` | `h4nb_wall_seconds_total` | counter | - | run card |
| `energy_rel_err` | `h4nb_energy_rel_err` | gauge | - | D1 |
| `energy_max_rel_err` | `h4nb_energy_max_rel_err` | gauge | - | run card |
| `energy_mean_rel_err` | `h4nb_energy_mean_rel_err` | gauge | - | D1 (optional line) |
| `energy_total` | `h4nb_energy_total` | gauge | - | not used in MVP |
| `dissipated_work` | `h4nb_dissipated_work` | gauge | - | D1 (second series) |
| `momentum_rel_change` | `h4nb_momentum_rel_change` | gauge | - | D3 |
| `angular_momentum_rel_change` | `h4nb_angular_momentum_rel_change` | gauge | - | D3 |
| `period_max_rel_err` | `h4nb_period_max_rel_err` | gauge | `period` | D2 |
| `dt_min` | `h4nb_dt_min` | gauge | - | D4 |
| `dt_mean` | `h4nb_dt_mean` | gauge | - | D4 |
| `dt_max` | `h4nb_dt_max` | gauge | - | D4 |
| `r_min` | `h4nb_r_min` | gauge | - | D4 |
| `active_per_block_step` | `h4nb_active_per_block_step` | gauge | - | D5 |
| `pairs_per_second` | `h4nb_pairs_per_second` | gauge | - | D5 |
| `gflops` | `h4nb_gflops` | gauge | - | run card (not a D plot) |
| `particle_updates_per_second` | `h4nb_particle_updates_per_second` | gauge | - | not used in MVP |
| `segment_wall_seconds` | `h4nb_segment_wall_seconds` | gauge | - | live update interval (T023) |
| `block_steps_total` | `h4nb_block_steps_total` | counter | - | not used in MVP |
| `active_updates_total` | `h4nb_active_updates_total` | counter | - | not used in MVP |
| `config_value` | `h4nb_config_value` | gauge | `key` | `eta`, `eps`, `energy_tol` (not a series) |
| `run_start_timestamp_seconds` | `h4nb_run_start_timestamp_seconds` | gauge | - | run card (`start_utc`) |
| `run_end_timestamp_seconds` | `h4nb_run_end_timestamp_seconds` | gauge | - | not used in MVP |

Backfilled samples have the extra label `origin="backfill"` (specs/002 FR-017). Every query in this file uses the matcher `origin!="backfill"` (decision OQ-2, contracts/http-api.md).

## R7 Orbital elements

- **Decision**: use two-body elements relative to the central body. Use μ = G (m_c + m_i). Compute `a` from the vis-viva equation. Compute `e` from the eccentricity vector. Compute `inc` from the angular momentum vector and the z axis.
- **Reason**: The method is standard. It is vectorised in `numpy`. It takes about 50 ms for 10^6 particles.
- **Note**: these are osculating elements for display. They are not used for any accuracy result.

## R8 Desktop wrapper

- **Decision**: Tauri 2 in Phase 3. It starts `h4nb-viz serve` as a sidecar and opens the page in the system web view.
- **Reason**: about 10 MB. Electron is about 150 MB.
- **Alternative**: `pywebview` is simpler and uses Python only. Check in Phase 3 whether a Rust toolchain is a problem.
