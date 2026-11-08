# Contract: HTTP API of the h4nb-viz server

The server listens on `127.0.0.1:<port>` (default 8820). All endpoints are `GET` unless stated. JSON is UTF-8. Errors are JSON `{"error": "<text>"}` with status 400 (bad request), 404 (no such run, frame or file) or 503 (Prometheus not reachable, only on `source=prometheus`).

`{run}` is the run name: the path of the run directory relative to the root directory, with `/` replaced by `~` (for archives: `<archive name>~<subdirectory>`).

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

## `GET /api/runs`

A list of runs, newest `mtime` first.

```json
[{"run": "eta~run1", "state": "finished", "n": 131073, "t_end": 6.3125, "sim_time": 6.3125,
  "snapshots": 101, "tables": ["energy", "momentum", "timesteps", "performance", "energy_periods"],
  "in_prometheus": true, "thin": false, "archive": null}]
```

`state` is one of `running` (files changed in the last `stale_after` = 600 s and no `snap_final.snap`), `finished` (`snap_final.snap` or `sim_time` ≥ `t_end`), `stopped` (only `*.dat.tmp` and no change for `stale_after`), `unknown`.

## `GET /api/runs/{run}`

The run card and the frame list.

```json
{"run": "eta~run1", "info": {"host": "...", "gpu": "NVIDIA GeForce RTX 4070 Ti", "commit": "49a2a76", "...": "..."},
 "config": {"eta": "0.0005", "eps": "0.01", "G": "1", "central_id": "0", "...": "..."},
 "frames": [{"index": 0, "file": "snap_000000.snap", "time": 0.0}, {"index": 1, "file": "snap_000001.snap", "time": 0.0625}],
 "final_energy_rel_err": 3.1e-9, "wall_s": 5123.4}
```

`info` is `run_info.txt`, `config` is `config.used` (values as text). A missing file gives `{}`. The frame list is sorted by `time`; `snap_final.snap` is the last frame if its time is larger than the last numbered snapshot.

## `GET /api/runs/{run}/ids?max_points=200000&seed=1`

Binary. The IDs of the subset (plan DD3), `uint32` little-endian if all IDs fit, else `int64` (header `X-H4NB-Id-Type: u32|i64`). Header `X-H4NB-Count`. The central body is the first ID.

## `GET /api/runs/{run}/frames/{index}?max_points=200000&seed=1&fields=pos,vel`

Binary frame, see `frame-format.md` section 1. The particle order is the order of `/ids`. `fields` selects `pos` (always), `vel`, `mass`.

## `GET /api/runs/{run}/derived/{index}?max_points=200000&seed=1&q=speed,r,e,inc`

Binary. One `float32` array per requested quantity, in the order of `q`, each with the particle order of `/ids`. `e` and `inc` follow research.md R7. For `e` ≥ 1, `e` is the value and `inc` is computed the same way.

## `GET /api/runs/{run}/hist/{index}?q=e&bins=50`

JSON `{"edges": [...], "counts": [...], "unbound": 12}` for P2 and P3 on all particles (not only the subset).

## `GET /api/runs/{run}/series?names=energy_rel_err,pairs_per_second&source=auto`

The curves for the D panels.

```json
{"source": "prometheus", "x": "time",
 "series": {"energy_rel_err": {"x": [0.0, 0.0625], "y": [0.0, 1.2e-10], "unit": "1",
            "origin": "h4nb_energy_rel_err"}}}
```

- `source`: `auto` (Prometheus when the run has `in_prometheus` and Prometheus is reachable, else `files`), `prometheus`, `files`.
- `x` is always the simulation time. For Prometheus, the server joins each metric with `h4nb_sim_time` on the sample timestamp (research.md R6).
- `origin` is the metric name or `file:column` (for example `energy.dat:rel_err`). The page shows it in the tooltip (spec FR-014).

Name table (one table in `prometheus.py` and `tables.py`):

| Name | Prometheus | File column |
|---|---|---|
| `energy_rel_err` | `h4nb_energy_rel_err` | `energy.dat:rel_err` |
| `dissipated_work` | `h4nb_dissipated_work` | `energy.dat:W_diss` |
| `momentum_rel_change` | `h4nb_momentum_rel_change` | `momentum.dat:dP_rel` |
| `angular_momentum_rel_change` | `h4nb_angular_momentum_rel_change` | `momentum.dat:dL_rel` |
| `dt_min`, `dt_mean`, `dt_max`, `r_min` | `h4nb_dt_min`, `h4nb_dt_mean`, `h4nb_dt_max`, `h4nb_r_min` | `timesteps.dat:<same>` |
| `pairs_per_second` | `h4nb_pairs_per_second` | `performance.dat:pairs_per_s` |
| `active_per_block_step` | `h4nb_active_per_block_step` | `timesteps.dat:mean_active_per_block_step` |
| `progress_ratio` | `h4nb_progress_ratio` | `energy.dat:time` / `t_end` |
| `period_max_rel_err` | `h4nb_period_max_rel_err` | `energy_periods.dat:max_rel_err` (x = `period`) |

`bench.dat` and `study.dat` are files only: `GET /api/runs/{run}/table/{name}` returns `{"columns": [...], "rows": [[...]]}`.

## `POST /api/export`

Body: the recorded media (`video/webm` or `video/mp4`) or a PNG. Query: `name=<file name>`, `mp4=1` to convert with `ffmpeg`. The server writes into the export directory (`--export-dir`, default `~/h4nb-viz-exports`). Response `{"path": "...", "mp4": true}`. Only from the page origin (check of the `Origin` header).

## `POST /api/runs/{run}/paraview` (Phase 3)

Writes `.pvd` + `.vtp` into the export directory. Response `{"path": ".../run1.pvd", "frames": 101}`.

## Security

- `127.0.0.1` only. No CORS headers. `POST` needs `Origin` equal to the server origin.
- The server serves files only from `web/`. It never serves a path from the request in a run directory.
- `{run}` must be in the current run list; else 404.
