# Contract: HTTP API of the h4nb-viz server

The server listens on `127.0.0.1:<port>` (default 8820).

All endpoints use `GET` unless stated otherwise. JSON is UTF-8.

An error returns the JSON `{"error": "<text>"}`.

- The status is 400 for a bad request.
- The status is 404 for no such run, frame or file.
- The status is 503 when Prometheus is not reachable. The 503 status occurs only for `source=prometheus`.

`{run}` is the run name. It is the path of the run directory, relative to the root directory, with `/` replaced by `~`. For archives, it is `<archive name>~<subdirectory>`.

## Static

| Path | Content |
|---|---|
| `/` | `web/index.html` |
| `/web/...` | files of `web/` (`Cache-Control: max-age=3600`) |

## `GET /api/status`

```json
{"version": "0.1.0", "root": "/Users/pavlo/runs", "prometheus": "http://127.0.0.1:9090", "prometheus_ok": true,
 "ffmpeg": true, "grafana_url": "http://127.0.0.1:3000"}
```

`prometheus_ok` is `true` when `GET <prometheus>/-/ready` returns HTTP 200 within 1 s. The server checks it at most once each 15 s. It is `false` when `--prometheus` is not set.

## `GET /api/runs`

A list of runs, newest `mtime` first.

```json
[{"run": "eta~run1", "state": "finished", "n": 131073, "t_end": 6.3125, "sim_time": 6.3125,
  "snapshots": 101, "tables": ["energy", "momentum", "timesteps", "performance", "energy_periods"],
  "in_prometheus": true, "prom_label": "eta/run1", "thin": false, "archive": null}]
```

`state` uses the names of specs/002 (`contracts/metrics.md` section 5). It is one of:

| `state` | Condition (same as specs/002 `h4nb_run_state`) |
|---|---|
| `running` | `energy.dat.tmp` exists and the newest change is at most `stale_after` ago. |
| `finished` | `energy.dat` exists and its last `time` ≥ `t_end` × (1 − 1e-12). |
| `stopped early` | `energy.dat` exists and its last `time` < `t_end`. |
| `stalled` | `energy.dat.tmp` exists and the newest change is more than `stale_after` ago. |
| `unknown` | 003 only. No `energy.dat` or `energy.dat.tmp` exists. specs/002 does not expose this state. |

`stale_after` = max(300 s, 5 × the largest `wall_s` of the last 10 rows of `performance.dat`). This is the rule of specs/002.

The rescan runs each 5 s. The Prometheus query runs at most once each 15 s.

The query is `h4nb_run_info{origin!="backfill"}`. A backfilled run does not match.

Each series has a `run` label (the 002 label) and a `start_utc` label. The server matches a local run to a series with the same `start_utc` value. It reads that value from the run's `run_info.txt`.

A run without a `run_info.txt` has no match. A matched run gets `prom_label` = the `run` label of that series. `in_prometheus` is `true` when a match exists.

When Prometheus is not reachable, `in_prometheus` is `false` and `prom_label` is `null`.

## `GET /api/runs/{run}`

The run card and the frame list.

```json
{"run": "eta~run1", "info": {"host": "...", "gpu": "NVIDIA GeForce RTX 4070 Ti", "commit": "49a2a76", "...": "..."},
 "config": {"eta": "0.0005", "eps": "0.01", "G": "1", "central_id": "0", "...": "..."},
 "frames": [{"index": 0, "file": "snap_000000.snap", "time": 0.0}, {"index": 1, "file": "snap_000001.snap", "time": 0.0625}],
 "final_energy_rel_err": 3.1e-9, "wall_s": 5123.4}
```

`info` is `run_info.txt`. `config` is `config.used`, with the values as text. A missing file gives `{}`. The frame list is sorted by `time`. `snap_final.snap` is the last frame when its time is larger than the time of the last numbered snapshot.

## `GET /api/runs/{run}/ids?max_points=200000&seed=1`

