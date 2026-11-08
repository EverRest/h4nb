"""Write a fake run directory. Use it to test h4nb-viz without a GPU.

The run has one central body (m = 1, id 0) and test particles on Kepler orbits (G = 1).
The snapshots follow the exact Kepler motion of each particle. The state values in the
tables (K, U, momentum, angular momentum, r_min) are computed from the snapshots. The
error values (energy and momentum relative errors) are invented. They follow a random walk
of the size of a real run, not a physical error. The files have the formats of
specs/001-hermite-nbody-lib/contracts/file-formats.md.
"""
from __future__ import annotations

import math
import os
import time
from typing import List, Tuple

import numpy as np

from .readers import SNAP_HEADER, SNAP_MAGIC

PARTICLE_MASS = 1e-6
PERIOD = 2 * math.pi  # Kepler period of a = 1 with mu = 1.
TWO_PI = 2 * math.pi


def kepler_state(a: np.ndarray, e: np.ndarray, inc: np.ndarray, node: np.ndarray, peri: np.ndarray,
                 m0: np.ndarray, t: float) -> Tuple[np.ndarray, np.ndarray]:
    """Return positions and velocities (each shape (k, 3)) at time t. The orbits use mu = 1."""
    mean_anomaly = np.mod(m0 + a ** -1.5 * t, TWO_PI)
    ecc = mean_anomaly + e * np.sin(mean_anomaly)
    for _ in range(30):  # Newton iteration for Kepler's equation. Converges fast for small e.
        ecc = ecc - (ecc - e * np.sin(ecc) - mean_anomaly) / (1 - e * np.cos(ecc))
    r = a * (1 - e * np.cos(ecc))
    x_p = a * (np.cos(ecc) - e)
    y_p = a * np.sqrt(1 - e * e) * np.sin(ecc)
    vx_p = -np.sqrt(a) * np.sin(ecc) / r
    vy_p = np.sqrt(a) * np.sqrt(1 - e * e) * np.cos(ecc) / r
    c_o, s_o = np.cos(node), np.sin(node)
    c_w, s_w = np.cos(peri), np.sin(peri)
    c_i, s_i = np.cos(inc), np.sin(inc)
    # Perifocal to inertial frame (rotation by node, inc and peri).
    p_vec = np.stack([c_o * c_w - s_o * s_w * c_i, s_o * c_w + c_o * s_w * c_i, s_w * s_i], axis=1)
    q_vec = np.stack([-c_o * s_w - s_o * c_w * c_i, -s_o * s_w + c_o * c_w * c_i, c_w * s_i], axis=1)
    pos = x_p[:, None] * p_vec + y_p[:, None] * q_vec
    vel = vx_p[:, None] * p_vec + vy_p[:, None] * q_vec
    return pos, vel


def _write_snapshot(path: str, t: float, ids: np.ndarray, mass: np.ndarray, pos: np.ndarray,
                    vel: np.ndarray) -> None:
    """Write a v1 snapshot. Write a .tmp file first, then rename it (as h4nb_run does)."""
    n = len(ids)
    with open(path + ".tmp", "wb") as f:
        f.write(SNAP_HEADER.pack(SNAP_MAGIC, 1, 0, n, t))
        f.write(np.ascontiguousarray(ids, dtype="<i8").tobytes())
        f.write(np.ascontiguousarray(mass, dtype="<f8").tobytes())
        for arr in (pos[:, 0], pos[:, 1], pos[:, 2], vel[:, 0], vel[:, 1], vel[:, 2]):
            f.write(np.ascontiguousarray(arr, dtype="<f8").tobytes())
    os.replace(path + ".tmp", path)


def _write_table(path: str, header: str, rows: List[str]) -> None:
    with open(path, "w") as f:
        f.write("# " + header + "\n")
        f.write("".join(row + "\n" for row in rows))


def write_fake_run(out_dir: str, n: int = 20000, snaps: int = 60, t_end: float = 6.3125, seed: int = 1) -> None:
    """Write one fake run into out_dir. There are `snaps` numbered snapshots, then snap_final.snap at t_end."""
    if n < 2:
        raise ValueError("n must be at least 2 (the central body and one particle)")
    if snaps < 1:
        raise ValueError("snaps must be at least 1")
    os.makedirs(out_dir, exist_ok=True)
    rng = np.random.default_rng(seed)
    k = n - 1
    a = rng.uniform(0.5, 2.5, k)
    e = rng.uniform(0.0, 0.05, k)
    inc = rng.uniform(0.0, 0.02, k)
    node, peri, m0 = (rng.uniform(0.0, TWO_PI, k) for _ in range(3))
    ids = np.arange(n, dtype=np.int64)
    mass = np.full(n, PARTICLE_MASS)
    mass[0] = 1.0
    diag = t_end / snaps
    times = [i * diag for i in range(snaps)] + [t_end]
    names = ["snap_%06d.snap" % i for i in range(snaps)] + ["snap_final.snap"]

    states = []
    for t in times:
        pos_k, vel_k = kepler_state(a, e, inc, node, peri, m0, t)
        states.append((np.vstack([np.zeros((1, 3)), pos_k]), np.vstack([np.zeros((1, 3)), vel_k])))
    for name, t, (pos, vel) in zip(names, times, states):
        _write_snapshot(os.path.join(out_dir, name), t, ids, mass, pos, vel)

    _write_tables(out_dir, times, states, mass, n, diag, t_end, rng)
    _write_run_record(out_dir, n, t_end, diag)


