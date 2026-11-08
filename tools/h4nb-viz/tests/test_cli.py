import os

import pytest

from h4nb_viz import __main__ as cli


def test_serve_passes_no_browser_flag(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "serve", lambda root, **kw: calls.append((root, kw)))
    assert cli.main(["serve", str(tmp_path), "--no-browser", "--port", "8821"]) == 0
    assert calls == [(str(tmp_path), {"port": 8821, "export_dir": None, "open_browser": False})]


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
