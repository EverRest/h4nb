import os
import struct

import pytest

from h4nb_viz import __main__ as cli


def test_serve_passes_no_browser_flag(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "serve", lambda root, **kw: calls.append((root, kw)))
    assert cli.main(["serve", str(tmp_path), "--no-browser", "--port", "8821"]) == 0
    assert calls == [(str(tmp_path), {"port": 8821, "export_dir": None, "open_browser": False,
                      "prometheus": None, "grafana_url": None})]


def test_serve_opens_browser_by_default(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "serve", lambda root, **kw: calls.append(kw))
    cli.main(["serve", str(tmp_path)])
    assert calls[0]["open_browser"] is True and calls[0]["port"] == 8820


def test_serve_rejects_missing_root(tmp_path):
    with pytest.raises(SystemExit) as err:
        cli.main(["serve", str(tmp_path / "missing")])
    assert err.value.code == 2


def test_fake_writes_a_run(tmp_path, capsys):
    out = str(tmp_path / "demo")
    assert cli.main(["fake", out, "--n", "50", "--snaps", "2", "--t-end", "0.5"]) == 0
    assert os.path.isfile(os.path.join(out, "snap_final.snap"))
    assert "wrote the fake run" in capsys.readouterr().out


def test_fake_rejects_too_few_particles(tmp_path):
    with pytest.raises(SystemExit) as err:
        cli.main(["fake", str(tmp_path / "x"), "--n", "1"])
    assert err.value.code == 2


def test_thin_writes_thin_files(tmp_path, capsys):
    run = str(tmp_path / "run")
    cli.main(["fake", run, "--n", "200", "--snaps", "2", "--t-end", "0.5"])
    out = str(tmp_path / "thin")
    assert cli.main(["thin", run, out, "--max-points", "50", "--seed", "2"]) == 0
    files = sorted(f for f in os.listdir(out) if f.endswith(".thin"))
    assert files == ["snap_000000.thin", "snap_000001.thin", "snap_final.thin"]
    with open(os.path.join(out, "snap_final.thin"), "rb") as f:
        _, _, seed, k, _, _ = struct.unpack("<8sIIQQd", f.read(40))
    assert (seed, k) == (2, 50)
    assert "wrote 3 thin snapshots" in capsys.readouterr().out


def test_thin_defaults(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "thin_run", lambda run, out, **kw: calls.append((run, out, kw)) or [])
    cli.main(["thin", str(tmp_path), str(tmp_path / "o")])
    assert calls == [(str(tmp_path), str(tmp_path / "o"), {"max_points": 200000, "seed": 1})]


def test_thin_rejects_missing_run(tmp_path):
    with pytest.raises(SystemExit) as err:
        cli.main(["thin", str(tmp_path / "missing"), str(tmp_path / "o")])
    assert err.value.code == 2
