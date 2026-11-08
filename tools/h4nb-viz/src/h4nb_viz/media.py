"""Movie export: WebM or Safari MP4 to MP4 with ffmpeg (research.md R5).

The page records with MediaRecorder. ffmpeg is optional. Without it, the server
writes the WebM file only.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

INPUT_SUFFIXES = (".webm", ".mp4")
# The container format of each input. ffmpeg needs it before -i for some inputs.
INPUT_FORMATS = {".webm": "matroska", ".mp4": "mov"}
FFMPEG_TIMEOUT = 600  # Seconds. A hung conversion must not block the server for ever.


class FfmpegError(RuntimeError):
    """ffmpeg is missing, or it failed."""


def find_ffmpeg():
    """Return the path of ffmpeg on PATH, or None."""
    return shutil.which("ffmpeg")


def to_mp4(src, dst):
    """Convert a movie to H.264 MP4. Raise FfmpegError on failure."""
    if Path(src).suffix.lower() not in INPUT_SUFFIXES:
        raise ValueError(f"not a movie file: {src}")
    exe = find_ffmpeg()
    if exe is None:
        raise FfmpegError("ffmpeg is not installed. Install ffmpeg to export MP4.")
    fmt = INPUT_FORMATS[Path(src).suffix.lower()]
    cmd = [exe, "-y", "-loglevel", "error", "-f", fmt, "-i", str(src),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(dst)]
    try:
        proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise FfmpegError(f"ffmpeg timed out after {FFMPEG_TIMEOUT} s and was stopped")
    if proc.returncode != 0:
        raise FfmpegError(f"ffmpeg failed with exit code {proc.returncode}: {proc.stderr.strip()}")
