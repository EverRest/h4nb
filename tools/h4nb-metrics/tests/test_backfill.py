import io
import os

from prometheus_client.openmetrics.parser import text_string_to_metric_families

from helpers import make_run, snapshot_tree
from h4nb_metrics.backfill import load_runs, write_openmetrics

START = 1793527200.0


def backfill(paths):
    buf = io.StringIO()
    write_openmetrics(load_runs(paths), buf)
    return buf.getvalue()


def test_valid_openmetrics_with_timestamps(tmp_path):
    make_run(tmp_path / "r", interval=2.0)
    text = backfill([str(tmp_path)])
    assert text.endswith("# EOF\n")
    fams = {f.name: f for f in text_string_to_metric_families(text)}
    err = fams["h4nb_energy_rel_err"].samples
    assert len(err) == 17  # t = 0 and 16 diag lines.
    assert all(s.labels["origin"] == "backfill" and s.labels["run"] == "r" for s in err)
    ts = [float(s.timestamp) for s in err]
    assert ts[0] == START and ts[1] == START + 2.0 and ts[-1] == START + 32.0
    wall = fams["h4nb_wall_seconds"].samples
    assert wall[-1].name == "h4nb_wall_seconds_total" and wall[-1].value == 32.0
    state = fams["h4nb_run_state"].samples
    assert [s.value for s in state[:-1]] == [0] * 16 and state[-1].value == 1


def test_deterministic(tmp_path):
    make_run(tmp_path / "r")
    assert backfill([str(tmp_path)]) == backfill([str(tmp_path)])  # FR-017


def test_even_spread_without_performance(tmp_path):
    make_run(tmp_path / "r")
    p = str(tmp_path / "r" / "performance.dat")
    os.remove(p)
    e = str(tmp_path / "r" / "energy.dat")
    os.utime(e, (START + 100, START + 100))
    fams = {f.name: f for f in text_string_to_metric_families(backfill([str(tmp_path)]))}
    ts = [float(s.timestamp) for s in fams["h4nb_sim_time"].samples]
    assert ts[0] == START and abs(ts[-1] - (START + 100)) < 1e-6 and abs(ts[8] - (START + 50)) < 1e-6


def test_stalled_archive_run_and_read_only(tmp_path):
    make_run(tmp_path / "h", hang_at=0.5)
    before = snapshot_tree(tmp_path)
    fams = {f.name: f for f in text_string_to_metric_families(backfill([str(tmp_path)]))}
    assert fams["h4nb_run_state"].samples[-1].value == 3
    assert "h4nb_eta_seconds" not in fams
    assert snapshot_tree(tmp_path) == before
