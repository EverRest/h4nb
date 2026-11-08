import gzip
import io
import os
import tarfile

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


def test_lists_runs_and_their_members(tmp_path):
    archive = Archive(_make_archive(str(tmp_path / "logs.tar.gz")), cache_dir=str(tmp_path / "cache"))

    runs = archive.runs()

    assert sorted(runs) == ["run1", "run2", "slurm"]
    assert runs["run1"] == ["config.used", "energy.dat", "frames/0001.snap"]
    assert runs["run2"] == ["energy.dat"]
    assert runs["slurm"] == ["slurm-7.out"]


def test_reads_snapshot_bytes_without_writing_to_cache(tmp_path):
    cache = tmp_path / "cache"
    archive = Archive(_make_archive(str(tmp_path / "logs.tar.gz")), cache_dir=str(cache))

    assert archive.read("run1", "frames/0001.snap") == b"H4NBSNAP-frame-1"
    assert not cache.exists()  # A plain member is read from the stream, not unpacked.


def test_compressed_member_is_extracted_once_to_cache(tmp_path):
    path = str(tmp_path / "logs.tar.gz")
    payload = gzip.compress(b"H4NBSNAP-packed")
    with tarfile.open(path, "w:gz") as tar:
        _add(tar, "h4nb_logs_x/run1/frames/0002.snap.gz", payload)
    cache = tmp_path / "cache"
    archive = Archive(path, cache_dir=str(cache))

    assert archive.read("run1", "frames/0002.snap.gz") == payload
    assert len(os.listdir(cache)) == 1  # The member is in the cache as one file.


def test_reread_after_archive_mtime_changes(tmp_path):
    path = _make_archive(str(tmp_path / "logs.tar.gz"), snap=b"old")
    os.utime(path, (1_000_000, 1_000_000))
    archive = Archive(path, cache_dir=str(tmp_path / "cache"))
    assert archive.read("run1", "frames/0001.snap") == b"old"

    with tarfile.open(path, "w:gz") as tar:  # Replace the archive: new run list, new mtime.
        _add(tar, "h4nb_logs_x/run3/energy.dat", b"0.0 0.0\n")
    os.utime(path, (1_000_060, 1_000_060))

    assert sorted(archive.runs()) == ["run3"]


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


def test_missing_member_raises_archive_error(tmp_path):
    archive = Archive(_make_archive(str(tmp_path / "logs.tar.gz")), cache_dir=str(tmp_path / "cache"))

    with pytest.raises(ArchiveError):
        archive.read("run9", "energy.dat")
