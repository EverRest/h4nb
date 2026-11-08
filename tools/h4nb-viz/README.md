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

The server prints a link with a token, and the browser opens it. The token is needed for every request except the page itself, so other programs cannot read the runs or write files. Select the run `demo` in the list on the left.

## Commands

| Command | Use |
|---|---|
| `h4nb-viz fake OUT_DIR [--n 20000] [--snaps 60] [--t-end 6.3125]` | Write a fake run. Use it to test the page. |
| `h4nb-viz serve ROOT [--port 8820] [--export-dir DIR] [--no-browser]` | Serve the runs under ROOT. If ROOT is a run, it is listed too. |

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

Serve the directory that holds the runs. Reading a run from an archive of `tools/h4nb_pack.sh` is not supported yet.

## Resource use

- The server reads one array of a snapshot at a time. It does not load the whole snapshot.
- The server sends at most 200 000 particles for each frame by default.
- The page keeps at most 64 frames in memory.
- The server writes only into the export directory.
