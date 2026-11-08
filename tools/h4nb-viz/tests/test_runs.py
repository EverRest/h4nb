import os

from h4nb_viz.runs import RunIndex, find_runs, run_state, stale_after, summarize

NOW = 1_000_000.0


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _run(tmp_path, energy_times, t_end=1.0, tmp=False):
    run_dir = str(tmp_path / "r")
    _write(os.path.join(run_dir, "config.used"), "t_end=%r  # cli\n" % t_end)
    body = "# time rel_err\n" + "".join("%r 1e-12\n" % t for t in energy_times)
    _write(os.path.join(run_dir, "energy.dat.tmp" if tmp else "energy.dat"), body)
    for name in os.listdir(run_dir):  # Make every file old, so the state does not depend on the clock.
        os.utime(os.path.join(run_dir, name), (NOW - 10, NOW - 10))
    return run_dir


def test_finished_when_last_time_reaches_t_end(tmp_path):
    assert run_state(_run(tmp_path, [0.0, 1.0]), NOW) == "finished"


def test_stopped_early_when_last_time_is_before_t_end(tmp_path):
    assert run_state(_run(tmp_path, [0.0, 0.5]), NOW) == "stopped early"


def test_running_when_tmp_file_is_fresh(tmp_path):
    run_dir = _run(tmp_path, [0.0, 0.5], tmp=True)
    assert run_state(run_dir, NOW) == "running"


def test_stalled_when_tmp_file_is_older_than_stale_limit(tmp_path):
    run_dir = _run(tmp_path, [0.0, 0.5], tmp=True)
    assert run_state(run_dir, NOW + 301) == "stalled"


def test_unknown_without_energy_table(tmp_path):
    run_dir = str(tmp_path / "r")
    _write(os.path.join(run_dir, "config.used"), "t_end=1\n")
    assert run_state(run_dir, NOW) == "unknown"


def test_unknown_without_t_end(tmp_path):
    run_dir = str(tmp_path / "r")
    _write(os.path.join(run_dir, "config.used"), "n=3\n")
    _write(os.path.join(run_dir, "energy.dat"), "# time rel_err\n1 0\n")
    assert run_state(run_dir, NOW) == "unknown"


def test_stale_after_uses_the_largest_wall_of_last_ten_rows(tmp_path):
    run_dir = str(tmp_path / "r")
    rows = "".join("%d %.1f 1 1 1.0\n" % (i, 100.0) for i in range(10))
    _write(os.path.join(run_dir, "performance.dat"), "# time wall_s block_steps active pairs_per_s\n" + rows)
    assert stale_after(run_dir) == 500.0  # 5 x 100 s, which is more than 300 s.


def test_stale_after_minimum_is_300_seconds(tmp_path):
    run_dir = str(tmp_path / "r")
    _write(os.path.join(run_dir, "performance.dat"), "# time wall_s block_steps active pairs_per_s\n0 1.0 1 1 1.0\n")
    assert stale_after(run_dir) == 300.0
    assert stale_after(str(tmp_path / "none")) == 300.0


def test_find_runs_names_and_root(fake_root):
    found = find_runs(fake_root)
    assert {n: r.path for n, r in found.items()} == {
        "eta~run1": os.path.join(fake_root, "eta", "run1"),
        "flat": os.path.join(fake_root, "flat"),
    }
    assert all(r.kind == "dir" for r in found.values())


def test_root_run_is_named_by_its_directory(tmp_path):
    root = tmp_path / "demo"
    _write(str(root / "config.used"), "t_end=1\n")
    _write(str(root / "energy.dat"), "# time\n0\n")
    found = find_runs(str(root))
    assert {n: r.path for n, r in found.items()} == {"demo": str(root)}


def test_run_index_rescans_at_most_every_five_seconds(tmp_path):
    root = str(tmp_path)
    clock = [0.0]
    index = RunIndex(root, clock=lambda: clock[0])
    assert index.runs() == {}
    _write(os.path.join(root, "a", "config.used"), "t_end=1\n")
    _write(os.path.join(root, "a", "energy.dat"), "# time\n0\n")
    clock[0] = 4.9
    assert index.runs() == {}  # Still the old list.
    clock[0] = 5.0
    assert set(index.runs()) == {"a"}


def test_summarize_fields(small_run):
    entry = summarize("run", small_run, NOW)
    assert entry["run"] == "run"
    assert entry["n"] == 200
    assert entry["t_end"] == 1.0
    assert entry["snapshots"] == 4
    assert entry["sim_time"] == 1.0
    assert entry["tables"] == ["energy.dat", "momentum.dat", "timesteps.dat", "performance.dat", "energy_periods.dat"]
    assert entry["in_prometheus"] is False and entry["prom_label"] is None


def test_central_id_of_reads_config_with_default(tmp_path):
    from h4nb_viz.runs import central_id_of

    run_dir = str(tmp_path / "r")
    _write(os.path.join(run_dir, "config.used"), "central_id=7  # cli\n")
    assert central_id_of(run_dir) == 7
    assert central_id_of(str(tmp_path / "none")) == 0


def test_run_list_is_newest_first(fake_root):
    from h4nb_viz.server import App

    app = App(fake_root)
    os.utime(os.path.join(fake_root, "flat", "config.used"), (NOW + 100, NOW + 100))
    os.utime(os.path.join(fake_root, "eta", "run1", "config.used"), (NOW, NOW))
    names = [r["run"] for r in app.run_list(NOW + 200)]
    assert names == ["flat", "eta~run1"]
