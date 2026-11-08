---
description: "Task list for h4nb-viz: local web app for the visualization of run results"
---

# Tasks: Visualization of run results (h4nb-viz)

**Input**: `specs/003-run-visualization/` (spec.md, plan.md, research.md, contracts/).

**Prerequisites**: none in the library. Phase 2 tasks with Prometheus need `specs/002-run-metrics` (exporter and compose stack) to exist.

**Tests**: `pytest` tasks are part of each phase. Run `pytest tools/h4nb-viz/tests` before a task is marked done. The library tests (`make test`) do not change.

**Rules for all tasks**:

- Write all text (README, comments, help text) in ASD-STE100.
- Change files only in `tools/h4nb-viz/` and `specs/003-run-visualization/` (spec SC-001). Do not change `src/`, `include/`, `tests/`, `CMakeLists.txt`, `tools/h4nb-metrics/`.
- Do not commit or push unless Pavlo asks.
- A task marked **[Q1]**, **[Q2]** or **[Q3]** depends on an open question of spec.md. Ask Pavlo before it starts. If Pavlo selects "no" for Q1 (no Python), stop and ask for a new plan.
- Read the contract before a task that implements it. Where the code and the contract differ, change the contract first, in the same change.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (a different file, no dependency on an open task).
- **[Story]**: the user story in spec.md (US1 to US6).

---

## Phase 1: Setup

- [ ] T001 **[Q1]** Create `tools/h4nb-viz/pyproject.toml` (name `h4nb-viz`, Python ≥ 3.10, dependency `numpy>=1.24`, extra `dev = ["pytest"]`, entry point `h4nb-viz = h4nb_viz.__main__:main`) and the empty package layout of plan.md Project Structure.
- [ ] T002 [P] Vendor `three.js` r160 (`three.module.min.js`) and `uPlot` 1.6.30 (`uPlot.esm.js`, `uPlot.min.css`) into `tools/h4nb-viz/web/vendor/` with their LICENSE files and a `VERSIONS.txt` (version, source URL, sha256).
- [ ] T003 [P] Copy `tools/h4nb-metrics/src/h4nb_metrics/readers.py` to `tools/h4nb-viz/src/h4nb_viz/readers.py`. Add a header comment with the source commit. If specs/002 is not on `main` yet, write the same functions (`parse_config_used`, `parse_run_info`, `parse_header`, `parse_row`, `snapshot_header`) from `specs/001-hermite-nbody-lib/contracts/file-formats.md`.

---

## Phase 2: Foundational (server core)

**⚠️ CRITICAL**: finish this phase before the user-story phases.

- [ ] T004 `src/h4nb_viz/fake.py` + CLI `h4nb-viz fake OUT_DIR [--n 20000] [--snaps 60] [--t-end 6.3125]`: Kepler disk around a central body (m = 1), small random e and inc, Keplerian advance for each snapshot. Write v1 snapshots `snap_%06d.snap`, `snap_final.snap`, `energy.dat`, `momentum.dat`, `timesteps.dat`, `performance.dat`, `energy_periods.dat`, `config.used`, `run_info.txt` with the headers of file-formats.md. Plausible values (energy error random walk near 1e-10). If the specs/002 generator writes snapshots, reuse its table writer.
- [ ] T005 `src/h4nb_viz/snapshots.py`: v1 reader with `numpy.memmap` (one array at a time), size check (skip a file that is still being written), and the decimation subset of plan.md DD3 / research.md R3 (cache per run, seed, central body first).
- [ ] T006 [P] `src/h4nb_viz/tables.py`: read a `.dat` table (or `.dat.tmp` when `.dat` is missing) to `numpy` columns by header name; ignore a truncated last line; the name table of contracts/http-api.md.
- [ ] T007 `src/h4nb_viz/runs.py`: find runs under the root (a directory with `config.used` or a snapshot or `energy.dat[.tmp]`), run names, `state` rules of contracts/http-api.md, rescan at most each 5 s.
- [ ] T008 `src/h4nb_viz/server.py` + CLI `h4nb-viz serve ROOT [--port 8820] [--export-dir] [--no-browser]`: `http.server.ThreadingHTTPServer` on `127.0.0.1`; endpoints `/`, `/web/...`, `/api/status`, `/api/runs`, `/api/runs/{run}`, `/ids`, `/frames/{index}`, `/series` with `source=files` (contracts/http-api.md, frame-format.md section 1). Open the browser unless `--no-browser`.
- [ ] T009 [P] Tests: `tests/test_snapshots.py` (round trip with the fake run, partial read, subset stays the same over frames and contains the central body), `tests/test_tables.py` (header names, truncated line, `.tmp` fallback), `tests/test_server.py` (start on a free port, each MVP endpoint, frame header bytes, 404 for an unknown run).

