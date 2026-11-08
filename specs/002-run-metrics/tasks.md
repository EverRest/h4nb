---
description: "Task list for h4nb-metrics: exporter, backfill and Grafana dashboards"
---

# Tasks: Run metrics exporter and Grafana dashboards (h4nb-metrics)

**Input**: `specs/002-run-metrics/` (spec.md, plan.md, contracts/metrics.md, contracts/dashboard.md).

**Branch**: do all code tasks in the branch `develop`. Do not merge into `main` unless Pavlo asks.

**Prototype**: the branch `develop` can contain a prototype of these tasks (plan.md, "Verification done on the prototype"). A task is done when its result meets the contract and its check passes. It is not done because a file exists.

**Rules for all tasks**: do not change files outside `tools/h4nb-metrics/` and `specs/002-run-metrics/` (FR-002). Write all text in ASD-STE100. Use only Python 3.8 syntax. Do not commit or push unless Pavlo asks. Run `python -m pytest -q` in `tools/h4nb-metrics` before a task is marked done.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (a different file, no dependency on an open task).
- **[Story]**: the user story in spec.md (US1 to US4).

---

## Phase 1: Setup

- [ ] M001 Create `tools/h4nb-metrics/pyproject.toml` (name `h4nb-metrics`, Python ≥ 3.8, dependency `prometheus_client>=0.12`, extra `test` with `pytest>=7` and `prometheus_client>=0.21`, script `h4nb-metrics = h4nb_metrics.cli:main`, src layout). Check: `pip install -e tools/h4nb-metrics` works in a clean venv.
- [ ] M002 [P] Create `src/h4nb_metrics/__init__.py` (version) and `__main__.py`. Create `tests/conftest.py` that adds `src` to the import path.

## Phase 2: Foundational (blocks all stories)

- [ ] M003 [P] `readers.py`: `parse_config_used` (skip `# key=` lines without a value), `parse_run_info`, `parse_device_line` (a GPU name can contain spaces), `parse_header` (stop at the first token that starts with `(`), `parse_row` (None for a bad line; `nan` and `inf` are numbers), `snapshot_header` (32 bytes, magic and version check), `split_lines` (keep the incomplete rest). Check: `tests/test_readers.py`.
- [ ] M004 [P] `readers.py`: `DirSource` and `MemorySource` with `stat`, `read(name, offset, size)`, `names`, `resolve`. `read_archive` for `h4nb_pack.sh` archives: find the run directories by `config.used`, remove the top directory from the name, keep only the 32-byte header of each snapshot. Check: an archive test in `tests/test_readers.py`.
- [ ] M005 `runs.py`: `TableTail` (plan P2). It reads `X.dat`, else `X.dat.tmp`; continues at the offset after a rename; reads again from the start after an inode change or a shorter file; counts bad lines. Check: tests for a partial line, a rename and a shorter file.
- [ ] M006 `metrics.py`: the names, types and help texts of `contracts/metrics.md` sections 1 to 4, 7 and 8. Counter names without `_total`.

## Phase 3: User Story 1 - Watch a running simulation (P1)

**Goal**: live values of one run in Prometheus.

**Independent test**: spec.md US1.

- [ ] M007 [US1] `runs.py`: `Run` with `update()` and `samples(now, stale_min)`. Implement all metrics of `contracts/metrics.md` sections 1 to 4: the gauges from the last rows (`ROW_GAUGES`), `h4nb_gflops` (60 × pairs/s / 1e9), `h4nb_particle_updates_per_second`, the counters from the sums of `performance.dat`, `h4nb_config_value` (numeric keys only), `h4nb_run_info` labels, `h4nb_period_max_rel_err` per period, start and end time stamps.
- [ ] M008 [US1] `runs.py`: run state (`contracts/metrics.md` section 5) with `stale_after` = max(`stale_min`, 5 × the largest `wall_s` of the last 10 segments). Time to end (section 6): 0 for states 1 and 2, not exposed for state 3 or with fewer than 2 segments. Check: tests for finished, stopped early, running, stalled, and the time-to-end formula.
- [ ] M009 [US1] `runs.py`: particle count by the order of FR-008 (key `n`, first `snap_*.snap`, `ic` when it is a `.snap`). Check: a test without the key `n`.
- [ ] M010 [US1] `exporter.py`: a `prometheus_client` collector that refreshes the runs at each scrape under one lock (plan P3) and adds the exporter metrics (section 7). An error in one run increments `h4nb_exporter_read_errors_total` and does not stop the others (FR-013). Check: `tests/test_exporter.py` (all metrics of the contract are exposed; the files do not change; SC-003).
- [ ] M011 [US1] `fakerun.py` (FR-012): write `config.used`, `run_info.txt`, `snap_000000.snap`, then one line of each table for each diag segment with the column formats of file-formats.md; at the end, `energy_periods.dat` and the rename of all `.tmp` files. Options: `instant`, `interval`, `fail_at` (NaN line, publish, exit 3), `hang_at` (stop, keep `.tmp`), `start_utc`, `seed`.
- [ ] M012 [US1] `cli.py`: `serve` (default `127.0.0.1:9810`, FR-009), `dump` (print once), `fake-run`. Check: `h4nb-metrics dump` on a fake run prints all metrics.

