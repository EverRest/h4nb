import os

import numpy as np

from h4nb_viz import fake
from h4nb_viz.snapshots import (FIELD_MASS, FIELD_POS, FIELD_VEL, FRAME_HEADER, FRAME_MAGIC, Subset, SubsetCache,
                                encode_frame, encode_ids, list_frames, open_snapshot, subset_indices)


def _write_known(path, time, ids, mass, pos, vel):
    fake._write_snapshot(str(path), time, ids, mass, pos, vel)


def _specific_energy(snap):
    """Kepler energy per particle (central body excluded). It is constant on a Kepler orbit."""
    x, y, z, vx, vy, vz = (np.asarray(snap.array(c))[1:] for c in ("x", "y", "z", "vx", "vy", "vz"))
    r = np.sqrt(x * x + y * y + z * z)
    return 0.5 * (vx * vx + vy * vy + vz * vz) - 1.0 / r


def test_write_read_round_trip(tmp_path):
    ids = np.array([3, 0, 7, 1, 9], dtype=np.int64)
    mass = np.array([1e-6, 1.0, 2e-6, 3e-6, 4e-6])
    pos = np.arange(15, dtype=float).reshape(5, 3) * 0.5
    vel = -np.arange(15, dtype=float).reshape(5, 3) * 0.25
    path = tmp_path / "s.snap"
    _write_known(path, 0.75, ids, mass, pos, vel)

    snap = open_snapshot(str(path))
    assert snap is not None
    assert (snap.n, snap.time) == (5, 0.75)
    assert np.array_equal(snap.array("id"), ids)
    assert np.array_equal(snap.array("m"), mass)
    for i, name in enumerate(("x", "y", "z")):
        assert np.array_equal(snap.array(name), pos[:, i])
    for i, name in enumerate(("vx", "vy", "vz")):
        assert np.array_equal(snap.array(name), vel[:, i])


def test_array_read_uses_its_own_offset(tmp_path):
    n = 5
    pos = np.ones((n, 3))
    vel = np.full((n, 3), 2.0)
    path = tmp_path / "s.snap"
    _write_known(path, 0.0, np.arange(n, dtype=np.int64), np.ones(n), pos, vel)
    with open(path, "r+b") as f:  # Overwrite the id and mass arrays. The vz array must still be right.
        f.seek(32)
        f.write(b"\xff" * (2 * 8 * n))
    snap = open_snapshot(str(path))
    assert np.array_equal(snap.array("vz"), np.full(n, 2.0))


def test_incomplete_snapshot_is_skipped(tmp_path):
    path = tmp_path / "s.snap"
    _write_known(path, 0.0, np.arange(4, dtype=np.int64), np.ones(4), np.zeros((4, 3)), np.zeros((4, 3)))
    size = os.path.getsize(path)
    with open(path, "r+b") as f:
        f.truncate(size - 8)  # The writer is still writing the last array.
    assert open_snapshot(str(path)) is None
    assert open_snapshot(str(tmp_path / "missing.snap")) is None


def test_list_frames_sorted_and_skips_partial(small_run):
    frames = list_frames(small_run)
    assert [f.name for f in frames] == ["snap_000000.snap", "snap_000001.snap", "snap_000002.snap", "snap_final.snap"]
    assert [round(f.time, 6) for f in frames] == [0.0, round(1 / 3, 6), round(2 / 3, 6), 1.0]

    partial = os.path.join(small_run, "snap_000001.snap")
    with open(partial, "r+b") as f:
        f.truncate(os.path.getsize(partial) - 1)
    assert "snap_000001.snap" not in [f.name for f in list_frames(small_run)]


def test_energy_is_constant_on_each_orbit(small_run):
    frames = list_frames(small_run)
    first, last = _specific_energy(frames[0]), _specific_energy(frames[-1])
    assert np.max(np.abs(first - last)) < 1e-12 * np.max(np.abs(first))


def test_subset_has_exact_size_and_central_first():
    ids = np.arange(1000, dtype=np.int64)[::-1]  # The central body (id 0) is the last row.
    idx = subset_indices(ids, central_id=0, max_points=100, seed=1)
    assert len(idx) == 100
    assert ids[idx[0]] == 0
    assert len(set(idx.tolist())) == 100


