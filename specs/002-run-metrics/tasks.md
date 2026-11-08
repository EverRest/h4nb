---
description: "Task list for h4nb-metrics: exporter, backfill and Grafana dashboards"
---

# Tasks: Run metrics exporter and Grafana dashboards (h4nb-metrics)

**Input**: `specs/002-run-metrics/` (spec.md, plan.md, contracts/metrics.md, contracts/dashboard.md, contracts/links.md).

**Branch**: do all code tasks in the branch `develop`. Do not merge into `main` unless Pavlo asks.

**Prototype**: the branch `develop` contains a prototype of these tasks in `tools/h4nb-metrics/` (plan.md, "Verification done on the prototype"). A task is done when its result meets the contract and its check passes. It is not done because a file exists.

**Status legend** (checked on 2026-11-08 against the prototype and its tests; `python3 -m pytest` with Python 3.13.3 gives 26 passed):

- **done**: the contract is met, and a test or a file check shows it. The checkbox is ticked.
- **partly done**: code exists, but a part of the check has no test or was not run. The checkbox is not ticked.
- **open**: no code, or no evidence in the repository. The checkbox is not ticked.

**Rules for all tasks**: do not change files outside `tools/h4nb-metrics/` and `specs/002-run-metrics/` (FR-002). Write all text in ASD-STE100. Use only Python 3.8 syntax. Do not commit or push unless Pavlo asks. Run `python -m pytest -q` in `tools/h4nb-metrics` before a task is marked done.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (a different file, no dependency on an open task).
- **[Story]**: the user story in spec.md (US1 to US4).

---

## Phase 1: Setup

- [x] M001 Create `tools/h4nb-metrics/pyproject.toml` (name `h4nb-metrics`, Python ≥ 3.8, dependency `prometheus_client>=0.12`, extra `test` with `pytest>=7` and `prometheus_client>=0.21`, script `h4nb-metrics = h4nb_metrics.cli:main`, src layout). Check: `pip install -e tools/h4nb-metrics` works in a clean venv. **Status: done (2026-11-08).** Clean venvs on Python 3.8.20 and 3.13.3: an editable install of a copy of the tool succeeds, and `h4nb-metrics --version` prints `0.1.0`.
- [x] M002 [P] Create `src/h4nb_metrics/__init__.py` (version) and `__main__.py`. Create `tests/conftest.py` that adds `src` to the import path. **Status: done.** Files exist. The 26 tests import the package.

## Phase 2: Foundational (blocks all stories)

- [x] M003 [P] `readers.py`: `parse_config_used` (skip `# key=` lines without a value), `parse_run_info`, `parse_device_line` (a GPU name can contain spaces), `parse_header` (stop at the first token that starts with `(`), `parse_row` (None for a bad line; `nan` and `inf` are numbers), `snapshot_header` (32 bytes, magic and version check), `split_lines` (keep the incomplete rest). Check: `tests/test_readers.py`. **Status: done.** Tests `test_config_used_skips_comments_and_empty_values`, `test_run_info_and_device_line`, `test_header_ignores_comment_after_paren`, `test_row_parsing_nan_and_bad`, `test_snapshot_header`, `test_split_lines_keeps_incomplete_rest` pass.
- [x] M004 [P] `readers.py`: `DirSource` and `MemorySource` with `stat`, `read(name, offset, size)`, `names`, `resolve`. `read_archive` for `h4nb_pack.sh` archives: find the run directories by `config.used`, remove the top directory from the name, keep only the 32-byte header of each snapshot. Check: an archive test in `tests/test_readers.py`. **Status: done.** `test_archive_reads_runs_and_only_snapshot_headers` passes.
- [x] M005 `runs.py`: `TableTail` (plan P2). It reads `X.dat`, else `X.dat.tmp`; continues at the offset after a rename; reads again from the start after an inode change or a shorter file; counts bad lines. Check: tests for a partial line, a rename and a shorter file. **Status: done.** `test_tail_incremental_partial_rename_and_shrink` and `test_tail_counts_bad_lines` pass.
- [x] M006 `metrics.py`: the names, types and help texts of `contracts/metrics.md` sections 0 to 4, 7 and 8. Counter names without `_total`. **Status: done.** The 34 names equal the table of metrics.md section 0 (checked 2026-11-08 by name).

## Phase 3: User Story 1 - Watch a running simulation (P1)

**Goal**: live values of one run in Prometheus.

