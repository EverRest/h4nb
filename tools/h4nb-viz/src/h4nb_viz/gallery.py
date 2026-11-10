"""Short GIF previews for the README.

The motion is the exact Kepler motion of test particles around one central mass.
It is not an h4nb run. No GPU is needed.
"""
from __future__ import annotations

import csv
import io
import math
import os
import shutil
import subprocess
from importlib import resources
from typing import List, Optional

import numpy as np

from .fake import TWO_PI, kepler_state

FIELDS = ("a_arcsec", "e", "i_deg", "node_deg", "peri_deg", "tp_year", "p_year")


def load_s_stars(path: Optional[str] = None) -> List[dict]:
    """Read the S-star table. Lines that start with # are comments."""
    if path is None:
        text = resources.files("h4nb_viz").joinpath("data", "s_stars.csv").read_text()
    else:
        with open(path) as f:
            text = f.read()
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
    stars = []
    for row in csv.DictReader(io.StringIO("\n".join(lines))):
        star = {"name": row["name"].strip()}
        star.update({key: float(row[key]) for key in FIELDS})
        stars.append(star)
    return stars


def s_star_frames(stars: List[dict], start: float = 2000.0, end: float = 2032.0, frames: int = 120) -> List[np.ndarray]:
    """Sky-frame positions of the S-stars. Length unit: a of S2. Time unit: the S2 period is 2*pi.

    x and y are in the plane of the sky. z is along the line of sight."""
    ref = next((s for s in stars if s["name"] == "S2"), None)
    if ref is None:
        raise ValueError("The S-star table has no S2 row. S2 sets the length and time units.")
    period = np.array([s["p_year"] for s in stars])
    a = (period / ref["p_year"]) ** (2.0 / 3.0)  # a of S2 is 1. P sets the scale.
    e = np.array([s["e"] for s in stars])
    inc = np.radians([s["i_deg"] for s in stars])
    node = np.radians([s["node_deg"] for s in stars])
    peri = np.radians([s["peri_deg"] for s in stars])
    tp = np.array([s["tp_year"] for s in stars])
    m0 = TWO_PI * (start - tp) / period
    scale = TWO_PI / ref["p_year"]  # Years to model time.
    out = []
    for t in np.linspace(start, end, frames):
        pos, _ = kepler_state(a, e, inc, node, peri, m0, (t - start) * scale)
        out.append(pos)
    return out


def _random_orbits(rng: np.random.Generator, a: np.ndarray, e: np.ndarray, inc: np.ndarray, frames: int,
                   t_end: float) -> List[np.ndarray]:
    n = a.size
    node = rng.uniform(0.0, TWO_PI, n)
    peri = rng.uniform(0.0, TWO_PI, n)
    m0 = rng.uniform(0.0, TWO_PI, n)
    return [kepler_state(a, e, inc, node, peri, m0, t)[0] for t in np.linspace(0.0, t_end, frames)]


def agn_disk_frames(n: int = 20000, frames: int = 120, t_end: float = 20.0, seed: int = 1) -> List[np.ndarray]:
    """A thin gas disk around the central mass, with the semi-major axis a from 1 to 10 (the radius r is about 0.8 to 12). The inner part turns faster (shear)."""
    rng = np.random.default_rng(seed)
    a = rng.uniform(1.0, 10.0, n)
    e = np.minimum(np.abs(rng.normal(0.0, 0.02, n)), 0.2)
    inc = np.abs(rng.normal(0.0, 0.02, n))
    return _random_orbits(rng, a, e, inc, frames, t_end)


def cluster_frames(n: int = 8000, frames: int = 120, t_end: float = 40.0, seed: int = 2) -> List[np.ndarray]:
    """A round star cluster around the central mass: random orientations, thermal e, a from 1 to 10 (log scale)."""
    rng = np.random.default_rng(seed)
    a = 10.0 ** rng.uniform(0.0, 1.0, n)
    e = np.sqrt(rng.uniform(0.0, 0.95 ** 2, n))
    inc = np.arccos(rng.uniform(-1.0, 1.0, n))
    return _random_orbits(rng, a, e, inc, frames, t_end)


def _turn(pos: np.ndarray, azimuth: float, tilt: float) -> np.ndarray:
    ca, sa = math.cos(azimuth), math.sin(azimuth)
    x = ca * pos[:, 0] - sa * pos[:, 1]
    y = sa * pos[:, 0] + ca * pos[:, 1]
    z = pos[:, 2]
    ct, st = math.cos(tilt), math.sin(tilt)
    return np.column_stack([x, ct * y - st * z, st * y + ct * z])


