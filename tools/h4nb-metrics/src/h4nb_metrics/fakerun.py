"""Fake run generator (spec FR-012). It writes the files of h4nb_run in the formats of file-formats.md, one diag
line after the other, so that the exporter and the dashboards can be checked without a GPU.
The numbers are invented. They only have realistic sizes."""
from __future__ import annotations

import math
import os
import random
import struct
import time
from typing import Optional

from .readers import SNAP_HEADER, SNAP_MAGIC, TABLES

HEADERS = {
    "energy.dat": "# time K U E rel_err max_rel_err mean_rel_err W_diss\n",
    "momentum.dat": "# time Px Py Pz Lx Ly Lz dP_rel dL_rel  (changes divided by sum m|v| and sum m|r x v| of the initial state, TZ 7.3)\n",
    "timesteps.dat": "# time dt_min dt_max dt_mean mean_active_per_block_step r_min\n",
    "performance.dat": "# time wall_s block_steps active pairs_per_s\n",
}


def write_snapshot(path: str, n: int, t: float, rng: random.Random) -> None:
    cols = [[float(i) for i in range(n)]]
    with open(path + ".tmp", "wb") as f:
        f.write(SNAP_HEADER.pack(SNAP_MAGIC, 1, 0, n, t))
        f.write(struct.pack("<%dq" % n, *range(n)))
        f.write(struct.pack("<%dd" % n, *([1.0] + [1e-6] * (n - 1))))
        for _ in range(6):
            f.write(struct.pack("<%dd" % n, *[rng.gauss(0, 1) for _ in range(n)]))
    os.replace(path + ".tmp", path)
    del cols


