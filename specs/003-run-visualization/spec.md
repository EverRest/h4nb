# Feature Specification: Visualization of run results (h4nb-viz)

**Feature Directory**: `specs/003-run-visualization`

**Created**: 2026-11-08

**Status**: Draft

**Input**: User request (Pavlo, 2026-11-08): "Visualization is interesting for the end user and an important part of presentations. Which tools and stack? It must be very simple and very impressive. Many different visualizations."

## Summary

`h4nb-viz` is a local web app in `tools/h4nb-viz/`. The user starts it on the own laptop with one command and opens it in the browser:

```text
h4nb-viz serve ~/runs           # opens http://127.0.0.1:8820
```

The app has two parts:

- **Server**: one small Python process. It reads run files (snapshots, `.dat`, `config.used`, `run_info.txt`, `make pack` archives) and, as an option, the Prometheus HTTP API of the `h4nb-metrics` stack (specs/002). It sends compact binary data to the browser. It does no rendering.
- **Browser page**: static HTML and JavaScript. The GPU of the laptop renders the particles with WebGL. The page also draws the curves and records movies.

The app only reads. It does not link to `libh4nb`. It does not use CUDA or MPI. It does not write into a run directory. It does not run on the cluster.

## Where the data comes from

| Data | Source | Reason |
|---|---|---|
| Curves of a run that Prometheus watched (energy error, momentum, time steps, speed, progress) | Prometheus HTTP API (`/api/v1/query_range`), the same data that Grafana shows | No copy of the run is necessary. Live runs update in the app. |
| Curves of a run that Prometheus did not watch | `.dat` files on the local disk, or a `make pack` archive | Prometheus has no data for it. |
| Particles (positions, velocities, masses) | Snapshot files on the local disk (`rsync`, or `make pack --snap`) | Prometheus and Grafana do not store particle data. One snapshot of 1M particles is 64 MB. A metric for each particle is not possible. |
| Run card (GPU, N, build) | `run_info.txt` and `config.used`, or the `h4nb_run_info` metric of specs/002 | Same values, two sources. |

Grafana links to the app: the `h4nb-metrics` dashboard has a data link "Open in h4nb-viz" for each run (a change in specs/002, owned by that feature). The app links back to the Grafana dashboard of the run.

## Resource use

- **Server**: Python stdlib and `numpy` only. Snapshots are opened with `numpy.memmap`: the server reads only the arrays and the particles that the page asks for. Expected load: idle less than 1 % of one CPU core, less than 100 MB of memory; one 1M-particle snapshot decimated to 200 000 points takes less than 0.5 s.
- **Network to the browser**: positions as float32. 200 000 points = 2.4 MB per frame. The page keeps at most `cache_frames` frames (default 64) in memory.
- **Browser**: WebGL points with additive blending. 200 000 points at 60 fps on an integrated GPU (Apple M1, Intel Iris Xe).
- **Disk**: the app writes only to its cache directory (`~/.cache/h4nb-viz`, limit 2 GB, oldest first out) and to the export directory that the user selects.
- **Cluster and GPU machine**: no load. The app does not connect to them. Prometheus is queried at most once each 15 s for a live run.

## Stack

| Layer | Tool | Reason |
|---|---|---|
| Server | Python 3.10+ stdlib `http.server` + `numpy` | No web framework. Two dependencies in total. |
| File readers | `readers.py` of `h4nb-metrics` (stdlib, copied with a version note) + `numpy.memmap` for the arrays | One parser for the table headers, `config.used`, `run_info.txt` and archives in the two tools. |
| 3D | `three.js` (pinned, vendored, MIT) | WebGL point sprites, camera orbit, trails. |
| Curves | `uPlot` (pinned, vendored, MIT, about 50 KB) | Fast line plots for 10^5 points. Much smaller than Plotly. |
| Movies | Browser `MediaRecorder` → WebM; MP4 with `ffmpeg` if it is on the PATH | No extra program is necessary for a first movie. MP4 for PowerPoint. |
| Images | Canvas → PNG, uPlot → SVG | For slides and papers. |
| Desktop app (P3) | Tauri wrapper around the same page | About 10 MB, uses the system web view. Electron (about 150 MB) is not used. |

No npm, no build step: the page uses ES modules from `tools/h4nb-viz/web/vendor/`. It works without a network. Telegram (bot or mini app) is not in this feature: a phone screen is small for 3D, and a bot needs a public server.

## Visualizations

Each visualization has an ID. The app shows a tab or a panel for each ID for which the input exists. It greys out the others and tells why (for example "movies need `snap` > 0").

### Particles (from snapshots, rendered in the browser)