## Phase 4: User Story 2 - Several runs at the same time (P1)

**Independent test**: spec.md US2.

- [ ] M013 [US2] `runs.py`: `RunSet` and `discover`. A run directory has a `config.used` whose first line contains `h4nb_run`. Search to `max_depth`. Search again at most each `rescan` seconds (FR-004). Labels: the directory name, or the path relative to the given path when two names are the same. Check: a test with two `run1` directories and a run that appears later.

## Phase 5: Dashboard "h4nb runs" and the container setup (US1, US2)

- [ ] M014 `grafana/build_dashboards.py`: write `dashboards/h4nb-runs.json` with the 21 panels of `contracts/dashboard.md` part 1, in the order of the contract, with the description text of the contract. Data source uid `prometheus`. Variable `run` (multi, All).
- [ ] M015 [P] `docker-compose.yml` (FR-011, FR-019, FR-020): `prom/prometheus:v2.55.1` with retention 5 years, `./backfill` mounted at `/backfill`; `grafana/grafana:11.3.0` with anonymous viewer access and file provisioning; ports on 127.0.0.1. `docker-compose.linux.yml` (plan P11). `prometheus/prometheus.yml` and `prometheus/prometheus-linux.yml`. Grafana provisioning: data source with `url: ${PROMETHEUS_URL}`, dashboard provider for `/var/lib/grafana/dashboards`.
- [ ] M016 `tests/test_dashboards.py`: the JSON files equal the generator output; each panel has the title and the description of the contract (SC-005).
- [ ] M017 Manual check (SC-004): start 4 fake runs (normal, a second normal with another `eta`, `--hang-at`, `--fail-at`), `serve`, and `docker compose up`. All panels show data within 60 s. Record a screenshot in the pull request.

## Phase 6: User Story 3 - Final values from an archive (P3)

- [ ] M018 [US3] `RunSet` accepts `h4nb_logs_*.tar.gz` paths and reads an archive again only when its modification time changes. Check: `h4nb-metrics dump ARCHIVE` shows the runs of the archive.

## Phase 7: User Story 4 - Past runs on a separate dashboard (P2)

**Independent test**: spec.md US4.

- [ ] M019 [US4] `backfill.py`: `FullRun` (all rows), `Timeline` (time stamps of `contracts/metrics.md` section 8, with the even spread when there is no `performance.dat`), `run_series`, `write_openmetrics` (label `origin="backfill"`, counters as `*_total`, one series after the other in time order, `# EOF`). Check: `tests/test_backfill.py` (valid OpenMetrics, time stamps, deterministic output, stalled state, read only).
- [ ] M020 [US4] `cli.py backfill`: output to a file or to standard output; `--load` writes to `<compose dir>/backfill/`, runs `promtool tsdb create-blocks-from openmetrics` in the Prometheus container, then restarts the container (plan P6).
- [ ] M021 [US4] `build_dashboards.py`: `dashboards/h4nb-past-runs.json` with the 15 panels of `contracts/dashboard.md` part 2 (plan P9, P10). Run list with a data link that sets `var-run`, `from` and `to`. Extend M016 to part 2.
- [ ] M022 [US4] Manual check: make two fake runs with `--instant --start-utc` in the past, pack them with `tools/h4nb_pack.sh`, run `h4nb-metrics backfill ARCHIVE --load`. "h4nb past runs" shows both runs, and the XY chart has the simulation time on the x axis. Run the backfill again: the values are not doubled. Measure SC-007.

## Phase 8: Polish

- [ ] M023 [P] `tools/h4nb-metrics/README.md` in ASD-STE100: install, the three network setups of spec.md ("Live data and past runs"), live use, backfill, the fake run, the effect on the library and the server, the list of dashboards.
- [ ] M024 [P] Measure SC-002 (20 fake runs, one line each second, scrape each 15 s, 2 minutes): CPU time and resident memory of `serve`. Record the numbers in the pull request.
- [ ] M025 Run the tests with Python 3.8 and the newest Python (SC-006).
- [ ] M026 Check SC-001: `git diff main --stat` shows changes only in `tools/h4nb-metrics/` and `specs/002-run-metrics/`.

## Dependencies

- M003 to M006 block all later tasks.
- US1 (M007 to M012) before US2 (M013), because `RunSet` uses `Run`.
- M014 to M017 need M010 and M013.
- US3 (M018) needs M004 and M013.
- US4 (M019 to M022) needs M007 to M009 and M015.
- Polish after all stories.

## Parallel work

- M003 and M004 (one file, but separate functions) can be given to one agent each if they agree on the `Source` interface first (`stat`, `read`, `names`, `resolve`).
- After phase 4: the dashboards (M014, M021), the container setup (M015) and the backfill (M019, M020) are independent.
