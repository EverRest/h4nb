"""Run discovery and run states (contracts/http-api.md, `GET /api/runs`).

The states use the names and rules of specs/002 section 5. A run is a directory under the root with
`config.used` and a snapshot or an energy table.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Dict, Optional

from .readers import parse_config_used, parse_run_info
from .snapshots import list_frames
from .tables import TABLE_NAMES, read_table, table_path

RESCAN_SECONDS = 5.0
STALE_MIN = 300.0  # Seconds. The minimum of the stale limit of specs/002.


def find_runs(root: str) -> Dict[str, str]:
    """Return {run name: run directory} for each run under root. A run has config.used and a snapshot or an
    energy table. The name is the path relative to root, with `/` replaced by `~`. If root is a run itself,
    its name is its directory name, so `h4nb-viz serve DIR` shows DIR (SC-005)."""
    root = os.path.abspath(root)
    runs = {}
    for dirpath, _dirs, files in os.walk(root):
        if "config.used" not in files:
            continue
        has_data = "energy.dat" in files or "energy.dat.tmp" in files or any(f.endswith(".snap") for f in files)
        if not has_data:
            continue
        if dirpath == root:
            name = os.path.basename(root)
        else:
            name = os.path.relpath(dirpath, root).replace(os.sep, "~")
        runs[name] = dirpath
    return runs


class RunIndex:
    """The runs of one root directory. The root is scanned at most once each RESCAN_SECONDS."""

    def __init__(self, root: str, clock: Callable[[], float] = time.monotonic):
        self.root = root
        self._clock = clock
        self._lock = threading.Lock()
        self._runs: Dict[str, str] = {}
        self._scanned_at: Optional[float] = None

    def runs(self) -> Dict[str, str]:
        with self._lock:
            now = self._clock()
            if self._scanned_at is None or now - self._scanned_at >= RESCAN_SECONDS:
                self._runs = find_runs(self.root)
                self._scanned_at = now
            return dict(self._runs)


def _read_text(run_dir: str, name: str) -> str:
    try:
        with open(os.path.join(run_dir, name), "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def t_end_of(run_dir: str) -> Optional[float]:
    """The t_end value of config.used, or None when it is missing or not a number."""
    try:
        return float(parse_config_used(_read_text(run_dir, "config.used"))["t_end"])
    except (KeyError, ValueError):
        return None


def central_id_of(run_dir: str) -> int:
    """The central_id value of config.used. The default is 0."""
    try:
        return int(parse_config_used(_read_text(run_dir, "config.used")).get("central_id", 0))
    except ValueError:
        return 0


def newest_change(run_dir: str) -> float:
    """The newest modification time of the files of the run directory."""
    times = []
    with os.scandir(run_dir) as entries:
        for entry in entries:
            if entry.is_file():
                times.append(entry.stat().st_mtime)
    return max(times, default=0.0)


def stale_after(run_dir: str) -> float:
    """max(300 s, 5 x the largest wall_s of the last 10 rows of performance.dat)."""
    perf = read_table(run_dir, "performance.dat")
    if not perf or len(perf.get("wall_s", ())) == 0:
        return STALE_MIN
    return max(STALE_MIN, 5 * float(perf["wall_s"][-10:].max()))


def run_state(run_dir: str, now: float) -> str:
    """One of: running, finished, stopped early, stalled, unknown."""
    if os.path.isfile(os.path.join(run_dir, "energy.dat.tmp")):
        age = now - newest_change(run_dir)
        return "running" if age <= stale_after(run_dir) else "stalled"
    energy = read_table(run_dir, "energy.dat")
    t_end = t_end_of(run_dir)
    if energy is None or t_end is None or len(energy.get("time", ())) == 0:
        return "unknown"
    return "finished" if energy["time"][-1] >= t_end * (1 - 1e-12) else "stopped early"


def summarize(name: str, run_dir: str, now: float) -> dict:
    """One entry of the run list (contracts/http-api.md `GET /api/runs`)."""
    frames = list_frames(run_dir)
    energy = read_table(run_dir, "energy.dat")
    times = energy.get("time", ()) if energy else ()
    return {
        "run": name,
        "state": run_state(run_dir, now),
        "n": frames[0].n if frames else None,
        "t_end": t_end_of(run_dir),
        "sim_time": float(times[-1]) if len(times) else None,
        "snapshots": len(frames),
        "tables": [t for t in TABLE_NAMES if table_path(run_dir, t)],
        # Prometheus matching is added in Phase 2 (T022). Until then, no run matches.
        "in_prometheus": False,
        "prom_label": None,
        "thin": False,
        "archive": None,
    }


def detail(name: str, run_dir: str) -> dict:
    """The run card and the frame list (contracts/http-api.md `GET /api/runs/{run}`).
    wall_s is the sum of the segment times of performance.dat."""
    frames = list_frames(run_dir)
    energy = read_table(run_dir, "energy.dat")
    perf = read_table(run_dir, "performance.dat")
    final_err = float(energy["rel_err"][-1]) if energy and len(energy.get("rel_err", ())) else None
    wall = float(perf["wall_s"].sum()) if perf and len(perf.get("wall_s", ())) else None
    return {
        "run": name,
        "info": parse_run_info(_read_text(run_dir, "run_info.txt")),
        "config": parse_config_used(_read_text(run_dir, "config.used")),
        "frames": [{"index": i, "file": s.name, "time": s.time} for i, s in enumerate(frames)],
        "final_energy_rel_err": final_err,
        "wall_s": wall,
    }