def _write_tables(out_dir: str, times: List[float], states, mass: np.ndarray, n: int, diag: float, t_end: float,
                  rng: np.random.Generator) -> None:
    rows = len(times)
    energy, momentum, timesteps, performance = [], [], [], []
    walk_e = np.abs(np.cumsum(np.r_[0.0, rng.normal(0.0, 1e-11, rows - 1)]))  # Invented energy error.
    walk_p = np.abs(np.cumsum(np.r_[0.0, rng.normal(0.0, 1e-14, rows - 1)]))  # Invented momentum error.
    walk_l = np.abs(np.cumsum(np.r_[0.0, rng.normal(0.0, 1e-14, rows - 1)]))
    max_e = np.maximum.accumulate(walk_e)
    mean_e = np.cumsum(walk_e) / np.arange(1, rows + 1)
    for i, (t, (pos, vel)) in enumerate(zip(times, states)):
        r = np.linalg.norm(pos[1:], axis=1)
        v2 = np.sum(vel * vel, axis=1)
        kin = 0.5 * np.sum(mass * v2)
        pot = -np.sum(mass[1:] / r)
        energy.append("%.17g %.17g %.17g %.17g %.6e %.6e %.6e %.17g" % (
            t, kin, pot, kin + pot, walk_e[i], max_e[i], mean_e[i], 0.0))
        p = np.sum(mass[:, None] * vel, axis=0)
        lvec = np.sum(mass[:, None] * np.cross(pos, vel), axis=0)
        momentum.append("%.17g %.17g %.17g %.17g %.17g %.17g %.17g %.6e %.6e" % (
            t, p[0], p[1], p[2], lvec[0], lvec[1], lvec[2], walk_p[i], walk_l[i]))
        dt_max = diag / 4
        dt_min = dt_max * 2.0 ** -int(rng.integers(4, 10))
        active = n * 0.02 * (1 + 0.2 * rng.random())
        timesteps.append("%.17g %.6e %.6e %.6e %.3f %.6e" % (
            t, dt_min, dt_max, (dt_min + dt_max) / 2, active, float(r.min())))
        wall = 0.0 if i == 0 else 2.0 * (1 + 0.1 * rng.random())
        steps = int(round(diag / dt_min))
        pairs = active * n / wall if wall > 0 else 0.0
        performance.append("%.17g %.6f %d %d %.6e" % (t, wall, steps, int(active), pairs))
    _write_table(os.path.join(out_dir, "energy.dat"), "time K U E rel_err max_rel_err mean_rel_err W_diss", energy)
    _write_table(os.path.join(out_dir, "momentum.dat"), "time Px Py Pz Lx Ly Lz dP_rel dL_rel", momentum)
    _write_table(os.path.join(out_dir, "timesteps.dat"),
                 "time dt_min dt_max dt_mean mean_active_per_block_step r_min", timesteps)
    _write_table(os.path.join(out_dir, "performance.dat"), "time wall_s block_steps active pairs_per_s", performance)
    _write_periods(os.path.join(out_dir, "energy_periods.dat"), times, walk_e, t_end)


def _write_periods(path: str, times: List[float], errors: np.ndarray, t_end: float) -> None:
    """One row for each reference period. The row uses the diag points with time in ((p-1)T, pT]."""
    lines = []
    for p in range(1, int(math.ceil(t_end / PERIOD - 1e-12)) + 1):
        lo, hi = (p - 1) * PERIOD, p * PERIOD
        sel = [errors[i] for i, t in enumerate(times) if lo < t <= hi]
        mx = max(sel) if sel else float("nan")
        mean = sum(sel) / len(sel) if sel else float("nan")
        complete = 1 if t_end >= hi else 0
        lines.append("%d %.17g %.17g %.6e %.6e %d" % (p, lo, hi, mx, mean, complete))
    _write_table(path, "period t_start t_end max_rel_err mean_rel_err complete", lines)


def _write_run_record(out_dir: str, n: int, t_end: float, diag: float) -> None:
    start = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    config = [
        ("n", str(n), "cli"), ("t_end", repr(t_end), "cli"), ("G", "1", "default"), ("central_id", "0", "default"),
        ("period", repr(PERIOD), "default"), ("eps", "0.01", "default"), ("eta", "0.0005", "default"),
        ("diag", repr(diag), "default"), ("snap", repr(diag), "default"), ("energy_norm", "e0", "default"),
    ]
    with open(os.path.join(out_dir, "config.used"), "w") as f:
        f.write("# h4nb_viz fake run  %s\n" % start)
        for key, value, source in config:
            f.write("%-22s # %s\n" % ("%s=%s" % (key, value), source))
    with open(os.path.join(out_dir, "run_info.txt"), "w") as f:
        f.write("tool: h4nb_viz fake\nh4nb_commit: fake\nbuild_type: none\ncuda_architectures: none\n"
                "mpi: off\ndevice_0: id=0 name=fake cc=0.0 sm_count=0\nranks: 1\nhost: fake\n"
                "start_utc: %s\ncommand: h4nb-viz fake\n" % start)
