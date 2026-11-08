"""Osculating two-body elements e and inc relative to the central body (research.md R7)."""
from __future__ import annotations

import numpy as np


def e_inc(pos: np.ndarray, vel: np.ndarray, mu: float = 1.0):
    """Return (e, inc) arrays with one value per particle.

    pos and vel have shape (n, 3). Particle 0 is the central body; its entries are NaN.
    e is not clamped: a value of e >= 1 means the particle is unbound.
    """
    r = pos[1:] - pos[0]
    v = vel[1:] - vel[0]
    rn = np.linalg.norm(r, axis=1)
    h = np.cross(r, v)  # Specific angular momentum.
    e_vec = np.cross(v, h) / mu - r / rn[:, None]
    e = np.full(len(pos), np.nan)
    inc = np.full(len(pos), np.nan)
    e[1:] = np.linalg.norm(e_vec, axis=1)
    inc[1:] = np.arctan2(np.hypot(h[:, 0], h[:, 1]), h[:, 2])
    return e, inc
