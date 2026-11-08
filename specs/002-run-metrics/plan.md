# Implementation Plan: Run metrics exporter and Grafana dashboards (h4nb-metrics)

**Branch**: `develop` (code), `main` (spec documents) | **Date**: 2026-11-08 | **Spec**: [spec.md](spec.md)

**Input**: `specs/002-run-metrics/spec.md` and its contracts. User decisions of 2026-11-08: only expose the data; every metric and every panel has a reason and a tooltip; a separate dashboard for past runs (backfill); the code stays in the branch `develop` so that the setup of `main` stays simple; subagents write the code from this plan and `tasks.md`.

## Summary

A separate Python package `tools/h4nb-metrics` reads the output files of `h4nb_run`. It has three commands:

- `serve`: an HTTP exporter for Prometheus (live data).
- `backfill`: the full curves of finished runs in the OpenMetrics format, loaded with `promtool`.
- `fake-run`: a generator of realistic run files, for checks without a GPU.

Two Grafana dashboards ("h4nb runs" and "h4nb past runs") and a `docker-compose.yml` with Prometheus and Grafana complete the feature. The library does not change.

## Technical Context

**Language/Version**: Python ≥ 3.8 (FR-014). The code uses no syntax newer than 3.8 (`from __future__ import annotations` for type hints).

**Primary Dependencies**: `prometheus_client` ≥ 0.12 at run time. The readers use only the standard library. Test: `pytest` ≥ 7, and `prometheus_client` ≥ 0.21 for its OpenMetrics parser (older parsers compare fractional time stamps wrongly).

**Containers**: `prom/prometheus:v2.55.1` (it has `promtool`) and `grafana/grafana:11.3.0`. Pinned versions, so that the dashboard JSON stays valid.

**Storage**: none of its own. Prometheus TSDB in a Docker volume, retention 5 years (FR-019).

**Testing**: `pytest` in `tools/h4nb-metrics/tests/`. The tests use the fake-run generator. They need no GPU, no Docker and no network.

**Target Platform**: exporter on Linux (x86_64, aarch64) and macOS. Containers on any Docker host.

**Performance Goals**: SC-002 (< 1 % CPU, < 50 MB) and SC-003 (scrape < 200 ms for 20 runs).

**Constraints**: read only (FR-001); no change to the library (FR-002); listen on 127.0.0.1 (FR-009, FR-020).

## Constitution Check

| Principle | Check | Result |
|---|---|---|
| I. Accuracy is the contract | The package shows the measured energy error. It does not compute a new error. The values come from `energy.dat` unchanged. | Pass |
| II. Speed by measurement | No change to the hot path. The exporter reads files from another process. | Pass |
| III. Library first, small API | No change to the public API. The package is a client of the output files, not of the library. | Pass |
| IV. Deterministic results | No change to the simulation. The backfill is deterministic (FR-017). | Pass |
| V. Simplicity | Constitution 2.0.1: the dependency rule applies to the library and its CMake/Spack build. A separate tool in `tools/` can have its own dependencies. The package does not link to the library and adds nothing to the build (FR-002). | Pass |
| Development workflow: tests | Constitution 2.0.1: a separate tool keeps its tests next to it and can use `pytest`. The tests run without a GPU. | Pass |

The constitution amendment 2.0.1 (approved by the user on 2026-11-08) covers separate tools in `tools/`.

## Project Structure

### Documentation (this feature)

```text
specs/002-run-metrics/
├── spec.md
├── plan.md               # this file
├── tasks.md
└── contracts/
    ├── metrics.md        # Prometheus metrics, state values, time to end, backfill
    └── dashboard.md      # panels, queries, reasons and tooltips of both dashboards
```

### Source code

