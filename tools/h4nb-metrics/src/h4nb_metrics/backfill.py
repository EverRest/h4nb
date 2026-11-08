"""Backfill: all rows of finished runs in the OpenMetrics format with time stamps (spec FR-016, FR-017;
contracts/metrics.md section 8). promtool tsdb create-blocks-from openmetrics reads the output."""
from __future__ import annotations

import bisect
import math
from typing import Dict, Iterable, List, Optional, TextIO, Tuple

from .metrics import COUNTER, METRICS
from .runs import ROW_GAUGES, STATE_FINISHED, STATE_STALLED, STATE_STOPPED, Run, RunSet, row_metrics

Labels = Dict[str, str]


def fmt_value(v: float) -> str:
    if math.isnan(v):
        return "NaN"
    if math.isinf(v):
        return "+Inf" if v > 0 else "-Inf"
    return repr(float(v))


def fmt_labels(labels: Labels) -> str:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

    return "{" + ",".join('%s="%s"' % (k, esc(str(v))) for k, v in labels.items()) + "}"


class Timeline:
    """Maps a simulation time to a wall-clock time stamp (metrics.md, "Backfill time stamps")."""

    def __init__(self, run: Run, energy_times: List[float]):
        self.start = run.start_timestamp()
        end_mtime = run.tails["energy.dat"].mtime or None
        if self.start is None:  # No start_utc: use the time of config.used.
            st = run.source.stat("config.used")
            self.start = st.mtime if st else (end_mtime or 0.0)
        self.perf_times: List[float] = []
        self.perf_wall: List[float] = []
        acc = 0.0
        for row in run.rows.get("performance.dat", []):
            w = row.get("wall_s", 0.0)
            acc += w if math.isfinite(w) else 0.0
            self.perf_times.append(row.get("time", 0.0))
            self.perf_wall.append(acc)
        self.even: Optional[Tuple[float, float]] = None
        if not self.perf_times and energy_times:
            t_last = energy_times[-1] or 1.0
            span = max(0.0, (end_mtime or self.start) - self.start)
            self.even = (t_last, span)

    def stamp(self, t: float) -> float:
        if self.even is not None:
            t_last, span = self.even
            return self.start + span * (t / t_last if t_last else 0.0)
        i = bisect.bisect_right(self.perf_times, t * (1 + 1e-12) + 1e-300)
        return self.start + (self.perf_wall[i - 1] if i > 0 else 0.0)


class FullRun(Run):
    """A run with all rows kept (the live exporter keeps only the last row of each table)."""

    def __init__(self, label: str, source):
        self.rows: Dict[str, List[Dict[str, float]]] = {}
        super().__init__(label, source)

    def _reset(self, name: str) -> None:
        super()._reset(name)
        self.rows.pop(name, None)

    def _add(self, name: str, row: Dict[str, float]) -> None:
        super()._add(name, row)
        self.rows.setdefault(name, []).append(row)


def run_series(run: FullRun) -> Dict[str, List[Tuple[Labels, float, float]]]:
    """metric -> [(extra labels, value, time stamp in s)] for one run."""
    out: Dict[str, List[Tuple[Labels, float, float]]] = {}

    def put(name: str, labels: Labels, value: Optional[float], ts: float) -> None:
        if value is not None:
            out.setdefault(name, []).append((labels, float(value), round(ts, 3)))

    energy = run.rows.get("energy.dat", [])
    if not energy:
        return out
    times = [r.get("time", 0.0) for r in energy]
    tl = Timeline(run, times)
    stamps = [tl.stamp(t) for t in times]
    start, end = stamps[0], stamps[-1]
    t_end = run.t_end
    if run.finished_files():
        final = STATE_FINISHED if (t_end is not None and times[-1] >= t_end * (1 - 1e-12)) else STATE_STOPPED
    else:
        final = STATE_STALLED
    info = run.info_labels()
    config = run.config_samples()
    for k, (t, ts) in enumerate(zip(times, stamps)):
        put("h4nb_run_info", info, 1.0, ts)
        for labels, v in config:
            put("h4nb_config_value", labels, v, ts)
        put("h4nb_run_state", {}, final if k == len(times) - 1 else 0, ts)
        put("h4nb_sim_time", {}, t, ts)
        put("h4nb_t_end", {}, t_end, ts)
        if t_end:
            put("h4nb_progress_ratio", {}, min(1.0, t / t_end), ts)
        put("h4nb_particles", {}, run.particles, ts)
        put("h4nb_run_start_timestamp_seconds", {}, start, ts)
        put("h4nb_run_end_timestamp_seconds", {}, end, ts)
    tables = {table for table, _, _ in ROW_GAUGES}
    for table in sorted(tables):
        sums = {"wall_s": 0.0, "block_steps": 0.0, "active": 0.0}
        for row in run.rows.get(table, []):
            ts = tl.stamp(row.get("time", 0.0))
            for metric, v in row_metrics({table: row}, run.particles):
                put(metric, {}, v, ts)
            if table == "performance.dat":
                for key in sums:
                    v = row.get(key, 0.0)
                    sums[key] += v if math.isfinite(v) else 0.0
                put("h4nb_wall_seconds", {}, sums["wall_s"], ts)
                put("h4nb_block_steps", {}, sums["block_steps"], ts)
                put("h4nb_active_updates", {}, sums["active"], ts)
    for row in run.rows.get("energy_periods.dat", []):
        put("h4nb_period_max_rel_err", {"period": str(int(row.get("period", 0)))}, row.get("max_rel_err"), end)
    return out


def write_openmetrics(runs: Iterable[FullRun], f: TextIO) -> int:
    """Writes all runs. Returns the number of samples."""
    merged: Dict[str, List[Tuple[Labels, float, float]]] = {}
    for run in runs:
        for name, samples in run_series(run).items():
            for labels, v, ts in samples:
                merged.setdefault(name, []).append((dict(run=run.label, origin="backfill", **labels), v, ts))
    n = 0
    for name, (kind, help_text) in METRICS.items():
        samples = merged.get(name)
        if not samples:
            continue
        f.write("# HELP %s %s\n# TYPE %s %s\n" % (name, help_text, name, kind))
        sample_name = name + "_total" if kind == COUNTER else name
        # One series after the other, each in time order.
        samples.sort(key=lambda s: (sorted(s[0].items()), s[2]))
        for labels, v, ts in samples:
            f.write("%s%s %s %s\n" % (sample_name, fmt_labels(labels), fmt_value(v), repr(ts)))
            n += 1
    f.write("# EOF\n")
    return n


def load_runs(paths: List[str], max_depth: int = 2) -> List[FullRun]:
    rs = RunSet(paths, max_depth, rescan=0.0)
    rs.refresh()  # Finds the labels. Then the runs are read again with all rows.
    out = []
    for label, run in sorted(rs.runs.items()):
        full = FullRun(label, run.source)
        full.update()
        out.append(full)
    return out