def _glow(img: np.ndarray) -> np.ndarray:
    near = sum(np.roll(np.roll(img, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)) - img
    return img + 0.5 * near / 8.0


def _colors(v: np.ndarray) -> np.ndarray:
    """0..1 to a warm color: dark red, orange, yellow, white."""
    r = np.clip(1.6 * v, 0.0, 1.0)
    g = np.clip(1.6 * v - 0.4, 0.0, 1.0)
    b = np.clip(1.6 * v - 1.0, 0.0, 1.0)
    return np.stack([r, g, b], axis=-1)


def render(pos: np.ndarray, size: int = 480, extent: float = 1.0, azimuth: float = 0.0, tilt: float = 0.0,
           center: bool = True) -> np.ndarray:
    """Project the points (shape (k, 3)) onto an RGB image of shape (size, size, 3), dtype uint8."""
    img = np.zeros((size, size))
    if pos.shape[0] > 0:
        p = _turn(pos, azimuth, tilt)
        ix = np.rint((p[:, 0] / extent + 1.0) * 0.5 * (size - 1)).astype(int)
        iy = np.rint((1.0 - (p[:, 1] / extent + 1.0) * 0.5) * (size - 1)).astype(int)
        keep = (ix >= 0) & (ix < size) & (iy >= 0) & (iy < size)
        np.add.at(img, (iy[keep], ix[keep]), 1.0)
        img = _glow(img)
    if center:
        c = (size - 1) // 2
        img[max(c - 1, 0):c + 2, max(c - 1, 0):c + 2] = max(img.max(), 1.0)
    v = np.log1p(img)
    top = v.max()
    if top > 0:
        v = v / top
    return (_colors(v) * 255.0).astype(np.uint8)


def write_gif(images: List[np.ndarray], path: str, fps: int = 20) -> None:
    """Write the RGB images as a looping GIF with ffmpeg. The file appears only when it is complete."""
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise RuntimeError("ffmpeg is not on PATH")
    h, w, _ = images[0].shape
    tmp = path + ".tmp.gif"
    cmd = [exe, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (w, h),
           "-r", str(fps), "-i", "-",
           "-filter_complex", "[0:v]split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
           "-loop", "0", tmp]
    data = b"".join(np.ascontiguousarray(img, dtype=np.uint8).tobytes() for img in images)
    subprocess.run(cmd, input=data, check=True, timeout=300)
    os.replace(tmp, path)


GIFS = ("s-stars.gif", "agn-disk.gif", "star-cluster.gif")


def _extent(frames: List[np.ndarray], tilt: float) -> float:
    """Half width that holds 98 % of the points over all frames, plus a margin."""
    xy = np.concatenate([np.abs(_turn(f, 0.0, tilt)[:, :2]).max(axis=1) for f in frames])
    return float(np.percentile(xy, 98.0)) * 1.15


def make_gallery(out_dir: str, frames: int = 180, size: int = 480, fps: int = 15) -> List[str]:
    """Write the three GIFs of GIFS into out_dir. Return their paths."""
    os.makedirs(out_dir, exist_ok=True)
    tilt_disk = math.radians(60.0)
    tilt_cluster = math.radians(20.0)
    scenes = [
        # S-stars: fixed sky view (x and y on the sky), as in the published orbit plots.
        (s_star_frames(load_s_stars(), frames=frames), 0.0, lambda i: 0.0),
        # AGN disk: seen at 60 degrees, turning slowly.
        (agn_disk_frames(frames=frames), tilt_disk, lambda i: math.radians(30.0) * i / max(frames - 1, 1)),
        # Star cluster: one full turn.
        (cluster_frames(frames=frames), tilt_cluster, lambda i: TWO_PI * i / max(frames, 1)),
    ]
    paths = []
    for name, (scene, tilt, azimuth) in zip(GIFS, scenes):
        extent = _extent(scene, tilt)
        images = [render(pos, size=size, extent=extent, azimuth=azimuth(i), tilt=tilt) for i, pos in enumerate(scene)]
        path = os.path.join(out_dir, name)
        write_gif(images, path, fps=fps)
        paths.append(path)
    return paths
