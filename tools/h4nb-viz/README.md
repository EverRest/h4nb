# h4nb-viz

h4nb-viz shows the results of `h4nb_run` in a web page on your computer.

It reads the files of a run. It does not change them. It listens on `127.0.0.1` only. It works without a network connection.

The specification is in `specs/003-run-visualization/`.

## Install

Use Python 3.10 or later. Install the package from the repository root:

```text
pip install -e tools/h4nb-viz
```

To run the tests:

```text
pip install -e "tools/h4nb-viz[dev]"
cd tools/h4nb-viz && python -m pytest
```

## Quick start

Write a fake run. It needs no GPU:

```text
h4nb-viz fake demo
```

Start the page for the run:

```text
h4nb-viz serve demo
```

The server prints a link with a token, and the browser opens it. The link works once: restart the server for a new link. The token is needed for every request except the page itself, so other programs cannot read the runs or write files. Select the run `demo` in the list on the left.

## Commands

| Command | Use |
|---|---|
| `h4nb-viz fake OUT_DIR [--n 20000] [--snaps 60] [--t-end 6.3125]` | Write a fake run. Use it to test the page. |
| `h4nb-viz serve ROOT [--port 8820] [--export-dir DIR] [--no-browser] [--prometheus URL] [--grafana URL]` | Serve the runs under ROOT. If ROOT is a run, it is listed too. `--prometheus` reads the live curves. `--grafana` adds a link to Grafana. |

## Keys

| Key | Action |
|---|---|
| Space | Play or pause |
| Left and Right arrows | One frame back or forward |
| P | Start or stop the presentation mode |
| T | Switch the dark and light theme |

The presentation mode uses the full screen. It hides the controls, plays the run in a loop and shows the run name and the time.

## Export

Use the buttons under the 3D view:

- **Record** records one playback from the first frame to the last. The movie has 1920 × 1080 pixels.
- **View PNG** saves the 3D view at 2 times the screen size.
- **Card PNG** saves the run card.
- **D1 PNG** and **D5 PNG** save one plot each.

The server writes the files into the export directory. The default is `~/h4nb-viz-exports`. Set another directory with `--export-dir`.

The movie is a WebM file. Safari writes MP4. A later version converts the file to MP4 when `ffmpeg` is on the PATH.

## Copy a run from the GPU machine

Copy the run directory with `rsync`. Include the snapshots:

```text
rsync -av gpu-host:/path/to/RUN_DIR/ ./runs/RUN_DIR/
h4nb-viz serve ./runs
```

Serve the directory that holds the runs. A `.tar.gz` of `tools/h4nb_pack.sh` in the root, or dropped onto the page, is also a run (FR-015). The name is `<archive>~<run>`. The server extracts it into `~/.cache/h4nb-viz/`.

A run made with `h4nb-viz thin` (`.thin` snapshots) is listed with `thin: true`. The server reads it like a full run (FR-019).

## Prometheus

Use `--prometheus URL` to read the curves from Prometheus. The server uses the metrics of specs/002. It joins each curve with `h4nb_sim_time`. A run that Prometheus does not have uses the files.

- `source=auto` (the default): Prometheus when the run is in Prometheus and Prometheus answers. Otherwise the files.
- `source=prometheus`: Prometheus only. The server returns 503 when Prometheus does not answer.
- `source=files`: the files only.

The page refreshes the curves of a running run every 15 s. It reads the frame list every 5 s. It reads the server status every 5 s. The status line shows `Prometheus: on`, `off` or `unknown`. Prometheus shows `off` within about 20 s after it stops. Use `--grafana URL` to show the link "Open in Grafana".

A link with `#run=<label>` opens the run whose Prometheus label is the value.

Status of the manual check (T023, 2026-11-08):

- Done (stub): the status line shows `Prometheus: on` with a stub Prometheus. It shows `off` after the stub stops. The Grafana link has its `href`. A `#run=` link with no matching label shows the no-match message. The page raises no script error in headless Chrome.
- Done (live stack of specs/002): `docker compose up` in `tools/h4nb-metrics`, `h4nb-metrics fake-run` with `--interval 1`, `h4nb-metrics serve`, then `h4nb-viz` with `--prometheus http://127.0.0.1:9090` and `--grafana http://127.0.0.1:3000`. `/api/status` had `prometheus_ok: true`. The run `live` had `in_prometheus: true`. `/series` first used the files (12 points), then Prometheus after a scrape. After `docker compose stop prometheus`, `prometheus_ok` was `false` and `/series` fell back to the files (35 points).

## Resource use

- The server reads one array of a snapshot at a time. It does not load the whole snapshot.
- The server sends at most 200 000 particles for each frame by default.
- The page keeps at most 64 frames in memory.
- The server writes only into the export directory and into `~/.cache/h4nb-viz/` (archives).
