# Feature Specification: Run metrics exporter and Grafana dashboard (h4nb-metrics)

**Feature Directory**: `specs/002-run-metrics`

**Created**: 2026-11-08

**Status**: Draft

**Input**: User request (Pavlo, 2026-11-08): "Expose the data of h4nb runs for Prometheus and Grafana. Do not change the library. Tell me the effect on performance, on the library size and on the server. Every widget and every metric must have a reason and a tooltip on the widget. Only expose the data."

## Summary

`h4nb-metrics` is a separate Python package in `tools/h4nb-metrics/`. It reads the output files of `h4nb_run`. It exposes their values as Prometheus metrics on an HTTP port. A Grafana dashboard shows these metrics. A `docker-compose.yml` starts Prometheus and Grafana with the dashboard already loaded.

The package only reads files. It does not link to `libh4nb`. It does not use CUDA, MPI or a GPU. It does not write into a run directory.

## Effect on the library, the performance and the server

- **Library**: no change. No source file in `src/`, `include/`, `tests/` or `CMakeLists.txt` changes. No new build dependency. The binary size and the step time stay the same.
- **Simulation performance**: no effect. `h4nb_run` already writes the `.dat` files at each `diag` time. The exporter reads these files from another process. The exporter does not lock the files.
- **Server**: the exporter is one Python process. It reads only the bytes that were added since the last scrape. It reads only the 32-byte header of a snapshot. The expected load is less than 1 % of one CPU core and less than 50 MB of memory for 20 runs. The exporter can run on a login node, on a workstation, or on the Mac with a copy of the run directories. Prometheus and Grafana run in containers on a different machine. They do not need to run on the cluster.
- **Python dependencies**: `prometheus_client` only (run time). `pytest` for the tests. They are in `tools/h4nb-metrics/pyproject.toml`. Spack and CMake do not know them.

## Live data and past runs

- **Live data**: the dashboard shows a running simulation in near real time. The delay is at most one `diag` interval (the run writes the files once in each interval) plus one scrape interval (15 s). Grafana refreshes each 15 s.
- **History of a watched run**: Prometheus keeps each scraped value. A run that Prometheus watched while it ran stays on the dashboard with its full curves for the retention time (5 years in `docker-compose.yml`, FR-019). Select a past time range in Grafana to see it.
- **A run that Prometheus did not watch** (for example a run in a `make pack` archive from the cluster): the exporter gives only the last values. To see the full curves, load the run with `h4nb-metrics backfill` (User Story 4). The dashboard "h4nb past runs" shows these runs.
- **Network**: for live data, Prometheus must reach the exporter port. There are three setups:
  1. **Grafana on the user's machine, exporter on the server** (recommended for a cluster). Start the exporter on the login node. Open an SSH tunnel: `ssh -N -L 9810:127.0.0.1:9810 user@login`. Run `docker compose up` on the user's machine. Prometheus scrapes `host.docker.internal:9810`. The server needs only Python and `prometheus_client`. It does not need Docker.
  2. **Everything on the server** (for a workstation with Docker, for example the RTX 4070 Ti machine). Run the exporter and `docker compose up` on the server. Open an SSH tunnel to Grafana: `ssh -N -L 3000:127.0.0.1:3000 user@server`. Open `http://localhost:3000` in the local browser. Grafana and Prometheus listen on `127.0.0.1` only, so the tunnel is the only access.
  3. **No connection during the run**. Copy the run directories with `rsync` at an interval, or get a `make pack` archive. Run the exporter or the backfill on the local machine.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Watch a running simulation (Priority: P1)

A researcher starts a long run on the GPU machine. The researcher opens Grafana and sees the progress, the time to the end, the energy error and the speed. The researcher does not log in to the machine and does not read the `.dat` files by hand.

**Why this priority**: A 1M-particle run takes days (research.md R6). An energy error that grows, or a run that stops, must be seen early. This is the main reason for the feature.

**Independent Test**: Start the fake-run generator (FR-012) in a directory. Start the exporter on the directory. Start the compose stack. Open the dashboard. The panels show values. The values change while the generator writes.

**Acceptance Scenarios**:

1. **Given** a run that writes `energy.dat.tmp`, **When** the exporter is scraped, **Then** `h4nb_sim_time` and `h4nb_energy_rel_err` have the values of the last complete line.
2. **Given** a run whose files did not change for longer than `stale_after`, **When** the exporter is scraped, **Then** `h4nb_run_state` is 3 (stalled).
3. **Given** a run that ended at `t_end`, **When** the exporter is scraped, **Then** `h4nb_run_state` is 1 (finished) and `h4nb_progress_ratio` is 1.

---

### User Story 2 - See several runs at the same time (Priority: P1)

A researcher runs an η scan or a scaling series. The researcher gives one parent directory to the exporter. The dashboard shows each run as one series. The researcher selects runs with the `run` variable.

