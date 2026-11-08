---
description: "Task list for h4nb-viz: local web app for the visualization of run results"
---

# Tasks: Visualization of run results (h4nb-viz)

**Input**: `specs/003-run-visualization/` (spec.md, plan.md, research.md, contracts/).

**Prerequisites**: No library change is needed. Phase 2 tasks with Prometheus need `specs/002-run-metrics` (exporter and compose stack). That feature must exist.

**Tests**: `pytest` tasks are part of each phase. Run `pytest tools/h4nb-viz/tests` before a task is marked done. The library tests (`make test`) do not change.

**Rules for all tasks**:

- Write all text (README, comments, help text) in ASD-STE100.
- Change files only in `tools/h4nb-viz/` and `specs/003-run-visualization/` (spec SC-001).
- Do not change `src/`, `include/`, `tests/`, `CMakeLists.txt` or `tools/h4nb-metrics/`.
- Do not commit or push unless Pavlo asks.
- Ask Pavlo before you start a task marked **[Q1]**, **[Q2]** or **[Q3]**. Such a task depends on an open question of spec.md.
- If Pavlo selects "no" for Q1 (no Python), stop. Ask Pavlo for a new plan.
- Read the contract before you start a task that implements it.
- Where the code and the contract differ, change the contract first. Make that change in the same change.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (a different file, no dependency on an open task).
- **[Story]**: the user story in spec.md (US1 to US6).

---

## Phase 1: Setup

- [x] T001 **[Q1]** Create `tools/h4nb-viz/pyproject.toml`. Set the name `h4nb-viz` and Python ≥ 3.10. Add the dependency `numpy>=1.24`. Add the extra `dev = ["pytest"]`. Add the entry point `h4nb-viz = h4nb_viz.__main__:main`. Create the empty package layout of plan.md Project Structure.
  - Evidence: `pip install -e tools/h4nb-viz[dev]` exit 0 on Python 3.13.3. `pip show h4nb-viz` gives version 0.1.0. `h4nb-viz --help` prints `usage: h4nb-viz [-h] {fake,serve} ...`.
- [x] T002 [P] Vendor `three.js` r160 (`three.module.min.js`) and `uPlot` 1.6.30 (`uPlot.esm.js`, `uPlot.min.css`) into `tools/h4nb-viz/web/vendor/`. Add their LICENSE files. Add a `VERSIONS.txt`. `VERSIONS.txt` lists the version, the source URL and the sha256 of each file.
  - Evidence: `shasum -a 256 tools/h4nb-viz/web/vendor/*` gives the sums in `VERSIONS.txt`. The header of `three.module.min.js` contains `const t="160"`.
- [x] T003 [P] Copy `tools/h4nb-metrics/src/h4nb_metrics/readers.py` to `tools/h4nb-viz/src/h4nb_viz/readers.py`.
  - Add a header comment with the source commit.
  - If specs/002 is not on `main` yet, write the same functions from `specs/001-hermite-nbody-lib/contracts/file-formats.md`.
  - These functions are `parse_config_used`, `parse_run_info`, `parse_header`, `parse_row` and `snapshot_header`.
  - Evidence: `src/h4nb_viz/readers.py` has the five functions. `pytest tools/h4nb-viz/tests` on Python 3.13.3: 65 passed. The functions run in `test_tables.py`, `test_snapshots.py` and `test_server.py`.

---

## Phase 2: Foundational (server core)

**⚠️ CRITICAL**: Finish this phase before you start the user-story phases.

- [x] T004 Write `src/h4nb_viz/fake.py` and the CLI `h4nb-viz fake OUT_DIR [--n 20000] [--snaps 60] [--t-end 6.3125]`.
  - Create a Kepler disk around a central body (m = 1).
  - Use small random e and inc.
  - Advance each snapshot with the Keplerian motion.
  - Write these v1 files with the headers of file-formats.md: the snapshots `snap_%06d.snap` and `snap_final.snap`.
  - Also write `energy.dat`, `momentum.dat`, `timesteps.dat`, `performance.dat`, `energy_periods.dat`, `config.used` and `run_info.txt`.
  - Use plausible values. The energy error follows a random walk near 1e-10.
  - If the specs/002 generator writes snapshots, reuse its table writer.
  - Evidence: `h4nb-viz fake <dir> --n 20000` ran in 4.28 s and wrote 61 snapshots (75 MB), 5 tables, `config.used` and `run_info.txt`. `pytest` on Python 3.13.3: 65 passed, including `test_fake.py` and `test_cli.py`.