| ID | Name | What the user does |
|---|---|---|
| V1 | 3D disk (glow, additive blending) | Rotate, zoom, play the time series, time slider. |
| V2 | Camera presets: top view, edge view (disk thickness), slow fly-around | One click. The fly-around is the default for a presentation. |
| V3 | Color modes: speed, radius, eccentricity, inclination, mass, ID | Select in a menu. A color bar shows the scale. |
| V4 | Orbit trails of selected particles (fade with age) | Click particles or give IDs. |
| V5 | Density map (2D log density, `inferno`) | Top or edge view. |
| V6 | Presentation mode: full screen, no controls, autoplay, loop | Key `P`. |

### Physics (computed by the server from snapshots, relative to the central body)

| ID | Name |
|---|---|
| P1 | Surface density Σ(r), one line per time (color = time) |
| P2 | Distribution of eccentricity and inclination over time (animated histogram) |
| P3 | Semi-major axis vs eccentricity (a–e plane), animated |
| P4 | Disk thickness h/r vs r |
| P5 | Phase space r vs v_r |

The orbital elements use `G` from `config.used` and the mass, position and velocity of the central body (`central_id`).

### Accuracy and performance (from Prometheus, else from `.dat` files)

| ID | Name | Prometheus metric (specs/002) or file |
|---|---|---|
| D1 | Relative energy error vs time, log scale, with W_diss | `h4nb_energy_rel_err` / `energy.dat` |
| D2 | Error per reference period (bars, incomplete period marked) | `h4nb_period_max_rel_err` / `energy_periods.dat` |
| D3 | Momentum and angular momentum drift | `h4nb_momentum_rel_change`, `h4nb_angular_momentum_rel_change` / `momentum.dat` |
| D4 | Time steps dt_min, dt_mean, dt_max and r_min (close encounters) | `h4nb_dt_min`, `h4nb_dt_mean`, `h4nb_dt_max`, `h4nb_r_min` / `timesteps.dat` |
| D5 | Speed: pairs/s, active particles per block step, progress and time to the end | `h4nb_pairs_per_second`, `h4nb_active_per_block_step`, `h4nb_progress_ratio`, `h4nb_eta_seconds` / `performance.dat` |
| D6 | GPU benchmark: GFLOPS vs N, one line per device count, % of peak | `bench.dat` (file only) |
| D7 | η scan: energy error vs η, with the line of order 4 | `study.dat` (file only) |
| D8 | Run comparison: D1 of several runs on one plot | several runs |

The metric names in this table follow `contracts/metrics.md` of specs/002. If that contract changes, this table changes.

All D plots are linked to the particle view: the time cursor of the 3D view is a vertical line on each plot. A click on a plot moves the 3D view to the nearest snapshot.

### Summary and export

| ID | Name | Output |
|---|---|---|
| S1 | Run card: N, t_end, devices, GPU, wall time, final energy error, build version | PNG, SVG |
| S2 | Movie export of the current view and camera path | WebM; MP4 with `ffmpeg` |
| S3 | Image export of any view or plot | PNG (2× scale), SVG for plots |
| S4 | ParaView export (`.pvd` + `.vtp`) | Files in the export directory |

## Constitution check

- Principle "one C++ library, tools are thin clients" and the dependency rule (CUDA, C++ standard library, optional MPI) apply to the library and to the tools in `tools/*.cpp`. `h4nb-viz` does not link to the library and is not built by CMake or Spack. Its Python and JavaScript dependencies do not become dependencies of the library. specs/002 (`h4nb-metrics`) uses the same rule.
- Docs in ASD-STE100 English: this spec, the plan, the tasks and the tool README.
- Tests: `pytest` in `tools/h4nb-viz/tests/`. They are not CTest tests and do not change `make test`.

## Phases (minimal work first)

The user asked for the least work with the most effect for presentations. The work is in three phases. Each phase is usable alone.

| Phase | Content | Size (estimate) |
|---|---|---|
| **MVP** | Server (run list, frames, `.dat` tables), V1, V2, V3 (speed and radius only), V6 presentation mode, D1, D5, S1, S2 (WebM), S3, fake-run generator | about 1 500 lines (Python about 500, JavaScript about 1 000) |
| **Phase 2** | Prometheus source (FR-007), live update, D2–D4, P1–P3, V4 trails, MP4 with `ffmpeg`, archives, `h4nb-viz thin` (FR-019) | about 1 000 lines |
| **Phase 3** | D6–D8, compare, V5, P4–P5, ParaView export, Tauri desktop wrapper | about 1 000 lines |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Show a run in a presentation (Priority: P1)

A presenter runs `h4nb-viz serve ~/runs` on a laptop without a network. The presenter selects a run, presses `P`, and the disk turns slowly and plays its time evolution on full screen.

**Why this priority**: This is the main request: very simple and very impressive.

**Independent Test**: Make a fake run with the generator (FR-012). Start the app. Select the run. Press `P`. The view plays in full screen.