**Why this priority**: Most work is a series of runs (convergence, scaling with 1, 2, 4, 8 ranks).

**Independent Test**: Make three fake runs in one parent directory. Start the exporter on the parent directory. Each run has its own `run` label. A new run directory appears in the metrics without an exporter restart.

**Acceptance Scenarios**:

1. **Given** a parent directory with three run directories, **When** the exporter is scraped, **Then** each metric has three series with different `run` labels.
2. **Given** a new run directory that appears after the start, **When** the next scrape occurs, **Then** the new run is in the metrics.

---

### User Story 3 - Look at the results of a finished run from an archive (Priority: P3)

A researcher gets an archive of `make pack` from the cluster. The researcher gives the archive to the exporter. The dashboard shows the final values of each run in the archive.

**Why this priority**: It is useful, but the compare plots of a later feature give more for finished runs. Prometheus records the values against the wall clock of the scrape, so a finished run shows as constant lines.

**Independent Test**: Pack a fake run with `tools/h4nb_pack.sh`. Start the exporter on the archive. The final values are in the metrics.

**Acceptance Scenarios**:

1. **Given** an `h4nb_logs_*.tar.gz` archive, **When** the exporter is scraped, **Then** each run directory in the archive is one `run` label, and the values are the values of the last lines.

---

### User Story 4 - Look at past runs on a separate dashboard (Priority: P2)

A researcher gets a `make pack` archive from the cluster. Prometheus did not watch these runs. The researcher loads the archive with one command. The dashboard "h4nb past runs" shows the full curves of each run. The researcher can also plot the energy error against the simulation time.

**Why this priority**: The GPU runs are on the cluster. Prometheus often cannot reach the cluster while a run is active. The archive is then the only source of the data. The user asked for a separate dashboard for old runs (2026-11-08).

**Independent Test**: Make a fake run. Pack it with `tools/h4nb_pack.sh`. Run `h4nb-metrics backfill` on the archive. Open "h4nb past runs". Select the run. The panels show curves that start at `start_utc` of the run.

**Acceptance Scenarios**:

1. **Given** an archive with two runs, **When** the user runs the backfill, **Then** the run list of "h4nb past runs" contains both runs with their start and end times.
2. **Given** a backfilled run, **When** the user selects it, **Then** the time series have one point for each line of the `.dat` files, at the time stamp of section "Backfill time stamps" in `contracts/metrics.md`.
3. **Given** a backfilled run, **When** the user opens the panel "Energy error against simulation time", **Then** the x axis is the simulation time, not the wall clock.
4. **Given** the same archive, **When** the user runs the backfill two times, **Then** the data is not doubled.

---

### Edge Cases

