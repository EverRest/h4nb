"""Reader for v1 snapshots (specs/001 file-formats.md section 2), decimation and the frame encoder
(contracts/frame-format.md section 1).

Each array is read with its own numpy.memmap at its own offset. A file that is still being
written has the wrong size, so open_snapshot returns None for it.
"""
from __future__ import annotations

import os
import re
import struct
from typing import Dict, List, Optional, Tuple

import numpy as np

from .readers import SNAP_HEADER, snapshot_header

HEADER_BYTES = SNAP_HEADER.size  # 32
ARRAY_NAMES = ("id", "m", "x", "y", "z", "vx", "vy", "vz")
ARRAY_DTYPES = {"id": "<i8"}  # All other arrays are float64.
FRAME_HEADER = struct.Struct("<4sIIId3ff")  # magic, version, count, fields, time, center[3], scale: 40 bytes
FRAME_MAGIC = b"H4VF"
FIELD_POS, FIELD_VEL, FIELD_MASS = 1, 2, 4
NUMBERED = re.compile(r"snap_\d{6}\.snap")


class Snapshot:
    """One valid snapshot file. Read the arrays with `array(name)`."""

    def __init__(self, path: str, n: int, time: float):
        self.path = path
        self.name = os.path.basename(path)
        self.n = n
        self.time = time

    def array(self, name: str) -> np.ndarray:
        """Return one array as a read-only memmap. Other arrays are not read."""
        dtype = ARRAY_DTYPES.get(name, "<f8")
        if self.n == 0:
            return np.empty(0, dtype=dtype)
        index = ARRAY_NAMES.index(name)
        return np.memmap(self.path, dtype=dtype, mode="r", offset=HEADER_BYTES + index * 8 * self.n,
                         shape=(self.n,))


def open_snapshot(path: str) -> Optional[Snapshot]:
    """Return the snapshot, or None when the file is missing, not v1, or not complete yet."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(HEADER_BYTES)
    except OSError:
        return None
    header = snapshot_header(head)
    if header is None:
        return None
    n, time = header
    if size != HEADER_BYTES + 8 * 8 * n:  # Eight arrays of n values, 8 bytes each.
        return None
    return Snapshot(path, n, time)


def list_frames(run_dir: str) -> List[Snapshot]:
    """Valid snapshots of a run, sorted by time. snap_final.snap counts only when its time is larger
    than the time of the last numbered snapshot."""
    try:
        names = sorted(f for f in os.listdir(run_dir) if NUMBERED.fullmatch(f))
    except OSError:
        return []
    frames = [s for s in (open_snapshot(os.path.join(run_dir, f)) for f in names) if s is not None]
    final = open_snapshot(os.path.join(run_dir, "snap_final.snap"))
    if final is not None and (not frames or final.time > frames[-1].time):
        frames.append(final)
    return sorted(frames, key=lambda s: s.time)


def _splitmix64(x: np.ndarray) -> np.ndarray:
    """The splitmix64 hash of uint64 values, computed for an array."""
    with np.errstate(over="ignore"):
        x = x + np.uint64(0x9E3779B97F4A7C15)
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return x ^ (x >> np.uint64(31))


def subset_indices(ids: np.ndarray, central_id: int, max_points: int, seed: int) -> np.ndarray:
    """Indices of the decimation subset (plan DD3). The central body comes first, then the particles
    with the smallest hash of id ^ seed. The subset depends on the IDs only, so it is the same in all frames.
    The count is exact: min(max_points, n). This is the hash threshold of DD3 with the threshold set to the
    m-th smallest hash."""
    n = len(ids)
    if max_points >= n:
        return np.arange(n)
    central = np.nonzero(ids == central_id)[0]
    others = np.nonzero(ids != central_id)[0]
    keep = max(max_points - len(central), 0)
    if keep < len(others):
        h = _splitmix64(ids[others].astype(np.uint64) ^ np.uint64(seed))
        others = others[np.argpartition(h, keep)[:keep]]
    return np.concatenate([central, np.sort(others)])


class Subset:
    """The subset of one run: indices into the arrays, and the array row of the central body (or None)."""

    def __init__(self, indices: np.ndarray, central_row: Optional[int]):
        self.indices = indices
        self.central_row = central_row


class SubsetCache:
    """Subsets per run, computed once. Key: run name, central_id, max_points and seed."""

    def __init__(self):
        self._items: Dict[Tuple[str, int, int, int], Subset] = {}

    def get(self, run: str, snap: Snapshot, central_id: int, max_points: int, seed: int) -> Subset:
        key = (run, central_id, max_points, seed)
        if key not in self._items:
            ids = snap.array("id")
            central = np.nonzero(ids == central_id)[0]
            central_row = int(central[0]) if len(central) else None
            self._items[key] = Subset(subset_indices(np.asarray(ids), central_id, max_points, seed), central_row)
        return self._items[key]


def encode_ids(ids: np.ndarray) -> Tuple[str, bytes]:
    """Return ("u32" or "i64", bytes) for IDs. The type is u32 when all IDs fit in 32 bits."""
    if len(ids) == 0 or (ids.min() >= 0 and ids.max() < 2 ** 32):
        return "u32", np.asarray(ids, dtype="<u4").tobytes()
    return "i64", np.asarray(ids, dtype="<i8").tobytes()


def encode_frame(snap: Snapshot, subset: Subset, fields: int = FIELD_POS) -> bytes:
    """Return one binary frame (frame-format.md section 1). Positions are relative to the central body.
    The scale is the largest distance from the center over the subset."""
    idx = subset.indices
    pos = np.stack([np.asarray(snap.array(c))[idx] for c in ("x", "y", "z")], axis=1).astype(np.float64)
    if subset.central_row is not None:
        center = np.array([float(snap.array(c)[subset.central_row]) for c in ("x", "y", "z")])
    else:
        center = np.zeros(3)
    rel = pos - center
    scale = float(np.sqrt(np.max(np.sum(rel * rel, axis=1)))) if len(idx) else 0.0
    k = len(idx)
    header = FRAME_HEADER.pack(FRAME_MAGIC, 1, k, fields, snap.time, *center, scale)
    body = [rel.astype("<f4").tobytes()]
    if fields & FIELD_VEL:
        vel = np.stack([np.asarray(snap.array(c))[idx] for c in ("vx", "vy", "vz")], axis=1)
        body.append(vel.astype("<f4").tobytes())
    if fields & FIELD_MASS:
        body.append(np.asarray(snap.array("m"))[idx].astype("<f4").tobytes())
    return header + b"".join(body)