**Acceptance Scenarios**:

1. **Given** a run with 1M particles and 100 snapshots, **When** the user opens it, **Then** the first frame shows in less than 3 s and playback runs at 30 fps or more (SC-003).
2. **Given** a run with only `snap_final.snap`, **When** the user opens it, **Then** V1–V5 show the one frame and the time controls are hidden.
3. **Given** the presentation mode, **When** the user presses Space, **Then** the playback stops or starts.

---

### User Story 2 - Watch a live run with data from Grafana (Priority: P1)

The `h4nb-metrics` stack watches a run on the GPU machine. The user opens the app with `--prometheus http://127.0.0.1:9090`. The D plots of the run come from Prometheus and update each 15 s. When the user copies new snapshots (`rsync`), the app shows them without a restart.

**Why this priority**: The user wants to use the Grafana data and not copy the `.dat` files.

**Independent Test**: Start the fake-run generator of specs/002, the exporter and Prometheus. Start the app with `--prometheus`. D1 shows the curve and gets new points.

**Acceptance Scenarios**:

1. **Given** Prometheus is not reachable, **When** the app starts, **Then** it uses the `.dat` files and shows "Prometheus: off" in the status bar.
2. **Given** a run in Prometheus and also on the disk, **When** the user opens it, **Then** the app uses Prometheus for the live curves and the files for the particles, and the status bar shows the two sources.

---

### User Story 3 - Export media for slides (Priority: P1)

The user selects a camera preset and presses "Record". The app writes a movie of the playback. The user exports PNG images of plots and the run card.

**Why this priority**: Slides need files. A live demo can fail.

**Acceptance Scenarios**:

1. **Given** no `ffmpeg`, **When** the user records, **Then** the app writes WebM and tells that MP4 needs `ffmpeg`.
2. **Given** `ffmpeg` on the PATH, **When** the user records, **Then** the app writes MP4 (H.264, yuv420p, 1920×1080, 30 fps) that PowerPoint and Keynote play.

---

### User Story 4 - Compare runs (Priority: P2)

The user selects several runs of an η scan. D7 and D8 show one line per run. The 3D view shows two runs side by side with one camera.

**Why this priority**: η scans and scaling series are the main results of the project.

---

### User Story 5 - Open a packed archive (Priority: P2)

The user drags a `make pack` archive into the app. The app reads it without a manual unpack. Without `--snap` in the archive, only the D and S outputs are available.

---

### User Story 6 - Desktop app (Priority: P3)

The user starts "h4nb-viz" from the Dock or the Start menu. A Tauri wrapper starts the server and shows the page in a window. The function is the same as in the browser.

**Why this priority**: The browser version already does all the work. The wrapper is only for users who do not use a terminal.

### Edge Cases