```text
tools/h4nb-metrics/
├── pyproject.toml
├── README.md
├── docker-compose.yml          # Prometheus + Grafana, ports on 127.0.0.1
├── docker-compose.linux.yml    # Linux: host network (FR-020)
├── prometheus/
│   ├── prometheus.yml          # scrape host.docker.internal:9810
│   └── prometheus-linux.yml    # scrape 127.0.0.1:9810
├── grafana/
│   ├── build_dashboards.py     # writes the two JSON files from the contract
│   ├── dashboards/h4nb-runs.json
│   ├── dashboards/h4nb-past-runs.json
│   └── provisioning/           # data source (uid prometheus) and dashboard provider
├── backfill/                   # output of backfill --load (git-ignored)
├── src/h4nb_metrics/
│   ├── readers.py              # file formats: config.used, run_info.txt, tables, snapshot header, archives
│   ├── runs.py                 # TableTail, Run, RunSet (discovery, state, time to end)
│   ├── metrics.py              # names, types, help texts
│   ├── exporter.py             # prometheus_client collector
│   ├── backfill.py             # OpenMetrics with time stamps
│   ├── fakerun.py              # fake run generator
│   └── cli.py                  # serve, dump, backfill, fake-run
└── tests/
```

## Design decisions

- **P1. Read the tables by header names** (FR-006). Reason: file-formats.md adds columns at the end (W_diss). Fixed positions would break.
- **P2. Incremental read with the inode** (FR-005). `h4nb_run` renames `X.dat.tmp` to `X.dat`. The rename keeps the inode, so the reader continues at its offset. A new inode or a shorter file starts a new read. Reason: one scrape of a long run reads only the new lines.
- **P3. The collector reads at scrape time.** No background thread. Reason: no work when nobody scrapes; no race between a reader thread and the HTTP thread (one lock).
- **P4. Snapshots: header only.** A snapshot of 1M particles is 64 MB. The exporter reads 32 bytes (FR-008).
- **P5. Run state from files only** (contracts/metrics.md section 5). The exporter cannot see the exit code. The `.dat` / `.dat.tmp` names and the last time against `t_end` give the state. `stale_after` scales with the segment time.
- **P6. Backfill with promtool.** Prometheus has no API to add old samples. `promtool tsdb create-blocks-from openmetrics` is the supported way. The command runs in the Prometheus container, so the user needs no local Prometheus. Prometheus loads new blocks at its start, so the command restarts the container.
- **P7. Backfill time stamps** = `start_utc` + the cumulative `wall_s` (contracts/metrics.md section 8). Reason: the curves have the real wall-clock shape. The values depend only on the files, so a second backfill gives the same samples (FR-017).
- **P8. Dashboards from a generator.** `grafana/build_dashboards.py` writes the JSON. A test compares the JSON with the generator and each description with `contracts/dashboard.md`. Reason: the tooltip texts have one source (the contract), and a change in Grafana's UI cannot silently remove a description.
- **P9. Past-runs dashboard uses `last_over_time(...[$__range])`.** Reason: an instant query finds a sample only 5 minutes back. Backfilled samples are older.
- **P10. Energy error against simulation time** uses the Grafana XY chart. The two queries (`h4nb_sim_time`, `h4nb_energy_rel_err`) have the same time stamps, so a join by time gives (x, y) pairs.
- **P11. Linux networking.** On Linux, `host.docker.internal` does not reach a port on 127.0.0.1 of the host. `docker-compose.linux.yml` puts Prometheus and Grafana on the host network and lets them listen on 127.0.0.1 only.

## Verification done on the prototype (2026-11-08, container, no GPU)

A prototype of all parts exists in the branch `develop`. It was checked as follows:

- 26 tests pass with Python 3.8.20 (`prometheus_client` 0.21.1) and Python 3.13.
- Exporter: 20 fake runs, one line each second, scrape each 15 s: 0.09 s CPU in 120 s (< 0.1 % of one core), 25 MB resident memory, scrape time 5 ms.
- `docker compose` with `prom/prometheus:v2.55.1` and `grafana/grafana:11.3.0`: both dashboards load by provisioning. All panels show data for live fake runs (running, stalled, stopped early).
- Backfill of a `tools/h4nb_pack.sh` archive with two runs: `promtool` made two blocks. "h4nb past runs" showed the run list, the final values and the XY chart against the simulation time.

## Complexity Tracking

| Deviation | Why needed | Simpler alternative rejected because |
|---|---|---|
| Docker for Prometheus and Grafana | The user asked for Grafana. Docker gives a setup with one command. | A native install differs on each OS. It is still possible: the README lists the two config files. |
