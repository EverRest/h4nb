"""Readers for the output files of h4nb_run (specs/001-hermite-nbody-lib/contracts/file-formats.md).

The readers only read. They never write, rename or lock a file (specs/002-run-metrics FR-001).
"""
from __future__ import annotations

import io
import os
import struct
import tarfile
from typing import Dict, List, Optional, Tuple

TABLES = ("energy.dat", "momentum.dat", "timesteps.dat", "performance.dat", "energy_periods.dat")
SNAP_MAGIC = b"H4NBSNAP"
SNAP_HEADER = struct.Struct("<8sIIQd")  # magic, version, reserved, n, time: 32 bytes


def parse_config_used(text: str) -> Dict[str, str]:
    """Parses `key=value  # source` lines. A key without a value is written as `# key=` and is skipped."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        body = line.split("#", 1)[0].strip()
        if "=" not in body:
            continue
        key, value = body.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def parse_run_info(text: str) -> Dict[str, str]:
    """Parses `key: value` lines of run_info.txt."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key and " " not in key:
            out[key] = value.strip()
    return out


def parse_device_line(value: str) -> Dict[str, str]:
    """Parses `id=0 name=NVIDIA GeForce RTX 4070 Ti cc=8.9 sm_count=60`. A name can contain spaces."""
    out: Dict[str, str] = {}
    key = None
    for tok in value.split():
        if "=" in tok:
            key, v = tok.split("=", 1)
            out[key] = v
        elif key is not None:
            out[key] += " " + tok
    return out


def parse_header(line: str) -> List[str]:
    """Column names of a `# a b c  (comment)` header line. Text from the first `(` is a comment."""
    names = []
    for tok in line.lstrip("#").split():
        if tok.startswith("("):
            break
        names.append(tok)
    return names


def parse_row(line: str, columns: List[str]) -> Optional[Dict[str, float]]:
    """One data line as a dict. Returns None for a line with a wrong field count or a field that is not a number."""
    fields = line.split()
    if len(fields) < len(columns):
        return None
    try:
        return {c: float(f) for c, f in zip(columns, fields)}
    except ValueError:
        return None


def snapshot_header(data: bytes) -> Optional[Tuple[int, float]]:
    """(n, time) from the first 32 bytes of a snapshot, or None when it is not a v1 snapshot."""
    if len(data) < SNAP_HEADER.size:
        return None
    magic, version, _, n, time = SNAP_HEADER.unpack(data[: SNAP_HEADER.size])
    if magic != SNAP_MAGIC or version != 1:
        return None
    return int(n), float(time)


class FileInfo:
    __slots__ = ("size", "inode", "mtime")

    def __init__(self, size: int, inode: int, mtime: float):
        self.size, self.inode, self.mtime = size, inode, mtime


class DirSource:
    """Files of one run directory on disk."""

    def __init__(self, path: str):
        self.path = path

    def stat(self, name: str) -> Optional[FileInfo]:
        try:
            st = os.stat(os.path.join(self.path, name))
        except OSError:
            return None
        return FileInfo(st.st_size, st.st_ino, st.st_mtime)

    def read(self, name: str, offset: int = 0, size: int = -1) -> bytes:
        with open(os.path.join(self.path, name), "rb") as f:
            f.seek(offset)
            return f.read(size)

    def names(self) -> List[str]:
        try:
            return os.listdir(self.path)
        except OSError:
            return []

    def resolve(self, path: str) -> Optional[str]:
        """An absolute path for a path from config.used (`ic`). Relative paths are tried from the run directory
        and from its parent, because h4nb_run gets them relative to its working directory."""
        if os.path.isabs(path):
            return path if os.path.exists(path) else None
        for base in (self.path, os.path.dirname(os.path.abspath(self.path))):
            p = os.path.join(base, path)
            if os.path.exists(p):
                return p
        return None


class MemorySource:
    """Files of one run directory inside an archive. The archive is read once; its files do not change."""

    def __init__(self, label: str, files: Dict[str, bytes], mtimes: Dict[str, float]):
        self.path = label
        self._files = files
        self._mtimes = mtimes

    def stat(self, name: str) -> Optional[FileInfo]:
        if name not in self._files:
            return None
        return FileInfo(len(self._files[name]), 0, self._mtimes.get(name, 0.0))

    def read(self, name: str, offset: int = 0, size: int = -1) -> bytes:
        data = self._files[name]
        return data[offset:] if size < 0 else data[offset : offset + size]

    def names(self) -> List[str]:
        return list(self._files)

    def resolve(self, path: str) -> Optional[str]:
        return None


def read_archive(path: str) -> Dict[str, MemorySource]:
    """Run directories of an h4nb_pack.sh archive. Key: run path inside the archive (without the top directory).
    Snapshots are not loaded. Only their 32-byte header is kept, under the snapshot name."""
    runs: Dict[str, Dict[str, bytes]] = {}
    mtimes: Dict[str, Dict[str, float]] = {}
    with tarfile.open(path, "r:*") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        dirs = {os.path.dirname(m.name) for m in members if os.path.basename(m.name) == "config.used"}
        for m in members:
            d, base = os.path.dirname(m.name), os.path.basename(m.name)
            if d not in dirs:
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            data = f.read(SNAP_HEADER.size) if base.endswith(".snap") else f.read()
            runs.setdefault(d, {})[base] = data
            mtimes.setdefault(d, {})[base] = float(m.mtime)
    out = {}
    for d, files in runs.items():
        parts = d.split("/", 1)
        rel = parts[1] if len(parts) == 2 else parts[0]  # Remove the top directory h4nb_logs_<host>_<time>.
        out[rel] = MemorySource(os.path.basename(path) + ":" + rel, files, mtimes[d])
    return out


def is_archive(path: str) -> bool:
    return os.path.isfile(path) and (path.endswith(".tar.gz") or path.endswith(".tgz") or path.endswith(".tar"))


def read_text(source, name: str) -> Optional[str]:
    if source.stat(name) is None:
        return None
    try:
        return source.read(name).decode("utf-8", "replace")
    except OSError:
        return None


def split_lines(buf: bytes) -> Tuple[List[str], bytes]:
    """Complete lines of a buffer, and the rest after the last newline (an incomplete line)."""
    cut = buf.rfind(b"\n")
    if cut < 0:
        return [], buf
    text = buf[: cut + 1].decode("utf-8", "replace")
    return text.splitlines(), buf[cut + 1 :]


def _bytes_io(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)
