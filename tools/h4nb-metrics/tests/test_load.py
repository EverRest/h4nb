"""backfill --load runs promtool on the Prometheus data volume, with Prometheus stopped (plan P6, spec FR-016)."""
import argparse
import os
import subprocess

import h4nb_metrics.cli as cli
from helpers import make_run


def fake_docker(monkeypatch, tmp_path, fail_op=None):
    """Replaces docker. Records each compose call. The call whose operation is fail_op returns 1."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        op = cmd[cmd.index("--project-directory") + 2]
        rc = 1 if op == fail_op else 0
        return subprocess.CompletedProcess(cmd, rc)

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(cli.subprocess, "run", run)
    compose = tmp_path / "compose"
    (compose / "backfill").mkdir(parents=True)
    om = compose / "backfill" / "h4nb_backfill.om"
    om.write_text("# EOF\n")
    return calls, compose, str(om)


def ops(calls):
    return [c[c.index("--project-directory") + 2] for c in calls]


def test_load_stops_promtool_then_starts(tmp_path, monkeypatch):
    calls, compose, om = fake_docker(monkeypatch, tmp_path)
    assert cli.load_into_compose(str(compose), om) == 0
    assert ops(calls) == ["stop", "run", "start"]
    run_cmd = calls[1]
    assert run_cmd[run_cmd.index("--entrypoint") + 1] == "promtool"
    assert run_cmd[run_cmd.index("openmetrics") + 1] == "/backfill/h4nb_backfill.om"


def test_failed_promtool_still_starts_prometheus(tmp_path, monkeypatch):
    calls, compose, om = fake_docker(monkeypatch, tmp_path, fail_op="run")
    assert cli.load_into_compose(str(compose), om) == 1
    assert ops(calls) == ["stop", "run", "start"]  # start is still called


def test_failed_stop_runs_nothing_else(tmp_path, monkeypatch):
    calls, compose, om = fake_docker(monkeypatch, tmp_path, fail_op="stop")
    assert cli.load_into_compose(str(compose), om) == 1
    assert ops(calls) == ["stop"]


def test_load_refuses_file_outside_backfill(tmp_path, monkeypatch):
    calls, compose, _ = fake_docker(monkeypatch, tmp_path)
    other = tmp_path / "elsewhere.om"
    other.write_text("# EOF\n")
    assert cli.load_into_compose(str(compose), str(other)) == 2
    assert calls == []  # no docker command runs


def test_name_starting_with_dots_is_inside_backfill(tmp_path, monkeypatch):
    calls, compose, _ = fake_docker(monkeypatch, tmp_path)
    inside = compose / "backfill" / "..x.om"
    inside.write_text("# EOF\n")
    assert cli.load_into_compose(str(compose), str(inside)) == 0


def backfill_args(tmp_path, output, load=True):
    return argparse.Namespace(paths=[str(tmp_path / "runs")], max_depth=2, output=output, load=load,
                              compose_dir=str(tmp_path / "compose"))


def test_backfill_load_checks_path_before_writing(tmp_path, monkeypatch):
    calls, compose, _ = fake_docker(monkeypatch, tmp_path)
    make_run(tmp_path / "runs" / "r1")
    target = tmp_path / "outside.om"
    assert cli.cmd_backfill(backfill_args(tmp_path, str(target))) == 2
    assert not target.exists()  # refused before the file is written
    assert calls == []


def test_backfill_load_default_path_goes_to_compose_backfill(tmp_path, monkeypatch):
    calls, compose, _ = fake_docker(monkeypatch, tmp_path)
    make_run(tmp_path / "runs" / "r1")
    assert cli.cmd_backfill(backfill_args(tmp_path, "-")) == 0
    written = compose / "backfill" / "h4nb-backfill.om"
    assert written.exists() and os.path.getsize(written) > 0
    assert ops(calls) == ["stop", "run", "start"]
