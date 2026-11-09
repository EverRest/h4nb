"""Short GIF previews for the README.

The motion is the exact Kepler motion of test particles around one central mass.
It is not an h4nb run. No GPU is needed.
"""
from __future__ import annotations

import csv
import io
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