The response is binary. It holds the IDs of the subset (plan DD3). It uses `uint32` little-endian when all IDs fit. Otherwise, it uses `int64`. The header `X-H4NB-Id-Type` is `u32` or `i64`. The header `X-H4NB-Count` gives the number of IDs. The central body is the first ID.

## `GET /api/runs/{run}/frames/{index}?max_points=200000&seed=1&fields=pos,vel`

The response is a binary frame. See `frame-format.md` section 1. The particle order is the order of `/ids`. The `fields` value selects `pos`, `vel` and `mass`. `pos` is always included.

## `GET /api/runs/{run}/derived/{index}?max_points=200000&seed=1&q=speed,r,e,inc`

The response is binary. It holds one `float32` array for each requested quantity, in the order of `q`. Each array uses the particle order of `/ids`. `e` and `inc` follow research.md R7. For `e` ≥ 1, the value of `e` is kept. Compute `inc` the same way.

## `GET /api/runs/{run}/hist/{index}?q=e&bins=50`

JSON `{"edges": [...], "counts": [...], "unbound": 12}` for P2 and P3 on all particles (not only the subset).

## `GET /api/runs/{run}/series?names=energy_rel_err,pairs_per_second&source=auto`

The curves for the D panels.

```json
{"source": "prometheus",
 "series": {"energy_rel_err": {"x": [0.0, 0.0625], "x_name": "time", "y": [0.0, 1.2e-10],
            "metric": "h4nb_energy_rel_err"}}}
```

- `source`: `auto` (Prometheus when the run has `in_prometheus` and Prometheus is reachable, else `files`), `prometheus`, `files`.
- Each series has its own `x_name`. `x_name` is `"time"` for all names except `period_max_rel_err`. For that name, `x_name` is `"period"` and `x` holds the period numbers. The page reads the axis from each series. There is no top-level `x` and no `unit` field.
- `progress_ratio` is `time / t_end` of `energy.dat`. The server computes it. A run without `t_end` in `config.used` has no `progress_ratio` series.
- For Prometheus, the server joins each metric with `h4nb_sim_time` on the sample timestamp (research.md R6). The join uses the same `origin!="backfill"` matcher as the metric.
- `metric` is the metric name or `file:column` (for example `energy.dat:rel_err`). The page shows it in the tooltip (spec FR-014).

Prometheus queries use the selector `{run="<label>",origin!="backfill"}`. Backfilled samples never reach the D plots (OQ-2, resolved). A run that is only backfilled has no Prometheus series for the D plots. Its curves come from files.

Name table (one table in `prometheus.py` and `tables.py`). The Prometheus column uses the names of research.md R6.

| Name | Prometheus | File column |
|---|---|---|
| `sim_time` | `h4nb_sim_time` | `energy.dat:time` (join key, not plotted alone) |
| `energy_rel_err` | `h4nb_energy_rel_err` | `energy.dat:rel_err` |
| `dissipated_work` | `h4nb_dissipated_work` | `energy.dat:W_diss` |
| `momentum_rel_change` | `h4nb_momentum_rel_change` | `momentum.dat:dP_rel` |
| `angular_momentum_rel_change` | `h4nb_angular_momentum_rel_change` | `momentum.dat:dL_rel` |
| `dt_min`, `dt_mean`, `dt_max`, `r_min` | `h4nb_dt_min`, `h4nb_dt_mean`, `h4nb_dt_max`, `h4nb_r_min` | `timesteps.dat:<same>` |
| `pairs_per_second` | `h4nb_pairs_per_second` | `performance.dat:pairs_per_s` |
| `active_per_block_step` | `h4nb_active_per_block_step` | `timesteps.dat:mean_active_per_block_step` |
| `progress_ratio` | `h4nb_progress_ratio` | `energy.dat:time` / `t_end` |
| `eta_seconds` | `h4nb_eta_seconds` | none: the server computes it with the rule of specs/002 section 6 |
| `period_max_rel_err` | `h4nb_period_max_rel_err` | `energy_periods.dat:max_rel_err` (x = `period`) |

