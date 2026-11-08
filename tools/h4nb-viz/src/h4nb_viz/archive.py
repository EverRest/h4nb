"""Runs inside the archives of tools/h4nb_pack.sh (FR-015).

Layout: <root>/<run>/<file>, <root>/MANIFEST.txt and <root>/slurm/<file>. The run name is the directory
name under <root>. The Slurm logs form the run `slurm`. The archive is read in place, not unpacked.
"""
from __future__ import annotations

import hashlib
import os
import tarfile
import threading
import zlib
from typing import Dict, List, Tuple

COMPRESSED = (".gz", ".bz2", ".xz")  # A member with one of these suffixes is extracted to the cache.


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
        """Return the bytes of one member. A member with a compression suffix is extracted to cache_dir once."""
        key, members = self._index()
        info = members.get(run, {}).get(name)
        if info is None:
            raise ArchiveError("%s: no member %s/%s" % (self.path, run, name))
        if name.endswith(COMPRESSED):
            return self._read_cached(key, info, name)
        return self._stream(info)

    def _index(self) -> Tuple[Tuple[int, int], Dict[str, Dict[str, tarfile.TarInfo]]]:
        with self._lock:
            try:
                st = os.stat(self.path)
            except OSError as e:
                raise self._error(e) from e
            key = (st.st_mtime_ns, st.st_size)
            if key != self._key:
                self._members = self._scan()
                self._key = key
            return key, self._members

    def _scan(self) -> Dict[str, Dict[str, tarfile.TarInfo]]:
        runs: Dict[str, Dict[str, tarfile.TarInfo]] = {}
        try:
            with tarfile.open(self.path, "r:*") as tar:
                for info in tar:
                    parts = info.name.split("/")
                    if info.isfile() and len(parts) >= 3:  # Skip MANIFEST.txt at the top level.
                        runs.setdefault(parts[1], {})["/".join(parts[2:])] = info
        except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
            raise self._error(e) from e
        return runs

    def _stream(self, info: tarfile.TarInfo) -> bytes:
        # Gzip cannot seek to a member, so the stream is read up to it. Nothing is written to disk.
        try:
            with tarfile.open(self.path, "r:*") as tar:
                return tar.extractfile(info).read()
        except (tarfile.TarError, OSError, EOFError, zlib.error) as e:
            raise self._error(e) from e

    def _read_cached(self, key: Tuple[int, int], info: tarfile.TarInfo, name: str) -> bytes:
        # The cache name holds the archive mtime and size, so an old copy is never read again.
        tag = "%s|%d|%d|%s" % (self.path, key[0], key[1], info.name)
        digest = hashlib.sha256(tag.encode()).hexdigest()[:16]
        target = os.path.join(self.cache_dir, "%s-%s" % (digest, os.path.basename(name)))
        if not os.path.exists(target):
            data = self._stream(info)
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(target + ".tmp", "wb") as f:
                f.write(data)
            os.replace(target + ".tmp", target)
        with open(target, "rb") as f:
            return f.read()

    def _error(self, e: Exception) -> ArchiveError:
        return ArchiveError("cannot read archive %s: %s" % (self.path, str(e) or type(e).__name__))
