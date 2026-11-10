import math
import os
import shutil

import numpy as np
import pytest

from h4nb_viz import gallery


def test_s_stars_table_loads():
    stars = gallery.load_s_stars()
    names = [s["name"] for s in stars]
    assert len(stars) >= 10
    assert "S2" in names
    for s in stars:
        assert 0.0 < s["e"] < 1.0
        assert s["a_arcsec"] > 0.0
        assert s["p_year"] > 0.0


def test_s_star_periods_follow_kepler():
    # One central mass: P is proportional to a^1.5. This checks the copied numbers.
    stars = gallery.load_s_stars()
    s2 = next(s for s in stars if s["name"] == "S2")
    for s in stars:
        expected = s2["p_year"] * (s["a_arcsec"] / s2["a_arcsec"]) ** 1.5
        assert s["p_year"] == pytest.approx(expected, rel=0.05), s["name"]


from h4nb_viz.fake import kepler_state


def test_kepler_state_high_e_keeps_energy():
    # The S-stars have e up to about 0.98. The specific energy must be -1 / (2a) at each time.
    a = np.full(8, 1.0)
    e = np.full(8, 0.98)
    zero = np.zeros(8)
    m0 = np.linspace(0.0, 2 * math.pi, 8, endpoint=False)
    for t in (0.0, 0.3, 1.7, 5.0):
        pos, vel = kepler_state(a, e, zero, zero, zero, m0, t)
        r = np.linalg.norm(pos, axis=1)
        energy = 0.5 * np.sum(vel * vel, axis=1) - 1.0 / r
        assert np.allclose(energy, -0.5, atol=1e-9)


def test_s2_is_at_pericentre_at_tp():
    stars = gallery.load_s_stars()
    s2 = next(s for s in stars if s["name"] == "S2")
    frames = gallery.s_star_frames([s2], start=s2["tp_year"] - 1.0, end=s2["tp_year"], frames=2)
    r = np.linalg.norm(frames[-1][0])
    assert r == pytest.approx(1.0 - s2["e"], rel=1e-6)


@pytest.mark.parametrize("name", ["S14", "S175"])
def test_other_star_is_at_pericentre_at_its_own_tp(name):
    # a is scaled to S2 by the Kepler rule from the period: a = (P / P_S2) ** (2/3).
    stars = gallery.load_s_stars()
    s2 = next(s for s in stars if s["name"] == "S2")
    s = next(s for s in stars if s["name"] == name)
    frames = gallery.s_star_frames([s2, s], start=s["tp_year"] - 1.0, end=s["tp_year"], frames=2)
    r = np.linalg.norm(frames[-1][1])
    expected = (s["p_year"] / s2["p_year"]) ** (2.0 / 3.0) * (1.0 - s["e"])
    assert r == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize("make, count", [
    (lambda: gallery.s_star_frames(gallery.load_s_stars(), frames=5), len(gallery.load_s_stars())),
    (lambda: gallery.agn_disk_frames(n=500, frames=5), 500),
    (lambda: gallery.cluster_frames(n=500, frames=5), 500),
])
def test_scene_frames_have_constant_shape(make, count):
    frames = make()
    assert len(frames) == 5
    k = frames[0].shape[0]
    assert k == count
    for f in frames:
        assert f.shape == (k, 3)
        assert np.all(np.isfinite(f))


def test_agn_disk_is_thin_and_in_range():
    pos = gallery.agn_disk_frames(n=2000, frames=1)[0]
    r = np.linalg.norm(pos[:, :2], axis=1)
    assert r.min() > 0.5 and r.max() < 13.0
    assert np.abs(pos[:, 2]).max() < 0.05 * r.max()


def test_render_empty_is_black():
    img = gallery.render(np.zeros((0, 3)), size=32, center=False)
    assert img.shape == (32, 32, 3)
    assert img.dtype == np.uint8
    assert img.max() == 0


def test_render_point_at_origin_lights_the_middle():
    img = gallery.render(np.zeros((1, 3)), size=33, center=False)
    assert img[16, 16].sum() > 0
    assert img[0, 0].sum() == 0


def test_render_center_marker():
    img = gallery.render(np.zeros((0, 3)), size=33, center=True)
    assert img[16, 16].sum() > 0


