# h4nb-metrics

h4nb-metrics shows the output of `h4nb_run` in Grafana.

It reads the files of a run. It does not change them. It does not link to `libh4nb`. It does not need a GPU.

The specification is in `specs/002-run-metrics/`.

## Install

Use Python 3.8 or later.

```text
pip install -e tools/h4nb-metrics
```

For the tests:

```text
pip install -e "tools/h4nb-metrics[test]"
python -m pytest -q
```

## Commands

| Command | Use |
|---|---|
| `h4nb-metrics serve PATH...` | Start the exporter on `127.0.0.1:9810`. |
| `h4nb-metrics dump PATH...` | Print the metrics once and exit. Use it to check the exporter. |
| `h4nb-metrics backfill PATH...` | Write the full curves of finished runs. Add `--load` to load them into Prometheus. |
| `h4nb-metrics fake-run OUT_DIR` | Write a fake run. Use it without a GPU. |

`PATH` is a run directory, a parent directory, or a `h4nb_logs_*.tar.gz` archive.

## Start Grafana and Prometheus

Use Docker Compose 2.24.0 or later for the Linux file only (see below).

```text
docker compose up -d
```

Open <http://localhost:3000>. The dashboard "h4nb runs" is the home dashboard. The dashboard "h4nb past runs" is in the folder "h4nb".

Prometheus runs on `127.0.0.1:9090`. Grafana runs on `127.0.0.1:3000`.

### Change the host ports

Set these variables before `docker compose up`. Each variable has a default.

| Variable | Default | Use |
|---|---|---|
| `GRAFANA_PORT` | 3000 | Host port of Grafana. |
| `PROMETHEUS_PORT` | 9090 | Host port of Prometheus. |
| `H4NB_VIEWER_PORT` | 8820 | Port of the h4nb-viz link in the dashboards. Set it before you run `build_dashboards.py`. |

The container ports do not change. The ports stay on `127.0.0.1`.

Example, if port 3000 is busy:

```text
GRAFANA_PORT=3100 docker compose up -d
```

Open <http://localhost:3100>. The Linux file uses the same variables for the listen address.

On Linux, use the second compose file:

```text
docker compose -f docker-compose.yml -f docker-compose.linux.yml up -d
```

## Three network setups

1. **Grafana on your machine, exporter on the cluster.** Start `h4nb-metrics serve` on the login node. Open an SSH tunnel with `ssh -N -L 9810:127.0.0.1:9810 user@login`. Run `docker compose up` on your machine.
2. **Everything on one server.** Run the exporter and `docker compose up` on the server. Open an SSH tunnel to Grafana with `ssh -N -L 3000:127.0.0.1:3000 user@server`.
3. **No connection during the run.** Copy the run directories or get a `make pack` archive. Run `backfill` on your local machine.

## Live use

Start the exporter on the run directories or on a parent directory:

```text
h4nb-metrics serve ~/runs/eta1 ~/runs/eta2
```

Prometheus scrapes the exporter every 15 s. A new run directory appears without a restart. The exporter searches again at most every 10 s.

## Backfill

Use backfill for a run that Prometheus did not watch:

```text
h4nb-metrics backfill h4nb_logs_host.tar.gz -o backfill/run.om --load
```

The `-o` file must be in the `backfill/` directory of this package. With `--load`, the command:

1. Stops the `prometheus` container.
2. Runs `promtool tsdb create-blocks-from openmetrics` on the Prometheus data volume.
3. Starts the `prometheus` container.

Backfilled series have the label `origin="backfill"`. Live series have no `origin` label.

## Fake run

```text
h4nb-metrics fake-run demo/run1 --t-end 6.3125 --interval 1
h4nb-metrics serve demo
```

Options: `--fail-at T` stops with NaN (state "stopped early"). `--hang-at T` stops writing (state "stalled"). `--instant` writes without waiting.

## Effect on the library and the server

- The library does not change. No file in `src/`, `include/`, `tests/` or `CMakeLists.txt` changes.
- The simulation does not slow down. The exporter reads files written by another process.
- In one measurement (2026-11-08, 20 fake runs, 8 scrapes at 15 s), the exporter used 0.24 s of CPU time in 2 minutes and about 21 MB of memory. The measurement used `ps -o cputime=,rss=` on the process before and after the scrapes.
- The exporter needs Python and `prometheus_client`. It does not need Docker.

## Dashboards

- **h4nb runs** (live): state, progress, time to end, energy error, momentum, time steps, speed and the run record.
- **h4nb past runs** (backfill and watched runs): run list, final values, curves against simulation time.

Each panel has a tooltip. The tooltip text is in `specs/002-run-metrics/contracts/dashboard.md`.

The run record table has the link "Open in h4nb-viz". The link points to the viewer of `specs/003-run-visualization/` at `http://127.0.0.1:8820`. That viewer is not built yet.

## Files

- `src/h4nb_metrics/`: the package.
- `grafana/build_dashboards.py`: writes the two dashboard JSON files. Run it after a change.
- `prometheus/`: the scrape configuration. `prometheus.yml` uses `host.docker.internal`. `prometheus-linux.yml` is for the Linux file.
- `docker-compose.yml`, `docker-compose.linux.yml`: Prometheus and Grafana.
- `tests/`: `python -m pytest -q`. The tests need no GPU and no Docker.
