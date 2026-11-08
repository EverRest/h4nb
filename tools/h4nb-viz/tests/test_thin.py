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


RUN_RECORDS = ["config.used", "run_info.txt", "energy.dat", "momentum.dat", "timesteps.dat",
               "performance.dat", "energy_periods.dat"]


def test_copies_tables_and_records(run, tmp_path):
    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=1)
    for name in RUN_RECORDS:
        with open(os.path.join(run, name), "rb") as a, open(os.path.join(out, name), "rb") as b:
            assert a.read() == b.read(), name


def test_open_thin_and_list_frames_prefer_thin(run, tmp_path):
    from h4nb_viz.snapshots import list_frames, open_thin

    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=1)
    snap = open_thin(os.path.join(out, "snap_final.thin"))
    assert snap is not None and snap.thin and snap.n == 50 and snap.seed == 1
    assert snap.array("id")[0] == 0
    frames = list_frames(out)
    assert all(f.name.endswith(".thin") for f in frames)
    assert [f.name for f in frames] == ["snap_000000.thin", "snap_000001.thin", "snap_000002.thin", "snap_final.thin"]


def test_open_thin_rejects_truncated_file(run, tmp_path):
    from h4nb_viz.snapshots import open_thin

    out = str(tmp_path / "out")
    thin_run(run, out, max_points=50, seed=1)
    path = os.path.join(out, "snap_final.thin")
    with open(path, "r+b") as f:
        f.truncate(os.path.getsize(path) - 1)
    assert open_thin(path) is None


def test_server_reads_thin_run(run, tmp_path):
    """A thinned run is listed with thin=true and serves frames of size k."""
    import json
    import threading
    import urllib.request

    from h4nb_viz.server import make_server
    from h4nb_viz.snapshots import FRAME_HEADER

    out = str(tmp_path / "root" / "thin_run")
    thin_run(run, out, max_points=50, seed=1)
    root = str(tmp_path / "root")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html>")
    httpd = make_server(root, port=0, export_dir=str(tmp_path / "ex"), web_dir=str(web))
    token = httpd.app.token
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        base = "http://127.0.0.1:%d" % httpd.server_address[1]

        def get(path):
            req = urllib.request.Request(base + path, headers={"X-H4NB-Token": token})
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()

        status, _, body = get("/api/runs")
        runs = json.loads(body)
        assert status == 200
        entry = next(r for r in runs if r["run"] == "thin_run")
        assert entry["thin"] is True and entry["n"] == 50 and entry["snapshots"] == 4
        status, headers, body = get("/api/runs/thin_run/ids?max_points=200000")
        assert status == 200 and headers["X-H4NB-Count"] == "50"
        status, _, body = get("/api/runs/thin_run/frames/0?max_points=200000&fields=pos,vel")
        assert status == 200
        _magic, _ver, count, fields, _t, *_rest = FRAME_HEADER.unpack(body[:40])
        assert (count, fields) == (50, 3)
        assert len(body) == 40 + 24 * 50
    finally:
        httpd.shutdown()
        httpd.server_close()