---

## Phase 3: User Story 1 - Show a run in a presentation (P1) 🎯 MVP

**Goal**: 3D disk with glow, time playback, camera presets, presentation mode.

**Independent Test**: `h4nb-viz fake demo && h4nb-viz serve demo`; select the run; press `P`.

- [ ] T010 [US1] `web/index.html`, `web/style.css`, `web/app.js`: layout (run list left, 3D view centre, plots below, status bar), dark and light themes (FR-011), time slider, play and pause, keys Space, `P`, `←`/`→` (frame step), `T` (theme).
- [ ] T011 [US1] `web/scene.js`: `THREE.Points` with a soft sprite and additive blending (research.md R2); frame loader with a cache of `cache_frames` frames and prefetch of the next frames (FR-010); `OrbitControls`.
- [ ] T012 [US1] `web/scene.js`: camera presets top, edge and fly-around (slow orbit, default for `P`) (V2).
- [ ] T013 [US1] Color modes speed and radius with a color bar (V3, MVP part). The page computes them from `pos` and `vel` of the frame. Add `inferno` as a 256×1 texture.
- [ ] T014 [US1] Presentation mode (V6): full screen, controls hidden, autoplay, loop, small run name and time in a corner.

---

## Phase 4: User Story 3 - Export media for slides (P1) 🎯 MVP

- [ ] T015 [US3] `web/record.js`: "Record" button; `canvas.captureStream(30)` + `MediaRecorder`; size 1920×1080 (resize the canvas during the recording); send the file to `POST /api/export` (research.md R5).
- [ ] T016 [US3] `POST /api/export` in `server.py` with the `Origin` check; write into the export directory. MP4 conversion is Phase 2 (T026).
- [ ] T017 [P] [US3] `web/card.js`: run card S1 from `/api/runs/{run}` (N, t_end, GPU, devices or ranks, wall time, final energy error, commit); PNG export at 2× scale (S3).
- [ ] T018 [P] [US3] PNG export of the 3D view (`preserveDrawingBuffer` only while exporting) and of each plot (S3).

---

## Phase 5: Accuracy and speed plots (P1) 🎯 MVP

- [ ] T019 [US1] `web/plots.js`: uPlot panels D1 (energy error, log y, W_diss as a second series) and D5 (pairs/s, progress) from `/series`; tooltip with the `origin` of each series (FR-014); the time cursor of the 3D view as a vertical line; a click on a plot moves the 3D view to the nearest frame.
- [ ] T020 [US1] `tools/h4nb-viz/README.md` (STE): install (`pip install -e tools/h4nb-viz`), the three commands of SC-005, keys, where the exports go, how to copy snapshots from the GPU machine (`rsync`, `make pack --snap`), resource use. Add one line for h4nb-viz to the documentation index (`README.md` tools list).

**Checkpoint**: MVP done. Demo on a fake run with N = 1 048 577 (check SC-003) and N = 20 000.

---

## Phase 6: User Story 2 - Live run with data from Grafana (P1, Phase 2)

