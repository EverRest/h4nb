import os
import struct
import tarfile

from h4nb_metrics import readers


def test_config_used_skips_comments_and_empty_values():
    text = ("# h4nb_run config.used  2026-11-07T16:00:00Z\n"
            "eta=0.0005            # file:configs/agn.cfg:4\n"
            "# snap_times=         # default, no value\n"
            "devices=0,1           # cli\n")
    assert readers.parse_config_used(text) == {"eta": "0.0005", "devices": "0,1"}


def test_run_info_and_device_line():
    info = readers.parse_run_info("tool: h4nb_run\ndevice_0: id=0 name=NVIDIA GeForce RTX 4070 Ti cc=8.9 sm_count=60\n"
                                  "command: h4nb_run out=x: y\n")
    assert info["tool"] == "h4nb_run"
    assert info["command"] == "h4nb_run out=x: y"
    d = readers.parse_device_line(info["device_0"])
    assert d == {"id": "0", "name": "NVIDIA GeForce RTX 4070 Ti", "cc": "8.9", "sm_count": "60"}


def test_header_ignores_comment_after_paren():
    line = "# time Px Py Pz Lx Ly Lz dP_rel dL_rel  (changes divided by sum m|v| and sum m|r x v|, TZ 7.3)"
    assert readers.parse_header(line) == ["time", "Px", "Py", "Pz", "Lx", "Ly", "Lz", "dP_rel", "dL_rel"]


def test_row_parsing_nan_and_bad():
    cols = ["time", "a"]
    r = readers.parse_row("1.5 -nan", cols)
    assert r["time"] == 1.5 and r["a"] != r["a"]
    assert readers.parse_row("1.5", cols) is None
    assert readers.parse_row("1.5 x", cols) is None


def test_snapshot_header():
    data = readers.SNAP_HEADER.pack(b"H4NBSNAP", 1, 0, 1024, 2.5) + b"\0" * 64
    assert readers.snapshot_header(data) == (1024, 2.5)
    assert readers.snapshot_header(b"XXXXXXXX" + data[8:]) is None
    assert readers.snapshot_header(data[:10]) is None


def test_split_lines_keeps_incomplete_rest():
    lines, rest = readers.split_lines(b"a\nb\nc")
    assert lines == ["a", "b"] and rest == b"c"


def test_archive_reads_runs_and_only_snapshot_headers(tmp_path):
    top = tmp_path / "h4nb_logs_host_20261108T000000Z"
    run = top / "run1"
    run.mkdir(parents=True)
    (run / "config.used").write_text("# h4nb_run config.used  x\nn=3  # cli\n")
    (run / "energy.dat").write_text("# time E\n0 1\n")
    (run / "snap_000000.snap").write_bytes(readers.SNAP_HEADER.pack(b"H4NBSNAP", 1, 0, 3, 0.0) + b"\1" * 192)
    (top / "MANIFEST.txt").write_text("x")
    arc = tmp_path / "a.tar.gz"
    with tarfile.open(str(arc), "w:gz") as t:
        t.add(str(top), arcname=top.name)
    runs = readers.read_archive(str(arc))
    assert list(runs) == ["run1"]
    src = runs["run1"]
    assert src.read("energy.dat") == b"# time E\n0 1\n"
    assert len(src.read("snap_000000.snap")) == readers.SNAP_HEADER.size