def test_render_drops_points_outside_the_view():
    img = gallery.render(np.array([[5.0, 5.0, 0.0]]), size=32, extent=1.0, center=False)
    assert img.max() == 0


def test_render_point_upper_right():
    img = gallery.render(np.array([[0.5, 0.5, 0.0]]), size=33, extent=1.0, azimuth=0.0, tilt=0.0, center=False)
    rows, cols = np.nonzero(img.sum(axis=2))
    assert rows.max() < 16 and cols.min() > 16


def test_render_point_lower_left():
    img = gallery.render(np.array([[-0.5, -0.5, 0.0]]), size=33, extent=1.0, azimuth=0.0, tilt=0.0, center=False)
    rows, cols = np.nonzero(img.sum(axis=2))
    assert rows.min() > 16 and cols.max() < 16


def test_render_two_points_in_one_pixel_are_brighter():
    # The frame is normalised to its own peak. Four far points set the same peak in both frames.
    far = np.array([[-0.5, -0.5, 0.0]] * 4)
    one = gallery.render(np.vstack([[[0.5, 0.5, 0.0]], far]), size=33, extent=1.0, center=False)
    two = gallery.render(np.vstack([[[0.5, 0.5, 0.0]] * 2, far]), size=33, extent=1.0, center=False)
    assert two[8, 24].astype(int).sum() > one[8, 24].astype(int).sum()


def _fake_ffmpeg(tmp_path, monkeypatch, body):
    exe = tmp_path / "bin" / "ffmpeg"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n" + body)
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(exe.parent) + os.pathsep + os.environ["PATH"])


def test_write_gif_failure_reports_stderr_and_removes_tmp(tmp_path, monkeypatch):
    # The fake ffmpeg makes the temporary file, prints to stderr and fails.
    _fake_ffmpeg(tmp_path, monkeypatch, 'for last; do :; done\necho partial > "$last"\necho boom-from-ffmpeg >&2\nexit 1\n')
    path = tmp_path / "x.gif"
    with pytest.raises(RuntimeError, match="ffmpeg failed: .*boom-from-ffmpeg"):
        gallery.write_gif([np.zeros((8, 8, 3), np.uint8)], str(path))
    assert not (tmp_path / "x.gif.tmp.gif").exists()
    assert not path.exists()


def test_write_gif_timeout_removes_tmp(tmp_path, monkeypatch):
    _fake_ffmpeg(tmp_path, monkeypatch, 'for last; do :; done\necho partial > "$last"\nexec sleep 30\n')
    monkeypatch.setattr(gallery, "FFMPEG_TIMEOUT", 1)
    with pytest.raises(RuntimeError, match="ffmpeg timed out"):
        gallery.write_gif([np.zeros((8, 8, 3), np.uint8)], str(tmp_path / "x.gif"))
    assert not (tmp_path / "x.gif.tmp.gif").exists()


def test_write_gif_without_images(tmp_path):
    with pytest.raises(ValueError, match="no images to write"):
        gallery.write_gif([], str(tmp_path / "x.gif"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")
def test_write_gif(tmp_path):
    images = [gallery.render(np.random.default_rng(i).uniform(-1, 1, (50, 3)), size=32) for i in range(3)]
    path = tmp_path / "x.gif"
    gallery.write_gif(images, str(path), fps=10)
    assert path.read_bytes()[:6] == b"GIF89a"
    assert not (tmp_path / "x.gif.tmp.gif").exists()


def test_write_gif_without_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(gallery.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        gallery.write_gif([np.zeros((8, 8, 3), np.uint8)], str(tmp_path / "x.gif"))


from h4nb_viz import __main__ as cli


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")
def test_make_gallery_writes_three_gifs(tmp_path):
    paths = gallery.make_gallery(str(tmp_path), frames=3, size=48, fps=10)
    assert [p.rsplit("/", 1)[-1] for p in paths] == list(gallery.GIFS)
    for p in paths:
        with open(p, "rb") as f:
            assert f.read(6) == b"GIF89a"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")
def test_cli_gallery(tmp_path, capsys):
    assert cli.main(["gallery", str(tmp_path / "media"), "--frames", "3", "--size", "48"]) == 0
    for name in gallery.GIFS:
        assert (tmp_path / "media" / name).exists()
    assert "3 GIF files" in capsys.readouterr().out