- [x] T005 Write `src/h4nb_viz/snapshots.py`. Write the v1 reader with `numpy.memmap`. Read one array at a time. Check the file size. Skip a file that is still being written. Build the decimation subset of plan.md DD3 and research.md R3. Cache the subset per run. The central body comes first.
  - Evidence: `pytest tools/h4nb-viz/tests` on Python 3.13.3: 65 passed. `tests/test_snapshots.py` checks the round trip, a partial read, a partial file and the subset (same over frames, central body first).
- [x] T006 [P] Write `src/h4nb_viz/tables.py`. Read a `.dat` table into `numpy` columns by header name. Read `.dat.tmp` when `.dat` is missing. Ignore a truncated last line. Use the name table of contracts/http-api.md.
  - Evidence: `pytest tools/h4nb-viz/tests` on Python 3.13.3: 65 passed. `tests/test_tables.py` checks the header names, a truncated line, a short row and the `.tmp` fallback.
- [x] T007 Write `src/h4nb_viz/runs.py`. Find the runs under the root. A run is a directory with `config.used`, a snapshot or `energy.dat[.tmp]`. Give each run its name. Set the `state` by the rules of contracts/http-api.md. Rescan at most every 5 s.
  - Evidence: `pytest tools/h4nb-viz/tests` on Python 3.13.3: 65 passed. `tests/test_runs.py` checks the five states, the `stale_after` rule, the rescan limit and the run names.
- [x] T008 Write `src/h4nb_viz/server.py` and the CLI `h4nb-viz serve ROOT [--port 8820] [--export-dir] [--no-browser]`.
  - Use `http.server.ThreadingHTTPServer` on `127.0.0.1`.
  - Serve these endpoints: `/`, `/web/...`, `/api/status`, `/api/runs`, `/api/runs/{run}`, `/api/runs/{run}/ids`, `/api/runs/{run}/frames/{index}`.
  - Serve `/series` with `source=files`.
  - See contracts/http-api.md and frame-format.md section 1.
  - Open the browser.
  - Do not open the browser when the user gives `--no-browser`.
  - Evidence: `h4nb-viz serve` on port 8899 and `curl`: `/api/status` 200, `/api/runs` 200, `/api/runs/demo/ids?max_points=1000` 200 with `X-H4NB-Id-Type: u32`, frame with `fields=pos,vel,mass` 28040 bytes (= 40 + 28 × 1000), unknown run 404, frame 999 404, `/web/../../etc/passwd` 404, `series?names=eta_seconds` 400. `tests/test_server.py` and `tests/test_cli.py` pass in the 65-test run.
- [x] T009 [P] Write the tests.
  - Write `tests/test_snapshots.py`. Test the round trip with the fake run and the partial read. Test that the subset stays the same over frames and contains the central body.
  - Write `tests/test_tables.py` for the header names, a truncated line and the `.tmp` fallback.
  - Write `tests/test_server.py` for a start on a free port, each MVP endpoint, the frame header bytes and the 404 for an unknown run.
  - Evidence: `pytest tools/h4nb-viz/tests -p no:cacheprovider` on Python 3.13.3: `65 passed in 7.47s`. On Python 3.10.21: `65 passed in 7.50s`.

---

## Phase 3: User Story 1 - Show a run in a presentation (P1) 🎯 MVP

**Goal**: 3D disk with glow, time playback, camera presets, presentation mode.

**Independent Test**: `h4nb-viz fake demo && h4nb-viz serve demo`. Select the run. Press `P`.

