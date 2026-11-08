import os
import stat

import pytest

from h4nb_viz import media

FAKE_FFMPEG = """#!/bin/sh
printf '%s\\n' "$@" > "$FAKE_FFMPEG_LOG"
if [ -n "$FAKE_FFMPEG_ERR" ]; then
  echo "$FAKE_FFMPEG_ERR" >&2
  exit 1
fi
exit 0
"""


@pytest.fixture
def fake_bin(tmp_path, monkeypatch):
    """A fake ffmpeg first on PATH. It writes its arguments to FAKE_FFMPEG_LOG."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "ffmpeg"
    exe.write_text(FAKE_FFMPEG)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "argv.txt"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_FFMPEG_LOG", str(log))
    monkeypatch.delenv("FAKE_FFMPEG_ERR", raising=False)
    return log


@pytest.fixture
def no_ffmpeg(tmp_path, monkeypatch):
    """PATH with no ffmpeg in it."""
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


def test_find_ffmpeg_returns_none_without_ffmpeg(no_ffmpeg):
    assert media.find_ffmpeg() is None


def test_find_ffmpeg_returns_path(fake_bin):
    found = media.find_ffmpeg()
    assert found is not None
    assert os.path.basename(found) == "ffmpeg"


def test_to_mp4_runs_ffmpeg_with_argument_list(fake_bin, tmp_path):
    src = tmp_path / "run.webm"
    dst = tmp_path / "run.mp4"
    media.to_mp4(src, dst)
    argv = fake_bin.read_text().splitlines()
    assert argv == ["-y", "-loglevel", "error", "-i", str(src), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(dst)]


def test_to_mp4_accepts_safari_mp4_input(fake_bin, tmp_path):
    src = tmp_path / "run.mp4"
    dst = tmp_path / "out.mp4"
    media.to_mp4(src, dst)
    argv = fake_bin.read_text().splitlines()
    assert argv[argv.index("-i") + 1] == str(src)


def test_to_mp4_rejects_other_input_types(fake_bin, tmp_path):
    with pytest.raises(ValueError, match="movie"):
        media.to_mp4(tmp_path / "run.png", tmp_path / "out.mp4")
    assert not fake_bin.exists()


def test_to_mp4_missing_ffmpeg_gives_clear_error(no_ffmpeg, tmp_path):
    with pytest.raises(media.FfmpegError, match="ffmpeg is not installed"):
        media.to_mp4(tmp_path / "run.webm", tmp_path / "out.mp4")


def test_to_mp4_failing_ffmpeg_gives_its_stderr(fake_bin, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_FFMPEG_ERR", "Invalid data found: bad webm header")
    with pytest.raises(media.FfmpegError, match="exit code 1: Invalid data found: bad webm header"):
        media.to_mp4(tmp_path / "run.webm", tmp_path / "out.mp4")
