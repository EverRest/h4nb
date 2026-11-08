"""Runs inside the archives of tools/h4nb_pack.sh (FR-015).

Layout: <root>/<run>/<file>, <root>/MANIFEST.txt and <root>/slurm/<file>. The run name is the directory
name under <root>. The Slurm logs form the run `slurm`. A plain member is streamed from the archive. A
member with a .gz, .bz2 or .xz suffix is decompressed once into cache_dir.
"""
from __future__ import annotations

import bz2
import contextlib
import gzip
import hashlib
import lzma
import os
import tarfile
import tempfile
import threading
import zlib
from typing import Callable, Dict, List, Tuple

DECOMPRESSORS: Dict[str, Callable[[bytes], bytes]] = {
    ".gz": gzip.decompress,
    ".bz2": bz2.decompress,
    ".xz": lzma.decompress,
}
READ_ERRORS = (tarfile.TarError, OSError, EOFError, zlib.error, lzma.LZMAError)
READ_ATTEMPTS = 3  # The archive can be replaced during a read. Then the read starts again.


class ArchiveError(ValueError):
    """The archive cannot be read, or it has no such member."""


class Archive:
    """One .tar.gz of h4nb_pack.sh. The member list is read again when the file mtime or size changes."""

    def __init__(self, path: str, cache_dir: str):
        self.path = os.path.abspath(path)
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self._key: Tuple[int, int] = (-1, -1)
        self._members: Dict[str, Dict[str, tarfile.TarInfo]] = {}

    def runs(self) -> Dict[str, List[str]]:
        """Return {run name: sorted member names}. A member name is the path inside the run directory."""
        _key, members = self._index()
        return {run: sorted(files) for run, files in members.items()}

    def read(self, run: str, name: str) -> bytes:
        """Return the bytes of one member. A member with a .gz, .bz2 or .xz suffix is returned decompressed."""
        for _ in range(READ_ATTEMPTS):
            key, members = self._index()
            info = members.get(run, {}).get(name)
            if info is None:
                raise ArchiveError("%s: no member %s/%s" % (self.path, run, name))
            ext = next((e for e in DECOMPRESSORS if name.endswith(e)), None)
            data = self._cached(key, info, name, ext) if ext else self._stream(info)
            if self._stat_key() == key:  # The bytes belong to the archive that the index describes.
                return data
        raise ArchiveError("%s: the archive changed during the read" % self.path)

    def _index(self) -> Tuple[Tuple[int, int], Dict[str, Dict[str, tarfile.TarInfo]]]:
        with self._lock:
            key = self._stat_key()
            if key != self._key:
                self._members = self._scan()
                self._key = key
            return key, self._members

    def _stat_key(self) -> Tuple[int, int]:
        try:
            st = os.stat(self.path)
        except OSError as e:
            raise self._error(e) from e
        return st.st_mtime_ns, st.st_size

    def _scan(self) -> Dict[str, Dict[str, tarfile.TarInfo]]:
        runs: Dict[str, Dict[str, tarfile.TarInfo]] = {}
        try:
            with tarfile.open(self.path, "r:*") as tar:
                for info in tar:
                    parts = info.name.split("/")
                    # The root and MANIFEST.txt have fewer than three parts. Skip "..": it is not a member.
                    if info.isfile() and len(parts) >= 3 and ".." not in parts:
                        runs.setdefault(parts[1], {})["/".join(parts[2:])] = info
        except READ_ERRORS as e:
            raise self._error(e) from e
        return runs

    # ponytail: gzip cannot seek, so each read streams from the start of the archive. Cost is about
    # N times the archive size for N frames. Upgrade: a seekable index of the stream, if reads get slow.
    def _stream(self, info: tarfile.TarInfo) -> bytes:
        try:
            with tarfile.open(self.path, "r:*") as tar:
                return tar.extractfile(info).read()
        except READ_ERRORS as e:
            raise self._error(e) from e

    def _cached(self, key: Tuple[int, int], info: tarfile.TarInfo, name: str, ext: str) -> bytes:
        # Cache names hold the archive key. A file of an older key is removed after a new one is written.
        prefix = hashlib.sha256(self.path.encode()).hexdigest()[:12]
        key_tag = hashlib.sha256(("%d|%d" % key).encode()).hexdigest()[:12]
        mem_tag = hashlib.sha256(info.name.encode()).hexdigest()[:12]
        target = os.path.join(self.cache_dir, "%s-%s-%s-%s" % (prefix, key_tag, mem_tag, os.path.basename(name)))
        try:
            if not os.path.exists(target):
                data = DECOMPRESSORS[ext](self._stream(info))
                self._write_cache(target, data, prefix, key_tag)
            with open(target, "rb") as f:
                return f.read()
        except READ_ERRORS as e:
            raise self._error(e) from e

    def _write_cache(self, target: str, data: bytes, prefix: str, key_tag: str) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        for old in os.listdir(self.cache_dir):  # Remove files of this archive with an older key.
            if old.startswith(prefix + "-") and old.split("-")[1] != key_tag:
                with contextlib.suppress(OSError):
                    os.unlink(os.path.join(self.cache_dir, old))

    def _error(self, e: Exception) -> ArchiveError:
        return ArchiveError("cannot read archive %s: %s" % (self.path, str(e) or type(e).__name__))