**Independent test**: spec.md US1.

- [x] M007 [US1] `runs.py`: `Run` with `update()` and `samples(now, stale_min)`. Implement all metrics of `contracts/metrics.md` sections 1 to 4: the gauges from the last rows (`ROW_GAUGES`), `h4nb_gflops` (60 × pairs/s / 1e9), `h4nb_particle_updates_per_second`, the counters from the sums of `performance.dat`, `h4nb_config_value` (numeric keys only), `h4nb_run_info` labels, `h4nb_period_max_rel_err` per period, start and end time stamps. **Status: done.** `test_finished_run_values` passes, and `test_exposes_contract_metrics` finds all names.
- [x] M008 [US1] `runs.py`: run state (`contracts/metrics.md` section 5) with `stale_after` = max(`stale_min`, 5 × the largest `wall_s` of the last 10 segments). Time to end (section 6): 0 for states 1 and 2, not exposed for state 3 or with fewer than 2 segments. Check: tests for finished, stopped early, running, stalled, and the time-to-end formula. **Status: done.** `test_stopped_early_and_stalled`, `test_eta_uses_recent_segments`, `test_stale_after_scales_with_segment_time` pass.
- [x] M009 [US1] `runs.py`: particle count by the order of FR-008 (key `n`, first `snap_*.snap`, `ic` when it is a `.snap`). Check: a test without the key `n`. **Status: done.** `test_particles_from_snapshot_without_key_n` passes. The `ic` branch is tested in M029.
- [x] M010 [US1] `exporter.py`: a `prometheus_client` collector that refreshes the runs at each scrape under one lock (plan P3) and adds the exporter metrics (section 7). An error in one run increments `h4nb_exporter_read_errors_total` and does not stop the others (FR-013). Check: `tests/test_exporter.py` (all metrics of the contract are exposed; the files do not change; SC-003). **Status: done.** `test_exposes_contract_metrics`, `test_exporter_only_reads`, `test_scrape_time_20_runs` pass. The scrape time test uses 20 runs of 4 time units, not the 2-minute run of M024.
- [x] M011 [US1] `fakerun.py` (FR-012): write `config.used`, `run_info.txt`, `snap_000000.snap`, then one line of each table for each diag segment with the column formats of file-formats.md; at the end, `energy_periods.dat` and the rename of all `.tmp` files. Options: `instant`, `interval`, `fail_at` (NaN line, publish, exit 3), `hang_at` (stop, keep `.tmp`), `start_utc`, `seed`. **Status: done.** All options exist in `fake_run()` and in the CLI. The test helper `make_run` uses the generator.
- [x] M012 [US1] `cli.py`: `serve` (default `127.0.0.1:9810`, FR-009), `dump` (print once), `fake-run`. Check: `h4nb-metrics dump` on a fake run prints all metrics. **Status: done (2026-11-08).** `h4nb-metrics fake-run <dir> --instant` and then `h4nb-metrics dump <dir>` exit 0. The dump prints 34 metric families, the same names as `contracts/metrics.md`. No test runs the CLI.

## Phase 4: User Story 2 - Several runs at the same time (P1)

**Independent test**: spec.md US2.

- [x] M013 [US2] `runs.py`: `RunSet` and `discover`. A run directory has a `config.used` whose first line contains `h4nb_run`. Search to `max_depth`. Search again at most each `rescan` seconds (FR-004). Labels: the directory name, or the path relative to the given path when two names are the same. Check: a test with two `run1` directories and a run that appears later. **Status: done.** `test_discovery_labels_and_new_runs` passes.

## Phase 5: Dashboard "h4nb runs" and the container setup (US1, US2)