- [x] T010 [US1] Write `web/index.html`, `web/style.css` and `web/app.js`.
  - Build the layout. The run list is on the left. The 3D view is in the centre. The plots are below. The status bar is at the bottom.
  - Add dark and light themes (FR-011).
  - Add a time slider.
  - Add play and pause.
  - Add these keys: Space, `P`, `←` and `→` (frame step), and `T` (theme).
  - Evidence: `web/index.html`, `web/style.css`, `web/app.js` exist. Playwright (headless Chromium) loaded `/` with no JS errors. Keys: Space toggled play (slider moved from 1 to 10 in 1.5 s), ArrowRight stepped one frame (t = 0.10521), T switched the theme, P started presentation. Dark and light themes both render (screenshots checked).
- [x] T011 [US1] Write `web/scene.js`. Use `THREE.Points` with a soft sprite and additive blending (research.md R2). Write a frame loader. The loader keeps a cache of `cache_frames` frames. It prefetches the next frames (FR-010). Add `OrbitControls`.
  - Evidence: `web/scene.js` has `THREE.Points` with a soft sprite, additive blending and `depthWrite: false`. `FrameLoader` keeps 64 frames and prefetches the next two. `OrbitControls.js` is vendored (`web/vendor/`, SHA-256 in `VERSIONS.txt`). The 3D view draws the demo run (61 frames, N = 20 000) in the browser.
- [x] T012 [US1] In `web/scene.js`, add the camera presets top, edge and fly-around (V2). The fly-around is a slow orbit. It is the default for `P`.
  - Evidence: `View.setPreset` implements `top`, `edge` and `fly`. The buttons call it. `fit` and presentation start with `fly`. Screenshot of the presentation view shows the disk.
- [x] T013 [US1] Add the color modes speed and radius with a color bar (V3, MVP part). The page computes both modes from `pos` and `vel` of the frame. Add `inferno` as a 256×1 texture.
  - Evidence: colour modes `speed` and `radius` in `scene.js`. The colour bar and its range (`0.00 … 1.47` for speed on the demo run) update on change. Deviation: the inferno LUT (256 entries, generated from matplotlib 3.11.2) is a `Uint8Array` used for vertex colours, not a GPU texture.
- [x] T014 [US1] Build the presentation mode (V6). It runs full screen. It hides the controls. It plays automatically and loops. It shows the run name and the time in a corner.

  - Evidence: presentation mode (P) hides the sidebar, controls and status, enters full screen, starts the fly-around view and autoplays. It loops. The run name and time show in the corner (screenshot). Space stops and starts playback. Leaving full screen ends the mode.
---

## Phase 4: User Story 3 - Export media for slides (P1) 🎯 MVP

- [x] T015 [US3] Write `web/record.js`. Add a "Record" button. Call `canvas.captureStream(30)` and `MediaRecorder`. Set the size to 1920×1080. Resize the canvas during the recording. Send the file to `POST /api/export` (research.md R5).
  - Evidence: `web/record.js`. Headless Chromium recorded the demo run to `demo-2026-11-08T18-16-07.webm` (3.6 MB). `ffprobe` reports VP9 at 1920 × 1080. The container has no duration (`N/A`). A later MP4 conversion (T026) should fix this. The ffmpeg hint is in the code, but no test showed it.
- [x] T016 [US3] Add `POST /api/export` to `server.py`. Check the `Origin` header. Write the file into the export directory. MP4 conversion is in Phase 2 (T026).
  - Evidence: `POST /api/export` in `server.py`. `tests/test_server.py` has four export tests (origin check, base name only, numbering of repeated names, bad names). `pytest` on Python 3.13.3: 70 passed. The response has `mp4: false` until T026.
- [x] T017 [P] [US3] Write `web/card.js`. It builds the run card S1 from `/api/runs/{run}`. The card shows N, t_end, GPU, devices or ranks, wall time, final energy error and commit. Add the PNG export at 2× scale (S3).
  - Evidence: `web/card.js` draws the card of the demo run: N 20000, t_end 6.3125, G 1, GPU, ranks, wall time 0:02:06, final energy error 7.94e-11, build and commit. The card PNG is 1600 × 920 px (2× of 800 × 460). Screenshot checked.
