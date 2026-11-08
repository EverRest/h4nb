"""Run discovery and run states (contracts/http-api.md, `GET /api/runs`).

The states use the names and rules of specs/002 section 5. A run is a directory under the root with
`config.used` and a snapshot or an energy table. Archives of `h4nb_pack.sh` are also runs: the name
is `<archive stem>~<subdirectory>` (FR-015).
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from .archive import Archive, ArchiveError, archive_stem, is_archive
from .readers import parse_config_used, parse_run_info
from .snapshots import list_frames
from .tables import TABLE_NAMES, read_table, table_path

RESCAN_SECONDS = 5.0
STALE_MIN = 300.0  # Seconds. The minimum of the stale limit of specs/002.
DEFAULT_CACHE_DIR = os.path.expanduser("~/.cache/h4nb-viz")


@dataclass(frozen=True)
class RunRef:
    """One discovered run. kind is "dir" or "archive"."""

    kind: str
    path: str  # Directory of the run, or path of the .tar.gz.
    archive_run: Optional[str] = None  # Subdirectory name inside the archive.
    archive_name: Optional[str] = None  # Basename of the archive file, for the API.


def _has_run_data(files) -> bool:
    return (
        "energy.dat" in files
        or "energy.dat.tmp" in files
        or any(f.endswith(".snap") for f in files)
        or any(f.endswith(".thin") for f in files)
    )


def find_dir_runs(root: str) -> Dict[str, RunRef]:
    """Return {run name: RunRef} for each run directory under root."""
    root = os.path.abspath(root)
    runs = {}
    for dirpath, _dirs, files in os.walk(root):
        if "config.used" not in files or not _has_run_data(files):
            continue
        if dirpath == root:
            name = os.path.basename(root)
        else:
            name = os.path.relpath(dirpath, root).replace(os.sep, "~")
        runs[name] = RunRef("dir", dirpath)
    return runs


def _archive_paths(root: str, upload_dir: Optional[str]) -> list:
    """Archive files in the top level of root and of the upload directory."""
    paths = []
    for folder in (root, upload_dir):
        if not folder or not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if is_archive(path):
                paths.append(path)
    return paths


def find_archive_runs(root: str, upload_dir: Optional[str], cache_dir: str) -> Dict[str, RunRef]:
    """Return {<stem>~<run>: RunRef} for each run with config.used inside an archive."""
    runs = {}
    for path in _archive_paths(root, upload_dir):
        stem = archive_stem(path)
        try:
            archive = Archive(path, cache_dir=os.path.join(cache_dir, "tar"))
            members = archive.runs()
        except ArchiveError:
            continue
        for run_name, files in members.items():
            if "config.used" not in files or not _has_run_data(files):
                continue
            name = "%s~%s" % (stem, run_name.replace("/", "~"))
            runs[name] = RunRef("archive", path, archive_run=run_name, archive_name=os.path.basename(path))
    return runs


def find_runs(root: str, upload_dir: Optional[str] = None, cache_dir: str = DEFAULT_CACHE_DIR) -> Dict[str, RunRef]:
    """Return {run name: RunRef} for directory runs and archive runs. Directory runs win on a name clash."""
    found = find_archive_runs(root, upload_dir, cache_dir)
    found.update(find_dir_runs(root))  # Directory runs overwrite archive names.
    return found


class RunIndex:
    """The runs of one root directory. The root is scanned at most once each RESCAN_SECONDS.

    Archive runs are extracted into cache_dir/runs/ on first access (FR-015).
    """

    def __init__(self, root: str, cache_dir: Optional[str] = None, upload_dir: Optional[str] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.root = os.path.abspath(root)
        self.cache_dir = os.path.abspath(cache_dir or DEFAULT_CACHE_DIR)
        self.upload_dir = os.path.abspath(upload_dir or os.path.join(self.cache_dir, "uploads"))
        self._clock = clock
        self._lock = threading.Lock()
        self._refs: Dict[str, RunRef] = {}
        self._resolved: Dict[str, str] = {}  # name -> materialized directory
        self._scanned_at: Optional[float] = None

    def invalidate(self) -> None:
        """Force a rescan on the next call to runs()."""
        with self._lock:
            self._scanned_at = None

    def archive_of(self, name: str) -> Optional[str]:
        """Basename of the archive for this run, or None for a directory run."""
        with self._lock:
            ref = self._refs.get(name)
        return ref.archive_name if ref and ref.kind == "archive" else None

    def runs(self) -> Dict[str, str]:
        """Return {run name: directory path}. Archive runs are materialized into the cache."""
        with self._lock:
            now = self._clock()
            if self._scanned_at is None or now - self._scanned_at >= RESCAN_SECONDS:
                self._refs = find_runs(self.root, self.upload_dir, self.cache_dir)
                self._resolved = {n: p for n, p in self._resolved.items() if n in self._refs}
                self._scanned_at = now
            out = {}
            for name, ref in self._refs.items():
                out[name] = self._resolve_locked(name, ref)
            return out

    def _resolve_locked(self, name: str, ref: RunRef) -> str:
        if ref.kind == "dir":
            return ref.path
        if name in self._resolved and os.path.isdir(self._resolved[name]):
            return self._resolved[name]
        dest = self._materialize(ref)
        self._resolved[name] = dest
        return dest

    def _materialize(self, ref: RunRef) -> str:
        try:
            st = os.stat(ref.path)
            key = hashlib.sha256(("%s|%d|%d" % (ref.path, st.st_mtime_ns, st.st_size)).encode()).hexdigest()[:16]
        except OSError as err:
            raise ArchiveError("cannot read archive %s: %s" % (ref.path, err)) from err
        dest = os.path.join(self.cache_dir, "runs", key, ref.archive_run.replace("/", os.sep))
        marker = os.path.join(dest, ".h4nb-viz-extracted")
        if os.path.isfile(marker):
            return dest
        archive = Archive(ref.path, cache_dir=os.path.join(self.cache_dir, "tar"))
        archive.materialize(ref.archive_run, dest)
        with open(marker, "w") as f:
            f.write("%s\n%s\n" % (ref.path, ref.archive_run))
        return dest


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


def start_utc_of(run_dir: str) -> Optional[str]:
    """The start_utc value of run_info.txt, or None. Prometheus matches runs by this value."""
    return parse_run_info(_read_text(run_dir, "run_info.txt")).get("start_utc")


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


def summarize(name: str, run_dir: str, now: float, prom_label: Optional[str] = None,
              archive: Optional[str] = None) -> dict:
    """One entry of the run list (contracts/http-api.md `GET /api/runs`). prom_label is the run label of
    specs/002 when Prometheus has the run, else None. archive is the archive basename when the run
    comes from a pack file."""
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
        "in_prometheus": prom_label is not None,
        "prom_label": prom_label,
        "thin": bool(frames) and bool(getattr(frames[0], "thin", False)),
        "archive": archive,
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