def test_subset_is_all_when_max_points_is_large():
    ids = np.arange(50, dtype=np.int64)
    assert np.array_equal(subset_indices(ids, 0, 500, 1), np.arange(50))


def test_subset_depends_on_ids_and_seed_only():
    ids = np.arange(1000, dtype=np.int64)
    a = subset_indices(ids, 0, 100, seed=1)
    assert np.array_equal(a, subset_indices(ids.copy(), 0, 100, seed=1))
    assert not np.array_equal(a, subset_indices(ids, 0, 100, seed=2))


def test_subset_same_over_frames_and_contains_central(small_run):
    frames = list_frames(small_run)
    cache = SubsetCache()
    first = cache.get("run", frames[0], central_id=0, max_points=50, seed=1)
    assert np.array_equal(first.indices, subset_indices(np.asarray(frames[-1].array("id")), 0, 50, 1))
    assert first.central_row == 0
    assert first.indices[0] == 0 and len(first.indices) == 50


def test_subset_central_row_not_at_start():
    ids = np.array([5, 6, 0, 7, 8], dtype=np.int64)  # The central body is at row 2.
    cache = SubsetCache()

    class _Snap:
        def array(self, name):
            return ids

    subset = cache.get("r", _Snap(), central_id=0, max_points=3, seed=1)
    assert subset.central_row == 2
    assert ids[subset.indices[0]] == 0


def test_encode_frame_header_and_body(tmp_path):
    ids = np.arange(4, dtype=np.int64)
    mass = np.array([1.0, 0.1, 0.2, 0.3])
    pos = np.array([[10.0, 20.0, 30.0], [11.0, 20.0, 30.0], [10.0, 23.0, 30.0], [10.0, 20.0, 34.0]])
    vel = np.arange(12, dtype=float).reshape(4, 3)
    path = tmp_path / "s.snap"
    _write_known(path, 0.75, ids, mass, pos, vel)
    snap = open_snapshot(str(path))
    subset = Subset(indices=np.array([0, 2, 3]), central_row=0)

    data = encode_frame(snap, subset, FIELD_POS | FIELD_VEL | FIELD_MASS)
    magic, version, count, fields, time, cx, cy, cz, scale = FRAME_HEADER.unpack(data[:40])
    assert (magic, version, count, fields, time) == (FRAME_MAGIC, 1, 3, 7, 0.75)
    assert (cx, cy, cz) == (10.0, 20.0, 30.0)
    assert scale == np.float32(4.0)  # Largest distance from the center: particle 3 is 4 away.
    assert len(data) == 40 + 4 * (3 * 3 + 3 * 3 + 3)
    rel = np.frombuffer(data[40:40 + 36], dtype="<f4").reshape(3, 3)
    assert np.allclose(rel, pos[[0, 2, 3]] - pos[0])
    vel_out = np.frombuffer(data[76:76 + 36], dtype="<f4").reshape(3, 3)
    assert np.allclose(vel_out, vel[[0, 2, 3]])
    assert np.allclose(np.frombuffer(data[112:124], dtype="<f4"), mass[[0, 2, 3]])


def test_encode_frame_positions_only_has_no_extra_arrays(tmp_path):
    path = tmp_path / "s.snap"
    _write_known(path, 0.0, np.arange(3, dtype=np.int64), np.ones(3), np.zeros((3, 3)), np.zeros((3, 3)))
    data = encode_frame(open_snapshot(str(path)), Subset(np.arange(3), None), FIELD_POS)
    assert len(data) == 40 + 3 * 3 * 4
    assert FRAME_HEADER.unpack(data[:40])[3] == FIELD_POS


def test_encode_ids_chooses_the_type():
    kind, body = encode_ids(np.array([0, 5], dtype=np.int64))
    assert kind == "u32" and len(body) == 8
    assert np.array_equal(np.frombuffer(body, dtype="<u4"), [0, 5])
    kind, body = encode_ids(np.array([2 ** 40], dtype=np.int64))
    assert kind == "i64" and np.frombuffer(body, dtype="<i8")[0] == 2 ** 40