- [x] T018 [P] [US3] Add the PNG export of the 3D view (S3). Set `preserveDrawingBuffer` only during the export. Add the PNG export of each plot (S3).

  - Evidence: the View PNG is 1960 × 496 px (2× of the view size) and has 27 639 lit pixels in headless Chromium. Downloads of the card PNG and of the D1 and D5 PNG were captured. Deviations: `preserveDrawingBuffer` is not set, because the image is read in the same task as the render. The plot PNG uses the device pixel ratio, so it is 2× only on a HiDPI screen.
---

## Phase 5: Accuracy and speed plots (P1) 🎯 MVP

- [x] T019 [US1] `web/plots.js`: build uPlot panels D1 and D5.
  - D1 shows the energy error on a log y axis. `W_diss` is a second series.
  - D5 shows pairs/s and progress.
  - Both panels read from `/series`.
  - The tooltip shows the `metric` of each series (FR-014).
  - The time cursor of the 3D view is a vertical line on each plot.
  - A click on a plot moves the 3D view to the nearest frame.
  - Evidence: `web/plots.js` builds D1 (log y, W_diss as a second series) and D5 (pairs/s, progress on a right axis). The screenshot shows both panels at 472 px with the time line and the G = 1 axis label. A click at 75 % of the D5 width moved the slider to frame 7 (t = 1.4) of an 11-frame run.
- [x] T020 [US1] Write `tools/h4nb-viz/README.md` in STE.
  - Describe the install with `pip install -e tools/h4nb-viz`.
  - Describe the three commands of SC-005 and the keys.
  - Say where the exports go.
  - Explain how to copy snapshots from the GPU machine with `rsync` or `make pack --snap`.
  - Describe the resource use.
  - Add one line for h4nb-viz to the tools list of the documentation index (`README.md`).

**Checkpoint**: MVP done. Run a demo on a fake run with N = 1 048 577 (check SC-003) and with N = 20 000.

  - Evidence: `tools/h4nb-viz/README.md` covers install, the two commands, keys, export and the rsync copy. The root `README.md` has one line for `tools/h4nb-viz/`. Check of SC-005: `h4nb-viz fake demo` then `h4nb-viz serve demo` lists the run `demo` with state `finished`.
---

## Phase 6: User Story 2 - Live run with data from Grafana (P1, Phase 2)

- [x] T021 [US2] `src/h4nb_viz/prometheus.py`: implement the Prometheus client.
  - Evidence: `pytest tools/h4nb-viz/tests -q -p no:cacheprovider` on Python 3.13.3: 92 passed. `test_names_match_002_contract` and `test_query_range_joins_sim_time` pass (tests/test_prometheus.py).
  - Use `query_range` with `urllib` (research.md R6).
  - Join each series with `h4nb_sim_time`.
  - Use the name table of contracts/http-api.md.
  - Add the options `--prometheus URL` and `--grafana URL`.
  - Set `prometheus_ok` in `/api/status`. Check it with `GET <url>/-/ready` (contracts/http-api.md).
  - Check: `tests/test_prometheus.py::test_names_match_002_contract`. The test reads the Prometheus names in the table of research.md R6. It fails if a name is not in `specs/002-run-metrics/contracts/metrics.md`. The comparison uses full names. Counters keep the suffix `_total`.
  - Check: `tests/test_prometheus.py::test_query_range_joins_sim_time`. The test checks that each returned series has the x values of `h4nb_sim_time`. It uses the fixture `fake_prometheus` of T024.
