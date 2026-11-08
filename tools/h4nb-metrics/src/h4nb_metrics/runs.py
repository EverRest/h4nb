"""Run directories: discovery, incremental reading and the current metric values (contracts/metrics.md)."""
from __future__ import annotations

import calendar
import collections
import math
import os
import time as _time
from typing import Deque, Dict, Iterable, List, Optional, Tuple

from . import readers
from .readers import DirSource, MemorySource, TABLES

STATE_RUNNING, STATE_FINISHED, STATE_STOPPED, STATE_STALLED = 0, 1, 2, 3
RECENT = 10  # Segments for the time-to-end estimate and for stale_after (metrics.md sections 5 and 6).
FLOP_PER_PAIR = 60.0  # research.md R6.

Labels = Dict[str, str]
Sample = Tuple[Labels, float]


def parse_utc(text: str) -> Optional[float]:
    try:
        return float(calendar.timegm(_time.strptime(text.strip(), "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, AttributeError):
        return None


def to_float(text: Optional[str]) -> Optional[float]:
    if text is None or text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


class TableTail:
    """Reads the new complete lines of X.dat, else of X.dat.tmp (spec FR-005, FR-006)."""

    def __init__(self, source, name: str):
        self.source, self.name = source, name
        self.inode: Optional[int] = None
        self.offset = 0
        self.rest = b""
        self.columns: Optional[List[str]] = None
        self.file: Optional[str] = None  # The file name that was read last: X.dat or X.dat.tmp.
        self.mtime = 0.0
        self.bad_lines = 0

    def pick(self) -> Tuple[Optional[str], Optional[readers.FileInfo]]:
        for n in (self.name, self.name + ".tmp"):
            info = self.source.stat(n)
            if info is not None:
                return n, info
        return None, None

    def poll(self) -> Tuple[List[Dict[str, float]], bool]:
        """New rows, and True when the file was read again from the start (the caller drops its old rows)."""
        name, info = self.pick()
        if name is None:
            return [], False
        reset = False
        # The rename of X.dat.tmp to X.dat keeps the inode. A new inode or a shorter file is a new file.
        if self.inode is not None and (info.inode != self.inode or info.size < self.offset):
            self.offset, self.rest, self.columns, reset = 0, b"", None, True
        self.inode, self.file, self.mtime = info.inode, name, info.mtime
        if info.size == self.offset:
            return [], reset
        data = self.source.read(name, self.offset)
        self.offset += len(data)
        lines, self.rest = readers.split_lines(self.rest + data)
        rows = []
        for line in lines:
            if line.startswith("#"):
                if self.columns is None:
                    self.columns = readers.parse_header(line)
                continue
            if not line.strip() or self.columns is None:
                continue
            row = readers.parse_row(line, self.columns)
            if row is None:
                self.bad_lines += 1
            else:
                rows.append(row)
        return rows, reset


class Run:
    """One run directory of h4nb_run. update() reads the new lines. samples() gives the metric values."""

    def __init__(self, label: str, source):
        self.label, self.source = label, source
        self.config = readers.parse_config_used(readers.read_text(source, "config.used") or "")
        self.info = readers.parse_run_info(readers.read_text(source, "run_info.txt") or "")
        self.tails = {name: TableTail(source, name) for name in TABLES}
        self.last: Dict[str, Dict[str, float]] = {}
        self.sums: Dict[str, float] = {}
        self.recent: Deque[Tuple[float, float]] = collections.deque(maxlen=RECENT)  # (segment sim length, wall_s)
        self.prev_perf_time = 0.0
        self.periods: Dict[int, Dict[str, float]] = {}
        self.read_errors = 0
        self.particles: Optional[int] = None

    # --- reading -------------------------------------------------------------------------------------------
    def update(self) -> None:
        for name, tail in self.tails.items():
            try:
                rows, reset = tail.poll()
            except OSError:
                self.read_errors += 1
                continue
            if reset:
                self._reset(name)
            for row in rows:
                self._add(name, row)
            self.read_errors += tail.bad_lines
            tail.bad_lines = 0
        if self.particles is None:
            self.particles = self._find_particles()

    def _reset(self, name: str) -> None:
        self.last.pop(name, None)
        if name == "performance.dat":
            self.sums.clear()
            self.recent.clear()
            self.prev_perf_time = 0.0
        if name == "energy_periods.dat":
            self.periods.clear()

    def _add(self, name: str, row: Dict[str, float]) -> None:
        self.last[name] = row
        if name == "performance.dat":
            for key in ("wall_s", "block_steps", "active"):
                if key in row and math.isfinite(row[key]):
                    self.sums[key] = self.sums.get(key, 0.0) + row[key]
            t = row.get("time", 0.0)
            self.recent.append((t - self.prev_perf_time, row.get("wall_s", 0.0)))
            self.prev_perf_time = t
        elif name == "energy_periods.dat" and "period" in row:
            self.periods[int(row["period"])] = row

    def _find_particles(self) -> Optional[int]:
        """spec FR-008: key n, then the first snap_*.snap header, then the ic file header (.snap only)."""
        n = to_float(self.config.get("n"))
        if n is not None and n > 0:
            return int(n)
        snaps = sorted(x for x in self.source.names() if x.startswith("snap_") and x.endswith(".snap"))
        for s in snaps:
            try:
                h = readers.snapshot_header(self.source.read(s, 0, readers.SNAP_HEADER.size))
            except OSError:
                h = None
            if h:
                return h[0]
        ic = self.config.get("ic", "")
        if ic.endswith(".snap"):
            p = self.source.resolve(ic)
            if p:
                try:
                    with open(p, "rb") as f:
                        h = readers.snapshot_header(f.read(readers.SNAP_HEADER.size))
                    if h:
                        return h[0]
                except OSError:
                    pass
        return None

    # --- derived values ------------------------------------------------------------------------------------
    @property
    def t_end(self) -> Optional[float]:
        return to_float(self.config.get("t_end"))

    def sim_time(self) -> Optional[float]:
        e = self.last.get("energy.dat")
        return e.get("time") if e else None

    def newest_mtime(self) -> Optional[float]:
        m = [t.mtime for t in self.tails.values() if t.file is not None]
        return max(m) if m else None

    def finished_files(self) -> bool:
        return self.tails["energy.dat"].file == "energy.dat"

    def stale_after(self, stale_min: float) -> float:
        walls = [w for _, w in self.recent if math.isfinite(w)]
        return max(stale_min, 5.0 * max(walls)) if walls else stale_min

    def state(self, now: float, stale_min: float) -> Optional[int]:
        if self.tails["energy.dat"].file is None:
            return None
        if self.finished_files():
            t, te = self.sim_time(), self.t_end
            if t is not None and te is not None and t >= te * (1 - 1e-12):
                return STATE_FINISHED
            return STATE_STOPPED
        age = now - (self.newest_mtime() or now)
        return STATE_STALLED if age > self.stale_after(stale_min) else STATE_RUNNING

    def eta_seconds(self, state: Optional[int]) -> Optional[float]:
        if state in (STATE_FINISHED, STATE_STOPPED):
            return 0.0
        if state == STATE_STALLED:  # The run does not progress. An estimate would mislead.
            return None
        t, te = self.sim_time(), self.t_end
        if t is None or te is None or len(self.recent) < 2:
            return None
        sim = sum(s for s, _ in self.recent)
        wall = sum(w for _, w in self.recent)
        if not (sim > 0 and wall > 0):
            return None
        return max(0.0, te - t) / (sim / wall)

    def info_labels(self) -> Labels:
        gpu = ""
        for key in ("device_0", "rank_0"):
            if key in self.info:
                d = readers.parse_device_line(self.info[key])
                gpu = d.get("name", d.get("error", ""))
                break
        return {
            "host": self.info.get("host", ""),
            "commit": self.info.get("h4nb_commit", ""),
            "build_type": self.info.get("build_type", ""),
            "gpu": gpu,
            "ranks": self.info.get("ranks", ""),
            "mpi": self.info.get("mpi", ""),
            "start_utc": self.info.get("start_utc", ""),
            "preset": self.config.get("preset", ""),
        }

    def config_samples(self) -> List[Sample]:
        out = []
        for key, value in sorted(self.config.items()):
            v = to_float(value)
            if v is not None:
                out.append(({"key": key}, v))
        return out

    def start_timestamp(self) -> Optional[float]:
        return parse_utc(self.info.get("start_utc", ""))

    def samples(self, now: float, stale_min: float) -> Dict[str, List[Sample]]:
        """Current values: metric name -> [(extra labels, value)]. Names without the `_total` suffix of counters."""
        out: Dict[str, List[Sample]] = collections.defaultdict(list)

        def put(name: str, value: Optional[float], labels: Optional[Labels] = None) -> None:
            if value is not None:
                out[name].append((labels or {}, float(value)))

        out["h4nb_run_info"].append((self.info_labels(), 1.0))
        out["h4nb_config_value"].extend(self.config_samples())
        state = self.state(now, stale_min)
        put("h4nb_run_state", state)
        t, te = self.sim_time(), self.t_end
        put("h4nb_sim_time", t)
        put("h4nb_t_end", te)
        if t is not None and te:
            put("h4nb_progress_ratio", min(1.0, t / te))
        put("h4nb_eta_seconds", self.eta_seconds(state))
        newest = self.newest_mtime()
        if newest is not None:
            put("h4nb_last_update_age_seconds", max(0.0, now - newest))
            put("h4nb_run_end_timestamp_seconds", self.tails["energy.dat"].mtime or newest)
        put("h4nb_run_start_timestamp_seconds", self.start_timestamp())
        put("h4nb_particles", self.particles)
        for metric, value in row_metrics(self.last, self.particles):
            put(metric, value)
        if "wall_s" in self.sums:
            put("h4nb_wall_seconds", self.sums["wall_s"])
            put("h4nb_block_steps", self.sums.get("block_steps", 0.0))
            put("h4nb_active_updates", self.sums.get("active", 0.0))
        for k, row in sorted(self.periods.items()):
            put("h4nb_period_max_rel_err", row.get("max_rel_err"), {"period": str(k)})
        return out


# Gauges from the last row of each table: (table, column, metric).
ROW_GAUGES = (
    ("energy.dat", "rel_err", "h4nb_energy_rel_err"),
    ("energy.dat", "max_rel_err", "h4nb_energy_max_rel_err"),
    ("energy.dat", "mean_rel_err", "h4nb_energy_mean_rel_err"),
    ("energy.dat", "E", "h4nb_energy_total"),
    ("energy.dat", "W_diss", "h4nb_dissipated_work"),
    ("momentum.dat", "dP_rel", "h4nb_momentum_rel_change"),
    ("momentum.dat", "dL_rel", "h4nb_angular_momentum_rel_change"),
    ("timesteps.dat", "dt_min", "h4nb_dt_min"),
    ("timesteps.dat", "dt_mean", "h4nb_dt_mean"),
    ("timesteps.dat", "dt_max", "h4nb_dt_max"),
    ("timesteps.dat", "mean_active_per_block_step", "h4nb_active_per_block_step"),
    ("timesteps.dat", "r_min", "h4nb_r_min"),
    ("performance.dat", "pairs_per_s", "h4nb_pairs_per_second"),
    ("performance.dat", "wall_s", "h4nb_segment_wall_seconds"),
)


def row_metrics(last: Dict[str, Dict[str, float]], particles: Optional[int]) -> Iterable[Tuple[str, float]]:
    """Gauges of the last rows. Also used by the backfill, one row at a time."""
    for table, column, metric in ROW_GAUGES:
        row = last.get(table)
        if row is not None and column in row:
            yield metric, row[column]
    perf = last.get("performance.dat")
    if perf is not None:
        if "pairs_per_s" in perf:
            yield "h4nb_gflops", FLOP_PER_PAIR * perf["pairs_per_s"] / 1e9
        wall, active = perf.get("wall_s"), perf.get("active")
        if wall and active is not None and wall > 0:
            yield "h4nb_particle_updates_per_second", active / wall


# --- discovery -----------------------------------------------------------------------------------------------
def is_run_dir(path: str) -> bool:
    try:
        with open(os.path.join(path, "config.used"), "r", errors="replace") as f:
            return "h4nb_run" in f.readline()
    except OSError:
        return False


def find_run_dirs(root: str, max_depth: int) -> List[str]:
    if is_run_dir(root):
        return [root]
    found = []
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, _ in os.walk(root):
        depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
        if depth > 0 and is_run_dir(dirpath):
            found.append(dirpath)
            dirnames[:] = []
            continue
        if depth >= max_depth:
            dirnames[:] = []
        dirnames.sort()
    return found


def unique_labels(items: List[Tuple[str, str, str]]) -> Dict[str, str]:
    """items: (key, short name, long name). The short name is used when it is unique, else the long name."""
    count = collections.Counter(short for _, short, _ in items)
    return {key: (short if count[short] == 1 else long) for key, short, long in items}


def discover(paths: List[str], max_depth: int, archive_cache: Dict) -> Dict[str, object]:
    """All runs under the paths: label -> source. archive_cache keeps the archives that did not change."""
    items = []  # (key, short, long, source factory)
    sources = {}
    for root in paths:
        if readers.is_archive(root):
            mtime = os.stat(root).st_mtime
            cached = archive_cache.get(root)
            if cached is None or cached[0] != mtime:
                cached = (mtime, readers.read_archive(root))
                archive_cache[root] = cached
            for rel, src in cached[1].items():
                key = root + "::" + rel
                items.append((key, os.path.basename(rel), os.path.basename(root).split(".")[0] + "/" + rel))
                sources[key] = src
        elif os.path.isdir(root):
            for d in find_run_dirs(root, max_depth):
                key = os.path.abspath(d)
                rel = os.path.relpath(d, os.path.dirname(os.path.abspath(root)))
                items.append((key, os.path.basename(os.path.abspath(d)), rel))
                sources[key] = None
    labels = unique_labels(items)
    return {labels[k]: (k, sources[k]) for k, _, _ in items}


class RunSet:
    """The runs under a list of paths. refresh() searches again, at most each `rescan` seconds (spec FR-004)."""

    def __init__(self, paths: List[str], max_depth: int = 2, rescan: float = 10.0):
        self.paths, self.max_depth, self.rescan = paths, max_depth, rescan
        self.runs: Dict[str, Run] = {}
        self._keys: Dict[str, str] = {}
        self._archives: Dict = {}
        self._last_scan = -1e300
        self.errors: Dict[str, float] = collections.defaultdict(float)

    def refresh(self, now: Optional[float] = None) -> None:
        now = _time.monotonic() if now is None else now
        if now - self._last_scan >= self.rescan:
            self._last_scan = now
            found = discover(self.paths, self.max_depth, self._archives)
            for label in list(self.runs):
                if label not in found or found[label][0] != self._keys[label]:
                    del self.runs[label]
                    del self._keys[label]
            for label, (key, src) in found.items():
                if label not in self.runs:
                    try:
                        self.runs[label] = Run(label, src if src is not None else DirSource(key))
                        self._keys[label] = key
                    except OSError:
                        self.errors[label] += 1
        for label, run in self.runs.items():
            try:
                run.update()
            except Exception:  # FR-013: one bad run must not stop the exporter.
                self.errors[label] += 1
            self.errors[label] += run.read_errors
            run.read_errors = 0
