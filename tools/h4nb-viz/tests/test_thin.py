"""Tests for thin_run: .thin files of a fake run (contracts/frame-format.md section 2)."""
import os
import struct

import numpy as np
import pytest

from h4nb_viz import fake
from h4nb_viz.snapshots import open_snapshot
from h4nb_viz.thin import thin_run

# Header layout from the contract, written here again so the test checks the format.
HEADER = struct.Struct("<8sIIQQd")  # magic, version, seed, k, n, time: 40 bytes


@pytest.fixture
def run(tmp_path):
    """A fake run of 200 particles: 3 numbered snapshots and snap_final.snap."""
    run_dir = str(tmp_path / "run")
    fake.write_fake_run(run_dir, n=200, snaps=3, t_end=1.0, seed=7)
    return run_dir


def read_thin(path):
    """Parse one .thin file by the contract layout. Fail when the file has extra or missing bytes."""
    with open(path, "rb") as f:
        data = f.read()
    magic, version, seed, k, n, time = HEADER.unpack_from(data, 0)
    off = HEADER.size
    ids = np.frombuffer(data, "<i8", k, off)
    off += 8 * k
    mass = np.frombuffer(data, "<f8", k, off)
    off += 8 * k
    pos = np.frombuffer(data, "<f4", 3 * k, off).reshape(k, 3)
    off += 12 * k
    vel = np.frombuffer(data, "<f4", 3 * k, off).reshape(k, 3)
    off += 12 * k
    assert off == len(data)
    return dict(magic=magic, version=version, seed=seed, k=k, n=n, time=time,
                ids=ids, mass=mass, pos=pos, vel=vel, size=len(data))


def thin_files(out_dir):
    return sorted(f for f in os.listdir(out_dir) if f.endswith(".thin"))


def test_one_thin_file_per_snapshot(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=1)
    assert thin_files(out) == ["snap_000000.thin", "snap_000001.thin", "snap_000002.thin", "snap_final.thin"]


def test_at_most_max_points_particles(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=1)
    for name in thin_files(out):
        assert read_thin(os.path.join(out, name))["k"] == 50


def test_max_points_above_n_keeps_all(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=5000, seed=1)
    assert read_thin(os.path.join(out, "snap_final.thin"))["k"] == 200


def test_central_body_first(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=1)
    for name in thin_files(out):
        assert read_thin(os.path.join(out, name))["ids"][0] == 0


def test_central_body_first_when_all_kept(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=5000, seed=1)
    assert read_thin(os.path.join(out, "snap_final.thin"))["ids"][0] == 0


def test_subset_same_in_every_frame(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=1)
    first = read_thin(os.path.join(out, "snap_000000.thin"))["ids"]
    for name in thin_files(out):
        assert np.array_equal(read_thin(os.path.join(out, name))["ids"], first)


def test_same_seed_same_subset(run, tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    thin_run(run, a, max_points=50, seed=1)
    thin_run(run, b, max_points=50, seed=1)
    assert np.array_equal(read_thin(os.path.join(a, "snap_final.thin"))["ids"],
                          read_thin(os.path.join(b, "snap_final.thin"))["ids"])


def test_other_seed_other_subset(run, tmp_path):
    a, b = str(tmp_path / "a"), str(tmp_path / "b")
    thin_run(run, a, max_points=50, seed=1)
    thin_run(run, b, max_points=50, seed=2)
    assert not np.array_equal(read_thin(os.path.join(a, "snap_final.thin"))["ids"],
                              read_thin(os.path.join(b, "snap_final.thin"))["ids"])


def test_keeps_ids_and_values_of_source(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=1)
    snap = open_snapshot(os.path.join(run, "snap_final.snap"))
    thin = read_thin(os.path.join(out, "snap_final.thin"))
    ids = thin["ids"]
    # The fake run uses id == row index.
    for axis, name in enumerate(("x", "y", "z")):
        assert np.array_equal(thin["pos"][:, axis], np.asarray(snap.array(name))[ids].astype(np.float32))
    assert np.array_equal(thin["mass"], np.asarray(snap.array("m"))[ids])


def test_size_matches_format(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=3)
    thin = read_thin(os.path.join(out, "snap_final.thin"))
    assert thin["magic"] == b"H4NBTHIN"
    assert thin["version"] == 1
    assert thin["seed"] == 3
    assert thin["n"] == 200
    assert thin["size"] == HEADER.size + 40 * thin["k"]  # id 8 + m 8 + pos 12 + vel 12 bytes each


def test_no_tmp_file_left(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=1)
    assert not [f for f in os.listdir(out) if f.endswith(".tmp")]