- The last line of a `.dat` file is not complete, because `h4nb_run` writes it at this moment. The exporter ignores the incomplete line. It reads the line at the next scrape.
- `h4nb_run` renames `X.dat.tmp` to `X.dat` at the end. The exporter continues to read the same data. The values do not jump back.
- A run stops with exit code 2 or 3. `h4nb_run` publishes the partial `.dat` files. The exporter reports state 2 (stopped early), because the last time is less than `t_end`.
- A value is `nan` or `inf` in a `.dat` file. The exporter exposes it as NaN. Grafana shows a gap. The run state panel shows the stop.
- An MPI run stops with an error on another rank. The files stay `*.dat.tmp` (file-formats.md section 4). The exporter reports state 3 (stalled) after `stale_after`.
- A file is removed or replaced by a shorter file. The exporter reads the file again from the start.
- `performance.dat` does not exist (`perf=0`). The performance metrics are not exposed for the run. The other metrics are exposed.
- A directory has no `config.used`. It is not a run directory. The exporter ignores it.
- A header line has other columns than the contract. The exporter uses the column names of the header line. It does not use fixed positions. An unknown column is ignored.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The package MUST only read files. It MUST NOT write, rename, lock or remove a file in a run directory or an archive.
- **FR-002**: The package MUST NOT change files in `src/`, `include/`, `tests/`, `CMakeLists.txt`, `cmake/` or `spack/`. It MUST NOT add a dependency to the library build.
- **FR-003**: The exporter MUST accept one or more paths. A path is a run directory, a parent directory, or an `h4nb_logs_*.tar.gz` archive. A run directory is a directory that contains `config.used` written by `h4nb_run`. The exporter MUST search a parent directory to the depth `max_depth` (default 2).
- **FR-004**: The exporter MUST search the paths again at each scrape, but not more often than each `rescan` seconds (default 10). A new run directory MUST appear without a restart.
- **FR-005**: The exporter MUST read `X.dat` when it exists, else `X.dat.tmp`. It MUST read only the bytes that were added after the last read. It MUST ignore an incomplete last line. It MUST read the file again from the start when the file is shorter than before or has a different inode.
- **FR-006**: The exporter MUST find the columns by the names in the `#` header line (file-formats.md section 3).
- **FR-007**: The exporter MUST expose the metrics in `contracts/metrics.md`, with the names, units, labels and sources given there.
- **FR-008**: The exporter MUST get the particle count N without a full read of a snapshot. Order: the key `n` in `config.used`, then the header of the first `snap_*.snap` file in the run directory, then the header of the `ic` file when it is a `.snap` file. When none of these is available, `h4nb_particles` is not exposed.
- **FR-009**: The exporter MUST listen on `127.0.0.1:9810` by default. The user can set the address and the port. Reason: a login node is shared. The exporter must not be open to the network without a decision of the user.
- **FR-010**: The repository MUST contain a Grafana dashboard JSON file. It MUST contain the panels in `contracts/dashboard.md`. Each panel MUST have the description text of the contract. Grafana shows this text as the tooltip of the `i` icon in the panel title.
- **FR-011**: The repository MUST contain a `docker-compose.yml` with Prometheus and Grafana. Grafana MUST load the data source and the dashboard by provisioning. The user MUST not need a manual step in the Grafana UI.
- **FR-012**: The package MUST contain a fake-run generator. It writes files in the formats of file-formats.md, line by line, at a set speed. Reason: the Mac and the container have no GPU. The dashboard must be checked without a GPU.
- **FR-013**: An error in one run (a file that cannot be read, a bad line) MUST NOT stop the exporter or remove the metrics of other runs. The exporter MUST count the errors in `h4nb_exporter_read_errors_total`.
- **FR-014**: The package MUST run with Python 3.8 or later. Reason: cluster login nodes often have an old system Python.
- **FR-015**: All documentation, dashboard titles and dashboard descriptions MUST be in ASD-STE100 English.
- **FR-016**: The package MUST provide `h4nb-metrics backfill PATH...`. It MUST write the rows of all `.dat` files of each run in the OpenMetrics text format with time stamps (`contracts/metrics.md` section 8). With `--load`, it MUST give the file to `promtool tsdb create-blocks-from openmetrics` in the Prometheus container of `docker-compose.yml`. Reason: `promtool` is the supported way to add old data to Prometheus.
- **FR-017**: Backfilled series MUST have the label `origin="backfill"`. A second backfill of the same run MUST give the same samples, so that Prometheus does not store them two times.
- **FR-018**: The repository MUST contain a second dashboard "h4nb past runs" (`contracts/dashboard.md`, part 2). It MUST have the same rules for the descriptions as FR-010.
- **FR-019**: Prometheus in `docker-compose.yml` MUST keep data for 5 years. Reason: retention removes data by its time stamp. Backfilled runs are old when they are loaded. The data of one run is a few MB.
- **FR-020**: `docker-compose.yml` MUST publish the ports of Grafana (3000) and Prometheus (9090) on `127.0.0.1` only. Prometheus MUST scrape the exporter on the host through `host.docker.internal` (on Linux with `extra_hosts: host-gateway`). Reason: a server is reached through an SSH tunnel (section "Live data and past runs"). An open port is a risk on a shared machine.

### Out of scope

- Compare plots of finished runs against simulation time (Streamlit or Jupyter).
- Export of snapshots (positions and velocities of the particles) to VTK or HDF5 for ParaView, and 3D animations. Grafana cannot show 3D particle data. The snapshot headers (N, time) are used only for metadata.
- Metrics of `h4nb_study` (`study.dat`) and `h4nb_bench` (`bench.dat`).
- Alerts (Grafana alert rules or Alertmanager).

These items can be a later feature. They do not change this feature.

### Key Entities

- **Run**: one output directory of `h4nb_run`. The `run` label is the directory name. When two runs have the same directory name, the label is the path relative to the given path.
- **Table**: one `.dat` file of a run, read by its header columns.
- **Run record**: `config.used` and `run_info.txt` of a run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `git diff` of the feature shows changes only in `tools/h4nb-metrics/`, `specs/002-run-metrics/` and the documentation index files.
- **SC-002**: With 20 fake runs that each add one line each second, the exporter uses less than 1 % of one CPU core on average with a scrape interval of 15 s, and less than 50 MB of resident memory.
- **SC-003**: A scrape of 20 runs takes less than 200 ms.
- **SC-004**: `docker compose up` and the fake-run generator show values in all panels of the dashboard within 60 s, with no manual step in Grafana.
- **SC-005**: Each panel of the dashboard has a non-empty description. A test checks this.
- **SC-006**: The tests pass with Python 3.8 and with the newest Python.
- **SC-007**: The backfill of an archive with 10 runs of 10 000 diag lines each takes less than 60 s, `promtool` included.

## Assumptions

- Prometheus records each value at the wall-clock time of the scrape. The dashboard x axis is the wall clock, not the simulation time. This is sufficient to watch a run.
- The scrape interval is 15 s. The default `diag` interval of large runs is longer than this, so the scrape does not miss a value that matters for the panels.
- Docker is available on the machine that runs Prometheus and Grafana. It is not necessary on the cluster.