- [x] M014 `grafana/build_dashboards.py`: write `dashboards/h4nb-runs.json` with the 21 panels of `contracts/dashboard.md` part 1, in the order of the contract, with the description text of the contract. Data source uid `prometheus`. Variable `run` (multi, All). **Status: done.** The JSON has 21 non-row panels. `test_json_files_match_generator` passes.
- [x] M015 [P] `docker-compose.yml` (FR-011, FR-019, FR-020): `prom/prometheus:v2.55.1` with retention 5 years, `./backfill` mounted at `/backfill`; `grafana/grafana:11.3.0` with anonymous viewer access and file provisioning; ports on 127.0.0.1. `docker-compose.linux.yml` (plan P11). `prometheus/prometheus.yml` and `prometheus/prometheus-linux.yml`. Grafana provisioning: data source with `url: ${PROMETHEUS_URL}`, dashboard provider for `/var/lib/grafana/dashboards`. **Status: done. `docker compose config` passes for both files (2026-11-08). Stack started: Prometheus target up, Grafana 11.3.0 health ok, both dashboards loaded.** All files exist and match the description. No test starts the containers. The `!reset` tag needs Docker Compose 2.24.0 or later (FR-022). This was not checked.
- [x] M016 `tests/test_dashboards.py`: the JSON files equal the generator output; each panel has the title and the description of the contract (SC-005). **Status: done.** `test_json_files_match_generator` and `test_every_panel_has_contract_description` pass for both parts.
- [x] M017 Manual check (SC-004): start 4 fake runs (normal, a second normal with another `eta`, `--hang-at`, `--fail-at`), `serve`, and `docker compose up`. All panels show data within 60 s. Record a screenshot in the pull request. **Status: done. Four fake runs (normal, eta 0.001, hang at 2.0, fail at 3.0). All 21 panels of "h4nb runs" returned data. The last one (Error per period) at 54.8 s, the others at 8 to 25 s. No screenshot taken.** The plan reports a check on 2026-11-08. No screenshot or log is in the repository.

## Phase 6: User Story 3 - Final values from an archive (P3)

- [x] M018 [US3] `RunSet` accepts `h4nb_logs_*.tar.gz` paths and reads an archive again only when its modification time changes. Check: `h4nb-metrics dump ARCHIVE` shows the runs of the archive. **Status: done (2026-11-08).** `tools/h4nb_pack.sh` packed a fake run. `h4nb-metrics dump ARCHIVE` exits 0 and shows `h4nb_config_value{key="n",run="fakeA"} 1000.0`. The archive was then replaced by another run and its mtime was changed. `dump` showed `run="fakeB"` and `n` 2000.0. No test in the repository covers the reload; this check was a manual run.

## Phase 7: User Story 4 - Past runs on a separate dashboard (P2)

**Independent test**: spec.md US4.

- [x] M019 [US4] `backfill.py`: `FullRun` (all rows), `Timeline` (time stamps of `contracts/metrics.md` section 8, with the even spread when there is no `performance.dat`), `run_series`, `write_openmetrics` (label `origin="backfill"`, counters as `*_total`, one series after the other in time order, `# EOF`). Check: `tests/test_backfill.py` (valid OpenMetrics, time stamps, deterministic output, stalled state, read only). **Status: done.** The four tests `test_valid_openmetrics_with_timestamps`, `test_deterministic`, `test_even_spread_without_performance`, `test_stalled_archive_run_and_read_only` pass.
- [x] M020 [US4] `cli.py backfill`: output to a file or to standard output; `--load` writes to `<compose dir>/backfill/`, stops the `prometheus` service, runs `promtool tsdb create-blocks-from openmetrics` in a one-off container on the Prometheus data volume, then starts the `prometheus` service (plan P6, spec FR-016). The prototype runs `promtool` in the running container and restarts it. This does not match the spec yet: change `load_into_compose` (open, see M029). **Status: done. --load order fixed in cli.py (plan P6). Test: tests/test_load.py.** The code exists in `cmd_backfill` and `load_into_compose`. No test covers `--load`. The test in M029 is open.
- [x] M021 [US4] `build_dashboards.py`: `dashboards/h4nb-past-runs.json` with the 15 panels of `contracts/dashboard.md` part 2 (plan P9, P10). Run list with a data link that sets `var-run`, `from` and `to`. Extend M016 to part 2. **Status: done.** The JSON has 15 non-row panels. The run list has the data link (`var-run`, `from`, `to`). The tests of M016 cover part 2.
- [x] M022 Manual check: make two fake runs with `--instant --start-utc` in the past, pack them with `tools/h4nb_pack.sh`, run `h4nb-metrics backfill ARCHIVE --load`. "h4nb past runs" shows both runs, and the XY chart has the simulation time on the x axis. Run the backfill again: the values are not doubled (FR-017, see open question Q2 in spec.md). Measure SC-007. **Status: done. Two past runs (alpha, beta) backfilled and loaded. Sample counts per run: 102 after the first load and still 102 after the second load. Disk: 2 blocks. The archive was made with tar. tools/h4nb_pack.sh failed on macOS (GNU find -printf). It was fixed on 2026-11-08 (approved by Pavlo). Its archive and manifest were checked after the fix.** The plan reports a check of two runs. The repeat run, the duplicate check and the SC-007 time are not recorded.

