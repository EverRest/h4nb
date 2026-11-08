import bz2
import gzip
import io
import lzma
import os
import tarfile
import threading

import pytest

from h4nb_viz.archive import Archive, ArchiveError


def _add(tar, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _make_archive(path, snap=b"H4NBSNAP-frame-1", energy=b"# time rel_err\n0.0 1e-12\n"):
    """The layout of tools/h4nb_pack.sh: <root>/<run>/<file>, <root>/MANIFEST.txt, <root>/slurm/*."""
    root = "h4nb_logs_host_20261108T000000Z"
    with tarfile.open(path, "w:gz") as tar:
        _add(tar, root + "/MANIFEST.txt", b"h4nb_pack manifest\n")
        _add(tar, root + "/run1/config.used", b"t_end=1.0  # cli\n")
        _add(tar, root + "/run1/energy.dat", energy)
        _add(tar, root + "/run1/frames/0001.snap", snap)
        _add(tar, root + "/run2/energy.dat", energy)
        _add(tar, root + "/slurm/slurm-7.out", b"job output\n")
    return path


def _replace(path, members, mtime):
    """Write a new .tar.gz at path with {member name: bytes} and set its mtime."""
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            _add(tar, name, data)
    os.utime(path, (mtime, mtime))


def test_lists_runs_and_their_members(tmp_path):
    archive = Archive(_make_archive(str(tmp_path / "logs.tar.gz")), cache_dir=str(tmp_path / "cache"))

    runs = archive.runs()

    assert sorted(runs) == ["run1", "run2", "slurm"]
    assert runs["run1"] == ["config.used", "energy.dat", "frames/0001.snap"]
    assert runs["run2"] == ["energy.dat"]
    assert runs["slurm"] == ["slurm-7.out"]


def test_plain_read_uses_one_uncompressed_copy_in_cache(tmp_path):
    path = _make_archive(str(tmp_path / "logs.tar.gz"))
    cache = tmp_path / "cache"
    archive = Archive(path, cache_dir=str(cache))

    assert archive.read("run1", "frames/0001.snap") == b"H4NBSNAP-frame-1"
    copies = os.listdir(cache)
    assert len(copies) == 1
    with open(os.path.join(cache, copies[0]), "rb") as f, gzip.open(path) as g:
        assert f.read() == g.read()  # The copy is the uncompressed tar, so reads seek to an offset.


def test_plain_tar_member_is_read(tmp_path):
    path = str(tmp_path / "logs.tar")
    with tarfile.open(path, "w") as tar:
        _add(tar, "h4nb_logs_x/run1/frames/0001.snap", b"plain")
    archive = Archive(path, cache_dir=str(tmp_path / "cache"))

    assert archive.read("run1", "frames/0001.snap") == b"plain"


def test_compressed_member_is_returned_decompressed_and_cached_once(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        _add(tar, "h4nb_logs_x/run1/frames/0002.snap.gz", gzip.compress(b"H4NBSNAP-packed"))
        _add(tar, "h4nb_logs_x/run1/frames/0003.snap.bz2", bz2.compress(b"H4NBSNAP-bz2"))
        _add(tar, "h4nb_logs_x/run1/frames/0004.snap.xz", lzma.compress(b"H4NBSNAP-xz"))
    cache = tmp_path / "cache"
    archive = Archive(path, cache_dir=str(cache))

    assert archive.read("run1", "frames/0002.snap.gz") == b"H4NBSNAP-packed"
    assert archive.read("run1", "frames/0002.snap.gz") == b"H4NBSNAP-packed"
    assert archive.read("run1", "frames/0003.snap.bz2") == b"H4NBSNAP-bz2"
    assert archive.read("run1", "frames/0004.snap.xz") == b"H4NBSNAP-xz"
    assert len(os.listdir(cache)) == 4  # Three members and the archive copy. No .tmp left.


def test_cache_stays_within_its_size_limit(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    members = {"frames/%04d.snap.gz" % i: b"x" * 1000 + bytes([i]) for i in range(5)}
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            _add(tar, "h4nb_logs_x/run1/" + name, gzip.compress(data))
    cache = tmp_path / "cache"
    archive = Archive(path, cache_dir=str(cache), max_cache_bytes=1)

    for name, data in members.items():
        assert archive.read("run1", name) == data  # The file just written is kept for this read.
    assert len(os.listdir(cache)) <= 2  # The newest member and the archive copy.


def test_no_eviction_while_cache_is_under_its_limit(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        for i in range(5):
            _add(tar, "h4nb_logs_x/run1/frames/%04d.snap.gz" % i, gzip.compress(b"x" * 100))
    cache = tmp_path / "cache"
    archive = Archive(path, cache_dir=str(cache), max_cache_bytes=10**9)

    for i in range(5):
        archive.read("run1", "frames/%04d.snap.gz" % i)
    assert len(os.listdir(cache)) == 6  # Five members and the archive copy.


def test_cache_of_old_archive_version_is_removed(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    _replace(path, {"h4nb_logs_x/run1/frames/0002.snap.gz": gzip.compress(b"old")}, 1_000_000)
    cache = tmp_path / "cache"
    archive = Archive(path, cache_dir=str(cache))
    assert archive.read("run1", "frames/0002.snap.gz") == b"old"

    _replace(path, {"h4nb_logs_x/run1/frames/0002.snap.gz": gzip.compress(b"new")}, 1_000_060)

    assert archive.read("run1", "frames/0002.snap.gz") == b"new"
    assert len(os.listdir(cache)) == 2  # The new member and the new archive copy. Old files are gone.


def test_concurrent_first_reads_of_compressed_member_all_succeed(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    _replace(path, {"h4nb_logs_x/run1/frames/0002.snap.gz": gzip.compress(b"packed")}, 1_000_000)
    archive = Archive(path, cache_dir=str(tmp_path / "cache"))
    results, errors = [], []
    start = threading.Barrier(16)

    def worker():
        start.wait()
        try:
            results.append(archive.read("run1", "frames/0002.snap.gz"))
        except Exception as e:  # The test reports any failure, whatever its type.
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert results == [b"packed"] * 16


def test_failed_cache_write_leaves_no_tmp_file_and_raises_archive_error(tmp_path, monkeypatch):
    path = str(tmp_path / "logs.tar.gz")
    _replace(path, {"h4nb_logs_x/run1/frames/0002.snap.gz": gzip.compress(b"packed")}, 1_000_000)
    cache = tmp_path / "cache"
    archive = Archive(path, cache_dir=str(cache))

    def fail(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(ArchiveError, match="disk full"):
        archive.read("run1", "frames/0002.snap.gz")
    assert [f for f in os.listdir(cache) if f.endswith(".tmp")] == []


def test_reread_after_archive_mtime_changes_returns_new_bytes(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    _replace(path, {"h4nb_logs_x/run1/frames/0001.snap": b"old"}, 1_000_000)
    archive = Archive(path, cache_dir=str(tmp_path / "cache"))
    assert archive.read("run1", "frames/0001.snap") == b"old"

    _replace(path, {"h4nb_logs_x/run3/energy.dat": b"0.0 0.0\n",
                    "h4nb_logs_x/run1/frames/0001.snap": b"new"}, 1_000_060)

    assert sorted(archive.runs()) == ["run1", "run3"]
    assert archive.read("run1", "frames/0001.snap") == b"new"


def test_archive_replaced_during_read_is_read_again(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    _replace(path, {"h4nb_logs_x/run1/frames/0001.snap": b"old"}, 1_000_000)
    archive = Archive(path, cache_dir=str(tmp_path / "cache"))
    archive.runs()  # Index the old archive.
    real_stream = archive._stream
    replaced = []

    def stream_then_replace(key, info):
        data = real_stream(key, info)
        if not replaced:  # The archive changes after the index was built and the member was read.
            replaced.append(True)
            _replace(path, {"h4nb_logs_x/run1/frames/0001.snap": b"new"}, 1_000_060)
        return data

    archive._stream = stream_then_replace

    assert archive.read("run1", "frames/0001.snap") == b"new"


def test_damaged_archive_raises_clear_error(tmp_path):
    path = _make_archive(str(tmp_path / "logs.tar.gz"))
    size = os.path.getsize(path)
    with open(path, "r+b") as f:
        f.truncate(size // 2)
    archive = Archive(path, cache_dir=str(tmp_path / "cache"))

    with pytest.raises(ArchiveError) as info:
        archive.runs()
    assert "logs.tar.gz" in str(info.value)
    assert "cannot read archive" in str(info.value)


def test_non_archive_file_raises_archive_error(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    with open(path, "wb") as f:
        f.write(b"not an archive at all")
    archive = Archive(path, cache_dir=str(tmp_path / "cache"))

    with pytest.raises(ArchiveError, match="cannot read archive"):
        archive.runs()


def test_empty_archive_has_no_runs(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    _replace(path, {}, 1_000_000)
    archive = Archive(path, cache_dir=str(tmp_path / "cache"))

    assert archive.runs() == {}


def test_directory_and_parent_path_members_are_not_listed(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    with tarfile.open(path, "w:gz") as tar:
        folder = tarfile.TarInfo("h4nb_logs_x/run4/frames")
        folder.type = tarfile.DIRTYPE
        tar.addfile(folder)
        _add(tar, "h4nb_logs_x/run1/../../evil.dat", b"x")
    archive = Archive(path, cache_dir=str(tmp_path / "cache"))

    assert archive.runs() == {}


def test_missing_member_raises_archive_error(tmp_path):
    archive = Archive(_make_archive(str(tmp_path / "logs.tar.gz")), cache_dir=str(tmp_path / "cache"))

    with pytest.raises(ArchiveError):
        archive.read("run9", "energy.dat")