def fake_run(out: str, n: int = 131072, t_end: float = 6.3125, diag: float = 0.0625, interval: float = 1.0,
             eta: float = 0.0005, eps: float = 0.01, fail_at: Optional[float] = None, hang_at: Optional[float] = None,
             instant: bool = False, start_utc: Optional[float] = None, seed: int = 1, snap_n: int = 256) -> int:
    """Writes one fake run into `out`. Returns the exit code that h4nb_run would give.
    instant: no sleep; wall_s is `interval` for each segment (use it for backfill tests).
    fail_at: stop at this simulation time and publish the .dat files (exit 3, state "stopped early").
    hang_at: stop writing at this time and keep the .dat.tmp files (state "stalled")."""
    rng = random.Random(seed)
    os.makedirs(out, exist_ok=True)
    start = time.time() if start_utc is None else start_utc
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start))
    period = 2 * math.pi
    keys = [("ic", "disk.snap", "cli"), ("n", str(n), "cli"), ("out", out, "cli"), ("t_end", repr(t_end), "cli"),
            ("period", repr(period), "file:configs/agn.cfg:5"), ("G", "1", "default"), ("eps", repr(eps), "preset:agn"),
            ("dissipation", "off", "default"), ("eta", repr(eta), "file:configs/agn.cfg:2"),
            ("dt_max", repr(diag / 4), "file:configs/agn.cfg:3"), ("max_level", "30", "default"),
            ("devices", "0,1", "cli"), ("tile", "128", "default"), ("blocks_per_sm", "4", "default"),
            ("diag", repr(diag), "file:configs/agn.cfg:4"), ("snap", repr(diag * 20), "cli"),
            ("energy_tol", "1e-08", "default"), ("energy_norm", "e0", "default"), ("perf", "1", "default"),
            ("preset", "agn", "file:configs/agn.cfg:1")]
    with open(os.path.join(out, "config.used"), "w") as f:
        f.write("# h4nb_run config.used  %s\n" % stamp)
        for k, v, src in keys:
            f.write("%-22s # %s\n" % ("%s=%s" % (k, v), src))
    with open(os.path.join(out, "run_info.txt"), "w") as f:
        f.write("tool: h4nb_run\nh4nb_commit: 49a2a76\nbuild_type: Release\ncuda_architectures: 89\n"
                "nvcc_version: 12.6\ncuda_runtime_version: 12.6\ncuda_driver_version: 12.8\nhost_compiler: GNU 13.2\n"
                "mpi: off\ndevice_0: id=0 name=NVIDIA GeForce RTX 4070 Ti cc=8.9 sm_count=60\n"
                "device_1: id=1 name=NVIDIA GeForce RTX 4070 Ti cc=8.9 sm_count=60\nranks: 1\nhost: fake-gpu\n"
                "start_utc: %s\ncommand: h4nb_run (fake) out=%s\n" % (stamp, out))
    write_snapshot(os.path.join(out, "snap_000000.snap"), snap_n, 0.0, rng)
    files = {name: open(os.path.join(out, name + ".tmp"), "w") for name in HEADERS}
    for name, f in files.items():
        f.write(HEADERS[name])
    E0, K0 = -0.25, 0.25
    max_err, err_sum, n_err = 0.0, 0.0, 0
    nseg = int(round(t_end / diag))

    def energy_line(t: float) -> float:
        nonlocal max_err, err_sum, n_err
        err = 0.0 if t == 0 else 2e-12 * (1 + 3 * t / period) * (1 + 0.4 * math.sin(5 * t)) * (1 + 0.1 * rng.random())
        max_err, err_sum, n_err = max(max_err, err), err_sum + err, n_err + 1
        E = E0 * (1 + err)
        files["energy.dat"].write("%.17g %.17g %.17g %.17g %.6e %.6e %.6e %.17g\n" % (
            t, K0, E - K0, E, err, max_err, err_sum / n_err, 0.0))
        files["momentum.dat"].write("%.17g %.17g %.17g %.17g %.17g %.17g %.17g %.6e %.6e\n" % (
            t, 1e-17, -2e-17, 0.0, 0.0, 0.0, 0.5, 1e-15 * (1 + t), 3e-15 * (1 + t)))
        return err

    def publish() -> None:
        for name in TABLES:
            tmp = os.path.join(out, name + ".tmp")
            if os.path.exists(tmp):
                os.replace(tmp, os.path.join(out, name))

    energy_line(0.0)
    for f in files.values():
        f.flush()
    period_rows = {}
    code = 0
    for k in range(1, nseg + 1):
        t = k * diag
        if hang_at is not None and t > hang_at:
            for f in files.values():
                f.close()
            return 0
        t0 = time.time()
        if not instant:
            time.sleep(interval)
        wall = interval if instant else time.time() - t0
        close = 1 + 30 * math.exp(-((t - 0.6 * t_end) ** 2) / (0.02 * t_end) ** 2)  # One close encounter.
        dt_min = diag / 4 / 2 ** (6 + int(math.log2(close)) + rng.randint(0, 1))
        active = max(64.0, n * 0.02 / close * (1 + 0.2 * rng.random()))
        steps = int(diag / 4 / dt_min)
        pairs = active * n / wall if wall > 0 else 0.0
        if fail_at is not None and t >= fail_at:
            files["energy.dat"].write("%.17g nan nan nan nan nan nan 0\n" % t)
            code = 3
            break
        err = energy_line(t)
        files["timesteps.dat"].write("%.17g %.6e %.6e %.6e %.3f %.6e\n" % (
            t, dt_min, diag / 4, diag / 64, active, 0.01 / close * (1 + 0.1 * rng.random())))
        files["performance.dat"].write("%.17g %.6f %d %d %.6e\n" % (t, wall, steps, int(active * steps), pairs * steps))
        p = int(math.ceil(t / period - 1e-12))
        r = period_rows.setdefault(p, [0.0, 0.0, 0])
        r[0], r[1], r[2] = max(r[0], err), r[1] + err, r[2] + 1
        for f in files.values():
            f.flush()
    with open(os.path.join(out, "energy_periods.dat.tmp"), "w") as f:
        f.write("# period t_start t_end max_rel_err mean_rel_err complete\n")
        t_reached = min(t_end, (k if code == 0 else k - 1) * diag)
        for p, (mx, s, c) in sorted(period_rows.items()):
            f.write("%d %.17g %.17g %.6e %.6e %d\n" % (p, (p - 1) * period, p * period, mx, s / c,
                                                       1 if t_reached >= p * period else 0))
    for f in files.values():
        f.close()
    if code == 0:
        write_snapshot(os.path.join(out, "snap_final.snap"), snap_n, t_end, rng)
    publish()
    return code
