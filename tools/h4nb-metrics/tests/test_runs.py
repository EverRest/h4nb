import os

from helpers import make_run
from h4nb_metrics import runs
from h4nb_metrics.readers import DirSource
from h4nb_metrics.runs import Run, RunSet, TableTail


def write(p, text, mode="a"):
    with open(str(p), mode) as f:
        f.write(text)


def test_tail_incremental_partial_rename_and_shrink(tmp_path):
    tmp = tmp_path / "energy.dat.tmp"
    write(tmp, "# time rel_err\n0 0\n1 1e-12\n2 2e", "w")
    t = TableTail(DirSource(str(tmp_path)), "energy.dat")
    rows, reset = t.poll()
    assert [r["time"] for r in rows] == [0, 1] and not reset  # The incomplete line is not read.
    write(tmp, "-12\n")
    rows, _ = t.poll()
    assert rows == [{"time": 2.0, "rel_err": 2e-12}]
    os.replace(str(tmp), str(tmp_path / "energy.dat"))  # Same inode: no reset, no repeated rows.
    rows, reset = t.poll()
    assert rows == [] and not reset and t.file == "energy.dat"
    write(tmp_path / "energy.dat", "# time rel_err\n0 5\n", "w")  # Shorter file: read again.
    rows, reset = t.poll()
    assert reset and rows == [{"time": 0.0, "rel_err": 5.0}]


def test_tail_counts_bad_lines(tmp_path):
    write(tmp_path / "energy.dat", "# time rel_err\n0 x\n1 2\n", "w")
    t = TableTail(DirSource(str(tmp_path)), "energy.dat")
    rows, _ = t.poll()
    assert len(rows) == 1 and t.bad_lines == 1


def test_finished_run_values(tmp_path):
    make_run(tmp_path / "r", n=1000)
    r = Run("r", DirSource(str(tmp_path / "r")))
    r.update()
    s = r.samples(now=2e9, stale_min=300)
    get = lambda name: s[name][0][1]
    assert get("h4nb_run_state") == runs.STATE_FINISHED
    assert get("h4nb_progress_ratio") == 1.0
    assert get("h4nb_eta_seconds") == 0.0
    assert get("h4nb_particles") == 1000
    assert get("h4nb_wall_seconds") == 16 * 2.0
    assert abs(get("h4nb_gflops") - 60 * get("h4nb_pairs_per_second") / 1e9) < 1e-9
    assert get("h4nb_run_start_timestamp_seconds") == 1793527200.0
    info = s["h4nb_run_info"][0][0]
    assert info["gpu"] == "NVIDIA GeForce RTX 4070 Ti" and info["commit"] == "49a2a76"
    keys = {l["key"] for l, _ in s["h4nb_config_value"]}
    assert {"eta", "eps", "dt_max", "energy_tol"} <= keys and "devices" not in keys
    assert {l["period"] for l, _ in s["h4nb_period_max_rel_err"]} == {"1"}


def test_stopped_early_and_stalled(tmp_path):
    assert make_run(tmp_path / "nan", fail_at=0.5) == 3
    make_run(tmp_path / "hang", hang_at=0.5)
    nan = Run("nan", DirSource(str(tmp_path / "nan")))
    nan.update()
    assert nan.state(now=2e9, stale_min=300) == runs.STATE_STOPPED
    hang = Run("hang", DirSource(str(tmp_path / "hang")))
    hang.update()
    m = hang.newest_mtime()
    assert hang.state(now=m + 10, stale_min=300) == runs.STATE_RUNNING
    assert hang.state(now=m + 301, stale_min=300) == runs.STATE_STALLED
    assert "h4nb_eta_seconds" not in hang.samples(now=m + 301, stale_min=300)


def test_eta_uses_recent_segments(tmp_path):
    make_run(tmp_path / "h", hang_at=0.5, t_end=1.0, interval=2.0)  # 8 segments of 0.0625 in 2 s each.
    r = Run("h", DirSource(str(tmp_path / "h")))
    r.update()
    eta = r.eta_seconds(runs.STATE_RUNNING)
    assert abs(eta - (1.0 - 0.5) / (0.0625 / 2.0)) < 1e-9


def test_stale_after_scales_with_segment_time(tmp_path):
    make_run(tmp_path / "h", hang_at=0.25, interval=200.0)
    r = Run("h", DirSource(str(tmp_path / "h")))
    r.update()
    assert r.stale_after(300) == 1000.0


def test_no_performance_file(tmp_path):
    make_run(tmp_path / "r")
    os.remove(str(tmp_path / "r" / "performance.dat"))
    r = Run("r", DirSource(str(tmp_path / "r")))
    r.update()
    s = r.samples(now=2e9, stale_min=300)
    assert "h4nb_pairs_per_second" not in s and "h4nb_wall_seconds" not in s
    assert "h4nb_energy_rel_err" in s


def test_particles_from_snapshot_without_key_n(tmp_path):
    make_run(tmp_path / "r", snap_n=77)
    p = tmp_path / "r" / "config.used"
    p.write_text("".join(l for l in p.read_text().splitlines(True) if not l.startswith("n=")))
    r = Run("r", DirSource(str(tmp_path / "r")))
    r.update()
    assert r.particles == 77


def test_particles_from_ic_snapshot_when_no_snap_files(tmp_path):
    import random
    from h4nb_metrics.fakerun import write_snapshot
    make_run(tmp_path / "r", snap_n=77)
    d = tmp_path / "r"
    for f in d.glob("snap_*.snap"):
        f.unlink()
    write_snapshot(str(d / "init.snap"), 77, 0.0, random.Random(1))
    p = d / "config.used"
    lines = [l for l in p.read_text().splitlines(True) if not l.startswith(("n=", "ic="))]
    p.write_text("".join(lines) + "ic=init.snap  # cli\n")
    r = Run("r", DirSource(str(d)))
    r.update()
    assert r.particles == 77


def test_discovery_labels_and_new_runs(tmp_path):
    make_run(tmp_path / "a" / "run1")
    make_run(tmp_path / "b" / "run1")
    make_run(tmp_path / "b" / "run2")
    (tmp_path / "notarun").mkdir()
    rs = RunSet([str(tmp_path)], max_depth=2, rescan=10)
    rs.refresh(now=0)
    assert sorted(rs.runs) == sorted([os.path.join(tmp_path.name, "a", "run1"),
                                      os.path.join(tmp_path.name, "b", "run1"), "run2"])
    make_run(tmp_path / "b" / "run3")
    rs.refresh(now=5)
    assert "run3" not in rs.runs  # Not before `rescan` seconds.
    rs.refresh(now=11)
    assert "run3" in rs.runs


def test_bad_run_does_not_stop_others(tmp_path):
    make_run(tmp_path / "good")
    make_run(tmp_path / "bad")
    os.remove(str(tmp_path / "bad" / "energy.dat"))
    os.mkdir(str(tmp_path / "bad" / "energy.dat"))  # Cannot be read as a file.
    rs = RunSet([str(tmp_path)], rescan=0)
    rs.refresh()
    assert "h4nb_energy_rel_err" in rs.runs["good"].samples(2e9, 300)
    assert rs.errors["bad"] > 0