`bench.dat` and `study.dat` exist only as files. `GET /api/runs/{run}/table/{name}` returns `{"columns": [...], "rows": [[...]]}`.

## `POST /api/export`

The body holds the recorded media (`video/webm` or `video/mp4`) or a PNG.

The query takes `name=<file name>`. Add `mp4=1` to convert with `ffmpeg`.

The server writes into the export directory (`--export-dir`, default `~/h4nb-viz-exports`).

The response is `{"path": "...", "mp4": true}`.

Only the page origin may call this endpoint. The server checks the `Origin` header.

## `POST /api/archive` (Phase 2, FR-015)

The body is a `.tar`, `.tar.gz` or `.tgz` archive of `tools/h4nb_pack.sh`.

The query takes `name=<file name>` (the suffix must match).

The server writes the file into `~/.cache/h4nb-viz/uploads/` (or the cache directory of the server). It does not write into the run root. It then scans the archive. The response is `{"path": "...", "runs": ["<stem>~<run>", ...]}`.

Only the page origin may call this endpoint. The server checks the `Origin` header. The page uses this endpoint for drag and drop of an archive.

## `POST /api/runs/{run}/paraview` (Phase 3)

Writes `.pvd` + `.vtp` into the export directory. Response `{"path": ".../run1.pvd", "frames": 101}`.

## Security

- `127.0.0.1` only. No CORS headers. `POST` needs `Origin` equal to the server origin.
- The server serves files only from `web/`. It never serves a path from the request in a run directory.
- `{run}` must be in the current run list. Otherwise, the server returns 404.

## Run name and label

`{run}` is the 003 name. It is the directory path relative to the root, with `/` replaced by `~`.

The Prometheus label is the run label of specs/002. The two can differ. The specs/002 label is a relative path (see specs/002 `spec.md`, Key Entities).

The server keeps both names. It uses the 003 name for URLs and the 002 label for queries.

The Grafana link of specs/002 sends the 002 label in the URL fragment. The link is defined in `specs/002-run-metrics/contracts/links.md`. This file does not copy it.

The page decodes the percent-encoded fragment value first. Then it matches the whole value with the field `prom_label` of the run in `/api/runs`. It does not match the last part of the label. Two runs can share a last part, for example `eta/run1` and `scan/run1`.

Hash rule: the fragment is `#run=<label>`. The page reads the text after `run=` and applies `decodeURIComponent` once. The page compares the result with `prom_label` of each run in `/api/runs`. The comparison is exact: no trimming and no case change.

Match rule:
- Exactly one run has `prom_label` equal to the decoded value: the page selects that run and opens its time range.
- No run matches: the page selects no run and shows the message "No run with label VALUE in this root directory. Check the root directory of h4nb-viz." VALUE is the decoded fragment. The page does not guess a run from the last part of the label.
- Two or more runs match. This is not expected, because each `prom_label` is a unique Prometheus label. The page selects none and shows "Several runs match VALUE."
- The page does not use the 003 name (`~` form) for this match.

`prom_label` is the `run` label of the `h4nb_run_info` series that matches the run. The server takes it from the Prometheus response at each rescan.

When no series matches, `prom_label` is `null`. A run with `prom_label` = `null` does not match any fragment.

`in_prometheus` is `true` only when `prom_label` is not `null`.

## Open questions

Resolved by Pavlo (2026-11-08):

- OQ-1: The JSON key for the metric name is `metric`. The name `origin` stays for the Prometheus label only (specs/002 FR-017).
- OQ-2: The D plots show no backfilled series. Queries use `origin!="backfill"`.
- OQ-3: The `state` values are the names of specs/002 (`running`, `finished`, `stopped early`, `stalled`, `unknown`). The `stale_after` rule is the rule of specs/002.