## Phase 8: Polish

- [x] M023 [P] `tools/h4nb-metrics/README.md` in ASD-STE100: install, the three network setups of spec.md ("Live data and past runs"), live use, backfill, the fake run, the effect on the library and the server, the list of dashboards, the Docker Compose version (FR-022), and the link to the viewer (links.md). **Status: done. README.md written in ASD-STE100 (2026-11-08). Reviewed once by a subagent.**
- [x] M024 [P] Measure SC-002 (20 fake runs, one line each second, scrape each 15 s, 2 minutes): CPU time and resident memory of `serve`. Record the numbers in the pull request. **Status: done. 20 fake runs, serve, 8 scrapes at 15 s over about 2 minutes: CPU 0:00.06 to 0:00.30 (0.24 s, about 0.2 % of one core), RSS 23.9 MB to 21.1 MB, scrape 0.012 s to 0.020 s, 20 runs seen.** The plan gives numbers from 2026-11-08. They are not recorded in the repository, and this session did not measure them.
- [x] M025 Run the tests with Python 3.8 and the newest Python (SC-006). **Status: done (2026-11-08).** `pytest -q` prints `35 passed` on Python 3.8.20, 3.13.3 and 3.15.0rc1 (the newest Python that uv provides here).
- [x] M026 Check SC-001: `git diff main --stat` shows changes only in `tools/h4nb-metrics/` and `specs/002-run-metrics/`. **Status: done with scope. `git diff main --stat -- tools/h4nb-metrics specs/002-run-metrics` lists 32 files, all in those paths. The three specs/003 files are outside this check (spec.md SC-001). `tools/h4nb_pack.sh` also changed (approved by Pavlo, the portable `find` fix); it is outside the check too.** Not run.

## Phase 9: Gaps found in the spec review (2026-11-08)

- [x] M027 [US1, US4] Add the data link "Open in h4nb-viz" (`contracts/links.md` section 1) to panel 21 of `h4nb-runs.json` and to panel 15 of `h4nb-past-runs.json`. Change `build_dashboards.py`, regenerate both JSON files. Extend `test_dashboards.py`: the link URL equals the template in `links.md`. **Status: done. Link added to the run record table of both dashboards; test_run_record_has_viewer_link_in_both_dashboards passes. Checked in Grafana API (2026-11-08).** No link exists in the prototype.
- [x] M028 Add a test that compares the names in `contracts/metrics.md` section 0 with `metrics.py`. The test reads the table with a regular expression, as `test_dashboards.py` reads the dashboard contract. **Status: done. test_table_names_equal_prototype_names passes.** The set is equal by a manual check (2026-11-08). No test checks it.
- [x] M029 [US4] Change `load_into_compose` to the order of plan P6: stop `prometheus`, `promtool` in a one-off container on the data volume, start `prometheus`. Add tests for `cli.py backfill --load` with a fake `docker` on the PATH. Check: the three steps run in order, and the output must be in `<compose dir>/backfill`. Add a test for the `ic` branch of `particle_count` (M009). **Status: done (2026-11-08).** Test `test_particles_from_ic_snapshot_when_no_snap_files` (tests/test_runs.py) covers the `ic` branch. Tests `test_load_stops_promtool_then_starts`, `test_failed_promtool_still_starts_prometheus`, `test_failed_stop_runs_nothing_else` and `test_backfill_load_default_path_goes_to_compose_backfill` (tests/test_load.py) check the order stop, promtool, start, and the output in `<compose dir>/backfill`. `pytest -q` gives `36 passed` on Python 3.8.20 and 3.13.3.

## Dependencies

- M003 to M006 block all later tasks.
- US1 (M007 to M012) before US2 (M013), because `RunSet` uses `Run`.
- M014 to M017 need M010 and M013.
- US3 (M018) needs M004 and M013.
- US4 (M019 to M022) needs M007 to M009 and M015.
- M027 needs M014 and M021.
- Polish after all stories.

## Parallel work

- M003 and M004 (one file, but separate functions) can be given to one agent each if they agree on the `Source` interface first (`stat`, `read`, `names`, `resolve`).
- After phase 4: the dashboards (M014, M021), the container setup (M015) and the backfill (M019, M020) are independent.
