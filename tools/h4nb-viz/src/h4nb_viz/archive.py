"""Runs inside the archives of tools/h4nb_pack.sh (FR-015).

Layout: <root>/<run>/<file>, <root>/MANIFEST.txt and <root>/slurm/<file>. The run name is the directory
name under <root>. The Slurm logs form the run `slurm`.

The cache in cache_dir holds two kinds of files. One is an uncompressed copy of the archive, so that a
member is read by seeking to its offset. The other is a decompressed member with a .gz, .bz2 or .xz
suffix. The cache has a size limit. The oldest files are removed first.
"""
from __future__ import annotations

import bz2
import contextlib
import gzip
import hashlib
import lzma
import os
import shutil
import tarfile
import tempfile
import threading
import zlib
from typing import Callable, Dict, IO, List, Tuple

DECOMPRESSORS: Dict[str, Callable[[bytes], bytes]] = {
    ".gz": gzip.decompress,
    ".bz2": bz2.decompress,
    ".xz": lzma.decompress,
}
OUTER_OPENERS = ((b"\x1f\x8b", gzip.open), (b"BZh", bz2.open), (b"\xfd7zXZ\x00", lzma.open))
READ_ERRORS = (tarfile.TarError, OSError, EOFError, zlib.error, lzma.LZMAError)
READ_ATTEMPTS = 3  # The archive can be replaced, and the cache can evict a file, during a read.
MAX_CACHE_BYTES = 4 * 1024**3


class ArchiveError(ValueError):
    """The archive cannot be read, or it has no such member."""


def is_archive(path: str) -> bool:
    """True when path is a regular file with a .tar, .tar.gz or .tgz suffix."""
    return os.path.isfile(path) and (
        path.endswith(".tar.gz") or path.endswith(".tgz") or path.endswith(".tar")
    )


def archive_stem(path: str) -> str:
    """The archive name without its suffix. Used in the run name `<stem>~<run>`."""
    name = os.path.basename(path)
    for suffix in (".tar.gz", ".tgz", ".tar"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _open_tar_bytes(path: str) -> IO[bytes]:
    """Open an archive for reading the uncompressed tar bytes. The signature decides the codec."""
    with open(path, "rb") as f:
        head = f.read(6)
    for sig, opener in OUTER_OPENERS:
        if head.startswith(sig):
            return opener(path, "rb")
    return open(path, "rb")


class Archive:
    """One .tar.gz of h4nb_pack.sh. The member list is read again when the file mtime or size changes."""

    def __init__(self, path: str, cache_dir: str, max_cache_bytes: int = MAX_CACHE_BYTES):
        self.path = os.path.abspath(path)
        self.cache_dir = cache_dir
        self.max_cache_bytes = max_cache_bytes
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
            data = self._cached(key, info, name, ext) if ext else self._stream(key, info)
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

    def _stream(self, key: Tuple[int, int], info: tarfile.TarInfo) -> bytes:
        for _ in range(READ_ATTEMPTS):
            copy = self._tar_copy(key)
            try:
                with tarfile.open(copy, "r:") as tar:
                    return tar.extractfile(info).read()
            except FileNotFoundError:  # Another read evicted the copy. Make it again.
                continue
            except READ_ERRORS as e:
                raise self._error(e) from e
        raise ArchiveError("%s: the cache copy keeps being removed" % self.path)

    def _tar_copy(self, key: Tuple[int, int]) -> str:
        prefix, key_tag = self._tags(key)
        target = os.path.join(self.cache_dir, "%s-%s-tar-archive.tar" % (prefix, key_tag))
        if not os.path.exists(target):
            try:
                self._write_cache(target, prefix, key_tag, self._copy_tar)
            except READ_ERRORS as e:
                raise self._error(e) from e
        else:
            with contextlib.suppress(OSError):  # Another thread can evict the copy at this moment.
                os.utime(target)
        return target

    def _copy_tar(self, f: IO[bytes]) -> None:
        with _open_tar_bytes(self.path) as src:
            shutil.copyfileobj(src, f)

    def _cached(self, key: Tuple[int, int], info: tarfile.TarInfo, name: str, ext: str) -> bytes:
        prefix, key_tag = self._tags(key)
        mem_tag = hashlib.sha256(info.name.encode()).hexdigest()[:12]
        target = os.path.join(self.cache_dir, "%s-%s-%s-%s" % (prefix, key_tag, mem_tag, os.path.basename(name)))
        try:
            with open(target, "rb") as f:
                data = f.read()
            with contextlib.suppress(OSError):
                os.utime(target)
            return data
        except FileNotFoundError:
            pass
        except OSError as e:
            raise self._error(e) from e
        try:
            data = DECOMPRESSORS[ext](self._stream(key, info))
            self._write_cache(target, prefix, key_tag, lambda f: f.write(data))
        except READ_ERRORS as e:
            raise self._error(e) from e
        return data

    def _tags(self, key: Tuple[int, int]) -> Tuple[str, str]:
        prefix = hashlib.sha256(self.path.encode()).hexdigest()[:12]
        key_tag = hashlib.sha256(("%d|%d" % key).encode()).hexdigest()[:12]
        return prefix, key_tag

    def _write_cache(self, target: str, prefix: str, key_tag: str, fill: Callable[[IO[bytes]], None]) -> None:
        os.makedirs(self.cache_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.cache_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                fill(f)
            os.replace(tmp, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        self._evict(prefix, key_tag, keep=target)

    # ponytail: the cache is the only copy of each file. Eviction is by mtime, not by use count.
    # Upgrade: a proper LRU with access times if the limit evicts files that are read often.
    def _evict(self, prefix: str, key_tag: str, keep: str) -> None:
        files = []
        for name in os.listdir(self.cache_dir):
            path = os.path.join(self.cache_dir, name)
            if name.endswith(".tmp"):
                continue
            with contextlib.suppress(OSError):  # A file can vanish when another thread removes it.
                if name.startswith(prefix + "-") and name.split("-")[1] != key_tag:
                    os.unlink(path)  # An older version of this archive.
                    continue
                st = os.stat(path)
                files.append((st.st_mtime_ns, st.st_size, path))
        total = sum(size for _mtime, size, _path in files)
        for _mtime, size, path in sorted(files):
            if total <= self.max_cache_bytes:
                break
            if path == keep:
                continue
            with contextlib.suppress(OSError):
                os.unlink(path)
                total -= size

    def materialize(self, run: str, dest_dir: str) -> str:
        """Extract every member of one run into dest_dir. Return dest_dir.

        Uncompressed tar members are read by seeking (via the cached tar copy). A member that was
        compressed on its own is decompressed into the cache first, then copied into dest_dir.
        """
        names = self.runs().get(run)
        if names is None:
            raise ArchiveError("%s: no run %s" % (self.path, run))
        os.makedirs(dest_dir, exist_ok=True)
        for name in names:
            data = self.read(run, name)
            target = os.path.join(dest_dir, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            tmp = target + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
        return dest_dir

    def _error(self, e: Exception) -> ArchiveError:
        return ArchiveError("cannot read archive %s: %s" % (self.path, str(e) or type(e).__name__))