- [x] T022 [US2] Add the `/series` source option and the run match.
  - Evidence: `pytest tools/h4nb-viz/tests -q -p no:cacheprovider` on Python 3.13.3: 92 passed. The T022 server tests in tests/test_server.py pass: runs_in_prometheus, run_without_match, backfill_only, series_source_auto_falls_back, series_prometheus_503, series_origin_filter.
  - Add `/series?source=auto|prometheus|files`.
  - Query `h4nb_run_info` without a selector.
  - Match each run by `start_utc`. Set `prom_label`.
  - Set `in_prometheus` in `/api/runs`. See contracts/http-api.md "Run name and label".
  - Check: `tests/test_server.py::test_runs_in_prometheus`. The fake Prometheus returns one `h4nb_run_info` series with label `run="eta/run1"`. Its `start_utc` equals the value in the `run_info.txt` of the run `eta~run1`. Then `prom_label` of `eta~run1` is `eta/run1`, and `in_prometheus` is `true`.
  - Check: `tests/test_server.py::test_run_without_match`. A run with another `start_utc` has `prom_label` = `null`.
  - Check: `tests/test_server.py::test_backfill_only_run_not_in_prometheus`. The fake Prometheus returns only a series with `origin="backfill"`. The run has `in_prometheus` = `false`.
  - Check: `tests/test_server.py::test_series_source_auto_falls_back`. The Prometheus port is closed. `source` is `files`, and the status is 200.
  - Check: `tests/test_server.py::test_series_prometheus_503`. The Prometheus port is closed and `source=prometheus`. The status is 503, with `{"error": ...}`.
  - Check: `tests/test_server.py::test_series_origin_filter`. The query string contains `origin!="backfill"`.
- [x] T023 [US2] Add a live update to the page. Refresh `/series` each 15 s. Refresh the frame list each 5 s for a `running` run. The status bar shows the sources. Show the link "Open in Grafana" when `grafana_url` is set.
  - Evidence (2026-11-08): stub check in headless Chrome (on/off, Grafana link, `#run=`). Live stack: `docker compose` in `tools/h4nb-metrics`, `fake-run --interval 1`, `serve`, then viz with `--prometheus` and `--grafana`. `prometheus_ok: true`, run `live` matched, `/series` used files then Prometheus. After `docker compose stop prometheus`, `prometheus_ok: false` and `/series` used files. Details in `tools/h4nb-viz/README.md`.
- [x] T024 [P] [US2] Write `tests/test_prometheus.py`. Use a fake Prometheus. It is an `http.server` that returns fixed `query_range` JSON. Test the fallback to files when Prometheus is down.
  - Evidence: `pytest tools/h4nb-viz/tests -q -p no:cacheprovider` on Python 3.13.3: 92 passed. Fixture `fake_prometheus` in tests/conftest.py with tests/data/prom_*.json. Fallback test passes.
  - Check: the fixture `fake_prometheus` is in `tests/conftest.py`. It starts a `http.server.ThreadingHTTPServer` on `127.0.0.1` with a free port.
  - Check: the fixture serves `/api/v1/query_range`, `/api/v1/query` and `/-/ready`. The responses come from `tests/data/prom_*.json`. These files copy the JSON shape of the Prometheus HTTP API.
  - Check: the fixture records each request. The tests use the record to check the `run` matcher, the `origin!="backfill"` matcher and the step (≥ 15 s). One test stops the fixture to check the fallback.
- [x] T025 [US2] Send a message to the specs/002 session. Request the Grafana data link "Open in h4nb-viz". Reference `specs/002-run-metrics/contracts/links.md`. Do not copy the link. Do not edit `tools/h4nb-metrics/`.
  - Evidence (2026-11-08): specs/002 closed M027. `contracts/links.md` holds the template. Both dashboards have the data link. The viewer matches `#run=` to `prom_label` (T023). No edit of `tools/h4nb-metrics/` in this session.

## Phase 7: More views and media (Phase 2)

- [x] T026 [P] [US3] Write `src/h4nb_viz/media.py`. Convert WebM (or Safari MP4) to MP4 with `ffmpeg` (research.md R5). Show `ffmpeg` in `/api/status`. The page shows a hint when `ffmpeg` is missing.
  - Evidence: `python -m pytest tools/h4nb-viz/tests -q` on Python 3.13: 127 passed. Real ffmpeg 9.0.2 converted a VP9 WebM to H.264 yuv420p MP4 (ffprobe checked, 3.000 s).
