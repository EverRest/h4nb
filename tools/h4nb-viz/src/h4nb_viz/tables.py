"""Read the diagnostic tables of a run as numpy columns (specs/001 file-formats.md section 3).

A table is read from `<name>.dat`. When it is missing, `<name>.dat.tmp` is read instead, because a
running run writes only the .tmp files. A truncated last line is ignored.
"""
from __future__ import annotations

import os
from typing import Dict, Optional

import numpy as np

from .readers import parse_header, parse_row

TABLE_NAMES = ("energy.dat", "momentum.dat", "timesteps.dat", "performance.dat", "energy_periods.dat")

# Series name -> (table file, column). The Prometheus names are in specs/003 contracts/http-api.md.
# The series names with no file column (eta_seconds, progress_ratio) are not listed here.
SERIES_COLUMNS = {
    "sim_time": ("energy.dat", "time"),
    "energy_rel_err": ("energy.dat", "rel_err"),
    "dissipated_work": ("energy.dat", "W_diss"),
    "momentum_rel_change": ("momentum.dat", "dP_rel"),
    "angular_momentum_rel_change": ("momentum.dat", "dL_rel"),
    "dt_min": ("timesteps.dat", "dt_min"),
    "dt_mean": ("timesteps.dat", "dt_mean"),
    "dt_max": ("timesteps.dat", "dt_max"),
    "r_min": ("timesteps.dat", "r_min"),
    "pairs_per_second": ("performance.dat", "pairs_per_s"),
    "active_per_block_step": ("timesteps.dat", "mean_active_per_block_step"),
    "period_max_rel_err": ("energy_periods.dat", "max_rel_err"),
    "period_complete": ("energy_periods.dat", "complete"),
}


def table_path(run_dir: str, name: str) -> Optional[str]:
    """Return the path of the table: the .dat file, else the .dat.tmp file, else None."""
    for candidate in (name, name + ".tmp"):
        path = os.path.join(run_dir, candidate)
        if os.path.isfile(path):
            return path
    return None


def parse_table(text: str) -> Dict[str, np.ndarray]:
    """Return the columns of a table text, keyed by the header names. Rows with too few fields are skipped."""
    # The last piece is an empty string, or a line that the writer did not finish. Drop it.
    lines = text.split("\n")[:-1]
    header = next((line for line in lines if line.startswith("#")), None)
    if header is None:
        return {}
    columns = parse_header(header)
    rows = []
    for line in lines:
        if not line or line.startswith("#"):
            continue
        row = parse_row(line, columns)
        if row is not None:
            rows.append(row)
    return {c: np.array([r[c] for r in rows], dtype=float) for c in columns}


def read_table(run_dir: str, name: str) -> Optional[Dict[str, np.ndarray]]:
    """Return the columns of a table, or None when neither the .dat nor the .dat.tmp file exists."""
    path = table_path(run_dir, name)
    if path is None:
        return None
    with open(path, "rb") as f:
        text = f.read().decode("utf-8", "replace")
    return parse_table(text)


def read_series(run_dir: str, name: str) -> Optional[dict]:
    """Return {"x", "x_name", "y", "metric"} for a series name, or None when the table or column is missing.
    x is the period number for period_max_rel_err, else the simulation time."""
    file, column = SERIES_COLUMNS[name]
    table = read_table(run_dir, file)
    x_name = "period" if name in ("period_max_rel_err", "period_complete") else "time"
    if table is None or column not in table or x_name not in table:
        return None
    return {"x": table[x_name], "x_name": x_name, "y": table[column], "metric": "%s:%s" % (file, column)}
