"""Write thinned snapshots: the .thin format of contracts/frame-format.md section 2 (FR-019, R3)."""
from __future__ import annotations

import os
import struct
from typing import List

import numpy as np

from .runs import central_id_of
from .snapshots import list_frames, subset_indices

THIN_HEADER = struct.Struct("<8sIIQQd")  # magic, version, seed, k, n, time: 40 bytes
THIN_MAGIC = b"H4NBTHIN"


def thin_run(run_dir: str, out_dir: str, max_points: int = 200000, seed: int = 1) -> List[str]:
    """Write one .thin file per snapshot of run_dir into out_dir. Return the paths written.

    The subset comes from the IDs of the first snapshot, so it is the same in every frame.
    """
    frames = list_frames(run_dir)
    if not frames:
        return []
    os.makedirs(out_dir, exist_ok=True)
    ids0 = np.asarray(frames[0].array("id"))
    central = central_id_of(run_dir)
    idx = subset_indices(ids0, central, max_points, seed)
    # Central body first. subset_indices skips this when all particles are kept.
    idx = np.concatenate([idx[ids0[idx] == central], idx[ids0[idx] != central]])

    written = []
    for snap in frames:
        pos = np.stack([np.asarray(snap.array(c))[idx] for c in ("x", "y", "z")], axis=1)
        vel = np.stack([np.asarray(snap.array(c))[idx] for c in ("vx", "vy", "vz")], axis=1)
        header = THIN_HEADER.pack(THIN_MAGIC, 1, seed, len(idx), snap.n, snap.time)
        body = (np.asarray(snap.array("id"))[idx].astype("<i8").tobytes()
                + np.asarray(snap.array("m"))[idx].astype("<f8").tobytes()
                + pos.astype("<f4").tobytes()
                + vel.astype("<f4").tobytes())
        path = os.path.join(out_dir, os.path.splitext(snap.name)[0] + ".thin")
        with open(path + ".tmp", "wb") as f:
            f.write(header + body)
        os.replace(path + ".tmp", path)
        written.append(path)
    return written
