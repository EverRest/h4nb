# Implementation Plan: Visualization of run results (h4nb-viz)

**Branch**: `main` (specs only; the code is written later) | **Date**: 2026-11-08 | **Spec**: [spec.md](spec.md)

**Input**: `specs/003-run-visualization/spec.md`. Pavlo's requests of 2026-11-08: simple, very impressive, many visualizations; minimal resources; run locally; data from Grafana where possible; desktop or web app; minimal implementation work.

**Related documents**: `specs/001-hermite-nbody-lib/contracts/file-formats.md` (input formats), `specs/002-run-metrics/` (Prometheus metrics and the shared readers), the constitution `.specify/memory/constitution.md`.

## Summary

`h4nb-viz` is a local web app. A Python server (stdlib `http.server` + `numpy`) reads run files and the Prometheus API. It sends decimated float32 frames and table columns to a static page. The page renders the particles with `three.js` and the curves with `uPlot`, and records movies with `MediaRecorder`. No build step, no CDN, no framework.

The work has three phases (spec.md, Phases). The MVP gives the presentation view: 3D disk, camera presets, presentation mode, energy error, speed, run card and movie export.

## Technical Context

**Language/Version**: Python ≥ 3.10 (server). JavaScript ES2020 modules (page). No TypeScript, no bundler.

**Primary Dependencies**: `numpy` ≥ 1.24 (server). `three.js` r160 and `uPlot` 1.6.30, vendored into `web/vendor/` with their license files. Optional: `ffmpeg` on the PATH (MP4). Dev: `pytest`.

**Storage**: read only: run directories and `make pack` archives. Write: `~/.cache/h4nb-viz/` (frame cache, limit 2 GB) and the export directory.

**Testing**: `pytest` in `tools/h4nb-viz/tests/` for the server (readers, decimation, frame encoding, HTTP API, orbital elements, ParaView writer). One Playwright smoke test opens the page on a fake run and checks that the canvas is not empty. The page logic has no unit tests (keep it small).

**Target Platform**: macOS, Linux and Windows laptops. Chrome, Firefox and Safari with WebGL 2.

**Project Type**: local web app (server + static page), separate from the library.

**Performance Goals**: spec.md SC-002, SC-003.

**Constraints**: listen on `127.0.0.1` only. Read only in run directories. Offline.

**Scale/Scope**: up to 20 runs, N up to 1 048 577, up to 300 snapshots per run.

## Constitution Check

| Principle | Status | Note |
|---|---|---|
| I. Accuracy is the contract | Pass | The app shows the values of the run files. It does not compute new accuracy numbers. Orbital elements are for display only. |
| II. Speed by measurement | Pass | No change to the hot path. The app does not run on the GPU machine (except `thin`, which only reads). |
| III. Library first, small API | Pass | No change to the library or to its API. |
| IV. Deterministic results | Pass | Not affected. The decimation subset is deterministic (seed). |
| V. Simplicity | Pass | Two Python dependencies, two vendored JS files, no build step. |
| Dependency rule | Pass | The rule is for the library and the C++ tools. `h4nb-viz` is not built by CMake or Spack (same as specs/002). |
| Docs in STE | Pass | Spec, plan, tasks, README in ASD-STE100. |

## Project Structure

```text
specs/003-run-visualization/
├── spec.md
├── plan.md
├── research.md
├── contracts/
│   ├── http-api.md        # server endpoints
│   └── frame-format.md    # binary frame and thin snapshot formats
└── tasks.md

tools/h4nb-viz/
├── pyproject.toml          # entry point h4nb-viz; deps numpy; extras dev = pytest
├── README.md               # STE: install, three commands, screenshots
├── src/h4nb_viz/
│   ├── __main__.py         # CLI: serve, fake, thin, export-paraview
│   ├── readers.py          # copy of h4nb_metrics/readers.py (version note in the header)
│   ├── snapshots.py        # memmap reader, size check, decimation subset
│   ├── runs.py             # run discovery, cache of run metadata, rescan each 5 s
│   ├── tables.py           # .dat columns as float arrays (header names)
│   ├── prometheus.py       # query_range client (urllib), fallback to tables
│   ├── orbits.py           # a, e, inc relative to the central body
│   ├── archive.py          # tar.gz runs (h4nb_pack.sh)
│   ├── paraview.py         # .vtp + .pvd writer
│   ├── thin.py             # decimated snapshot writer
│   ├── fake.py             # Kepler-disk fake run
│   ├── media.py            # WebM -> MP4 with ffmpeg
│   └── server.py           # http.server handler for contracts/http-api.md
├── web/
│   ├── index.html
│   ├── app.js              # state, run list, time cursor, keys
│   ├── scene.js            # three.js points, camera presets, trails
│   ├── plots.js            # uPlot panels with tooltips
│   ├── card.js             # run card (canvas -> PNG)
│   ├── record.js           # MediaRecorder
│   ├── style.css           # dark and light themes
│   └── vendor/             # three.module.min.js, uPlot.esm.js, uPlot.min.css, LICENSE files
└── tests/
```

## Design decisions

- **DD1 Server does no rendering.** The laptop GPU renders. The server only slices arrays. This gives the low resource use that Pavlo asked for (research R1).
- **DD2 Binary frames.** float32 positions, uint32 IDs once per run. 12 bytes per point (contracts/frame-format.md).
- **DD3 Fixed subset.** Subset = the `max_points` IDs with the smallest hash (splitmix64 of id ^ seed). The count is exact, so `max_points` is a hard limit. The same particles in all frames without a lookup table; the central body is always in it and comes first (research R3).
- **DD4 Two sources for curves.** Prometheus first for runs that it has, else files. One JSON shape for the page (contracts/http-api.md `/api/runs/{run}/series`).
- **DD5 Glow without post-processing.** Additive blending of soft point sprites with a size that scales with the screen. No bloom pass, no shader library (research R2).
- **DD6 Copy, not import, of `readers.py`.** h4nb-viz does not depend on the metrics package. The metrics session agreed (2026-11-08) not to rename these functions without notice.
- **DD7 Movies in the browser.** `canvas.captureStream(30)` + `MediaRecorder`; the server converts to MP4 if `ffmpeg` exists.

## Phases and order

1. **MVP** (spec.md Phases): T001–T020 of tasks.md.
2. **Phase 2**: Prometheus, live, physics plots, trails, MP4, archives, thin.
3. **Phase 3**: compare, density map, ParaView, Tauri.

Each phase ends with a demo on a fake run and the README update.

## Open questions

spec.md Q1–Q3 are open until the implementation starts. The plan uses the proposals: Python server (Q1), `thin` in Phase 2 (Q2), desktop wrapper in Phase 3 (Q3).

## Risks

| Risk | Effect | Action |
|---|---|---|
| Safari `MediaRecorder` gives MP4, not WebM | Different file type | Accept both types on the server. |
| 1M snapshots are 64 MB; copying 100 of them is slow | Bad first experience | `thin` in Phase 2; the README tells to use `snap` with few snapshots for a first test. |
| Metric names of specs/002 change | D plots from Prometheus break | The names are in one table in `prometheus.py`; fallback to files. |
| WebGL 2 is missing | No 3D | Show plots only and a message. |