- A run that is still running: the app uses `*.dat.tmp` and the snapshots that exist, and marks the run "running".
- A run that stopped after an MPI error: rank 0 files stay in `*.dat.tmp` (file-formats.md section 4). The app reads them and marks the run "stopped".
- A snapshot with a wrong magic or version: the app skips the file and shows a warning. It does not stop.
- A truncated last line in a `.dat` file: the app ignores the line.
- A snapshot that is still being written (size smaller than 32 + 64·N bytes): the app skips it until the size is correct.
- N different between snapshots (not expected): V4 and the decimation stop with an error for this run; the other views continue.
- A particle on an unbound orbit (e ≥ 1): P2 and P3 show it in a separate "unbound" bin.
- A browser without WebGL 2: the app shows V5 (density map as a PNG from the server) and the D plots only.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The app MUST only read run files and the Prometheus API. It MUST NOT write into a run directory. It writes only into its cache directory and into the export directory that the user selects.
- **FR-002**: The server MUST listen on `127.0.0.1` only, by default port 8820 (option `--port`).
- **FR-003**: The snapshot reader MUST read the v1 format of file-formats.md section 2 with `numpy.memmap`. It MUST read only the arrays and particles that a request needs.
- **FR-004**: The server MUST decimate a frame to at most `max_points` particles (default 200 000, option in the page). The subset is a fixed random set of IDs (seed in the URL), so each particle stays the same in all frames. The central body is always in the subset.
- **FR-005**: The server MUST send positions as little-endian float32 binary (`application/octet-stream`), not as JSON.
- **FR-006**: The `.dat` readers MUST use the column names from the `#` header line (reuse `readers.py` of specs/002). An unknown extra column MUST NOT be an error.
- **FR-007**: With `--prometheus URL`, the server MUST get the D curves with `query_range` and MUST query a live run at most once each 15 s. Without it, or when Prometheus is not reachable, the server MUST use the `.dat` files.
- **FR-008**: The server MUST find new runs and new snapshots in the root directory without a restart (scan at most once each 5 s).
- **FR-009**: The page MUST be static HTML and ES modules from `web/vendor/`. It MUST work without a network. It MUST NOT load files from a CDN.
- **FR-010**: The page MUST keep at most `cache_frames` frames in memory (default 64) and MUST load the next frames before they are shown.
- **FR-011**: The page MUST have two themes: dark (default, for screens and slides) and light (for papers). One colormap for density (`inferno`) and one categorical palette for lines.
- **FR-012**: The package MUST have a fake-run generator (`h4nb-viz fake OUT_DIR`) that writes a Kepler disk with snapshots and `.dat` files in the h4nb formats. If the generator of specs/002 writes snapshots, `h4nb-viz` uses it and does not add a second one.
- **FR-013**: The app MUST read `run_info.txt` and `config.used` for the run card and for `G` and `central_id`. A missing file MUST NOT be an error; the card shows "unknown".
- **FR-014**: Every plot MUST have a title, axis labels ("dimensionless", G = value) and the run name. Every panel MUST have a tooltip that tells what it shows and its data source (Prometheus metric or file).
- **FR-015**: The app MUST read `.tar.gz` archives of `tools/h4nb_pack.sh` without a manual unpack.
- **FR-016**: The ParaView export MUST write VTK XML PolyData (`.vtp`, appended raw binary, little-endian) with point data `id`, `m`, `v`, `speed`, `r`, `e`, `inc`, and one `.pvd` collection with the snapshot times.
- **FR-017**: Movie export MUST use `MediaRecorder` (WebM). When `ffmpeg` is on the PATH of the server, the server MUST convert the file to MP4 (H.264, yuv420p).
- **FR-018**: Run-time dependencies MUST be Python 3.10+, `numpy`, and the vendored `three.js` and `uPlot`. `ffmpeg` is optional.
- **FR-019**: The command `h4nb-viz thin RUN_DIR OUT_DIR` MUST write decimated snapshots (same subset rule as FR-004, float32 positions and velocities, `thin` format of contracts/frame-format.md). It needs only Python and `numpy`, so it runs on the GPU machine or a login node. The app reads thinned runs like full runs.

### Key Entities

- **Run**: one run directory (or one subdirectory of an archive): snapshots, `.dat` files, `config.used`, `run_info.txt`; and, as an option, its series in Prometheus (label `run`).
- **Frame**: the decimated particle data of one snapshot at one time.
- **Source**: where a curve comes from: Prometheus or file.

## Success Criteria *(mandatory)*

- **SC-001**: `git diff` of the feature shows changes only in `tools/h4nb-viz/`, `specs/003-run-visualization/` and the documentation index files.
- **SC-002**: The server uses less than 1 % of one CPU core when idle and less than 100 MB of memory with 20 runs.
- **SC-003**: With N = 1 048 576 and `max_points` = 200 000, the first frame shows in less than 3 s and playback runs at 30 fps or more on a laptop with an integrated GPU (Apple M1 or Intel Iris Xe).
- **SC-004**: The MP4 files play in PowerPoint (Windows and Mac), Keynote, Chrome, Firefox and Safari.
- **SC-005**: A new user sees a disk in three commands: install, `h4nb-viz fake demo`, `h4nb-viz serve demo`.
- **SC-006**: The install size (without Python and `numpy`) is less than 5 MB.

## Out of scope

- A Grafana panel plugin for 3D. Grafana has no good 3D particle panel, and a plugin is a large separate project.
- Particle data in Prometheus. It is not possible with 10^6 particles.
- A Telegram bot or mini app. It can be a later feature for notifications and still images.
- Rendering on the cluster or the GPU machine, Blender renders.
- Changes to the library or to `h4nb_run`. If a view needs new data (for example the block-step level per particle), it is a separate change request to the library.
- A hosted web server for other users.

## Assumptions

- Movies need `snap` > 0 or `snap_times`. 100–300 snapshots per run make a smooth movie.
- The disk is in the x–y plane, so "top view" is along z.
- The user copies snapshots to the laptop (`rsync` or `make pack --snap`). A 1M-particle run with 100 snapshots is 6.4 GB.

## Open questions

Pavlo decides these when the implementation starts (Pavlo, 2026-11-08). The proposal is in brackets. The plan and the tasks use the proposal and mark the affected tasks with **[Q1]**, **[Q2]** or **[Q3]**. Ask Pavlo before such a task starts.

- Q1: Python is acceptable for the server? [Yes. `h4nb-metrics` is also Python. The library rule does not apply, see Constitution check.]
- Q2: Is a decimated copy for the laptop (`h4nb-viz thin`, run on the GPU machine, 200 000 points as float32 = 2.4 MB per frame) wanted? [Yes, in Phase 2. It is small and saves copy time.]
- Q3: Is the desktop wrapper (User Story 6) wanted now? [No. Phase 3.]