- [ ] T021 [US2] `src/h4nb_viz/prometheus.py`: `query_range` with `urllib` (research.md R6), join with `h4nb_sim_time`, name table of contracts/http-api.md; `--prometheus URL` and `--grafana URL` options; `prometheus_ok` in `/api/status`.
- [ ] T022 [US2] `/series?source=auto|prometheus|files`; mark `in_prometheus` in `/api/runs` (query `h4nb_run_info{run=...}` once per rescan).
- [ ] T023 [US2] Live update in the page: refresh `/series` each 15 s and the frame list each 5 s for a `running` run; status bar shows the sources; link "Open in Grafana" when `grafana_url` is set.
- [ ] T024 [P] [US2] Tests: `tests/test_prometheus.py` with a fake Prometheus (`http.server` that returns fixed `query_range` JSON); fallback to files when it is down.
- [ ] T025 [US2] Send a message to the specs/002 session: request the Grafana data link "Open in h4nb-viz" (`http://127.0.0.1:8820/#run=${run}`). Do not edit `tools/h4nb-metrics/`.

## Phase 7: More views and media (Phase 2)

- [ ] T026 [P] [US3] `src/h4nb_viz/media.py`: WebM (or Safari MP4) to MP4 with `ffmpeg` (research.md R5); `ffmpeg` in `/api/status`; the page shows the hint when it is missing.
- [ ] T027 [P] `src/h4nb_viz/orbits.py` + `/derived` + `/hist` (research.md R7); tests with circular and eccentric two-body orbits (e and inc to 1e-6).
- [ ] T028 Color modes e, inc, mass, ID (V3 full) from `/derived`.
- [ ] T029 Plots P1 (Σ(r)), P2 (animated e and inc histograms), P3 (a–e plane) in `web/plots.js`.
- [ ] T030 D2, D3, D4 panels.
- [ ] T031 V4 orbit trails: ring buffer of the last 64 positions for up to 200 selected particles; click to select; fade with age.
- [ ] T032 [US5] `src/h4nb_viz/archive.py`: runs from `h4nb_pack.sh` archives (FR-015), snapshots read from the tar member with an offset (no unpack when the member is not compressed separately; else extract into the cache); drag and drop of an archive onto the page (`POST` upload into the cache).
- [ ] T033 **[Q2]** `src/h4nb_viz/thin.py` + CLI `h4nb-viz thin RUN_DIR OUT_DIR [--max-points 200000] [--seed 1]` (FR-019, frame-format.md section 2); the server reads `.thin` files; tests.

## Phase 8: Compare, ParaView, desktop (Phase 3)

- [ ] T034 [US4] Several selected runs: D7 (η scan from `study.dat`), D8 (D1 of each run), side by side 3D with one camera.
- [ ] T035 [P] D6 GPU benchmark plot from `bench.dat`.
- [ ] T036 [P] V5 density map (2D log histogram, `inferno`) in a WebGL texture; server PNG fallback for no WebGL 2.
- [ ] T037 [P] P4 (h/r) and P5 (r vs v_r).
- [ ] T038 [P] `src/h4nb_viz/paraview.py` + `POST /api/runs/{run}/paraview` + CLI `h4nb-viz export-paraview RUN_DIR OUT_DIR` (FR-016); test that parses the `.vtp` XML and the appended data.
- [ ] T039 **[Q3]** Tauri 2 wrapper in `tools/h4nb-viz/desktop/` with `h4nb-viz serve` as a sidecar (research.md R8); or `pywebview` if Pavlo selects no Rust toolchain.
- [ ] T040 Playwright smoke test: open the page on a fake run, wait for the first frame, check that the canvas has non-black pixels; record 2 s and check that the export file exists.

## Dependencies

- Phase 1 → Phase 2 → Phases 3, 4, 5 (MVP; 3 before 4 and 5 in one session, or in parallel by different agents: T010–T014 page, T015–T018 export, T019 plots).
- Phase 6 needs specs/002 on `main` (metric names) and T008.
- Phase 7 and 8 need the MVP.

## Parallel work for agents

- Agent A: T004–T009 (server, Python).
- Agent B: T010–T014 (3D page) against the contract, with the fake run from Agent A.
- Agent C: T015–T019 (export, card, plots) after T010.