- [ ] T027 [P] Write `src/h4nb_viz/orbits.py`. Add `/derived` and `/hist` (research.md R7). Test the code with circular and eccentric two-body orbits. The values of e and inc must match to 1e-6.
- [ ] T028 Add the color modes e, inc, mass and ID (V3 full) from `/derived`.
- [ ] T029 Add the plots P1 (Σ(r)), P2 (animated histograms of e and inc) and P3 (a–e plane) in `web/plots.js`.
- [x] T030 Add the D2, D3 and D4 panels.
  - Evidence: `web/plots.js` has D2 (error per period as bars, incomplete periods in red, from `period_complete`), D3 (dP/P and dL/L, log scale) and D4 (dt_min, dt_mean, dt_max, and r_min on a right axis). Playwright on the demo run: five panels with the same width, no JS error. Log axes use one tick per decade, because uPlot's own log ticks loop for values below about 1e-15. `pytest` on Python 3.13.3: 71 passed (new test for `period_complete`).
- [ ] T031 Add V4 orbit trails. Keep a ring buffer of the last 64 positions for up to 200 selected particles. The user selects a particle by clicking it. Fade each trail with its age.
- [x] T032 [US5] Write `src/h4nb_viz/archive.py`.
  - Evidence (2026-11-08): `archive.py` reads pack archives and materializes a run into `~/.cache/h4nb-viz/runs/`. `RunIndex` lists `<stem>~<run>`. `POST /api/archive` stores an upload in the cache. The page accepts drag and drop. `pytest`: 191 passed (includes `test_run_index_lists_and_serves_archive_run`, `test_post_archive_upload`).
- [x] T033 **[Q2]** Write `src/h4nb_viz/thin.py` and the CLI `h4nb-viz thin RUN_DIR OUT_DIR [--max-points 200000] [--seed 1]` (FR-019, frame-format.md section 2). The server reads `.thin` files. Add tests.
  - Evidence (2026-11-08): `thin_run` + CLI write `.thin` and copy the run records. `list_frames` prefers `.thin`. The API sets `thin: true` and serves frames of size k. Tests in `tests/test_thin.py` (including `test_server_reads_thin_run`).

## Phase 8: Compare, ParaView, desktop (Phase 3)

- [ ] T034 [US4] Support several selected runs. Add D7 (η scan from `study.dat`) and D8 (D1 of each run). Show the 3D view of two runs side by side with one camera.
- [ ] T035 [P] Add the D6 GPU benchmark plot from `bench.dat`.
- [ ] T036 [P] Add V5, a density map (2D log histogram, `inferno`), in a WebGL texture. Add a server PNG fallback for browsers without WebGL 2.
- [ ] T037 [P] Add P4 (h/r) and P5 (r vs v_r).
- [ ] T038 [P] Write `src/h4nb_viz/paraview.py`. Add `POST /api/runs/{run}/paraview` and the CLI `h4nb-viz export-paraview RUN_DIR OUT_DIR` (FR-016). Add a test that parses the `.vtp` XML and the appended data.
- [ ] T039 **[Q3]** Build a Tauri 2 wrapper in `tools/h4nb-viz/desktop/`. The wrapper starts `h4nb-viz serve` as a sidecar (research.md R8). If Pavlo selects no Rust toolchain, use `pywebview` instead.
- [ ] T040 Write a Playwright smoke test. Open the page on a fake run. Wait for the first frame. Check that the canvas has non-black pixels. Record 2 s of video. Check that the export file exists.

## Dependencies

- Phase 1 → Phase 2 → Phases 3, 4 and 5 (MVP). In one session, do Phase 3 before Phases 4 and 5. Or run them in parallel with different agents: T010–T014 for the page, T015–T018 for the export, and T019 for the plots.
- Phase 6 needs specs/002 on `main` (metric names) and T008.
- T021 and T022 use the fixture `fake_prometheus` of T024. Write T024 first, even though T024 is marked [P].
- Phases 7 and 8 need the MVP.

## Parallel work for agents

- Agent A: T004–T009 (server, Python).
- Agent B: T010–T014 (3D page) against the contract, with the fake run from Agent A.
- Agent C: T015–T019 (export, card, plots) after T010.
