"""Short GIF previews for the README.

The motion is the exact Kepler motion of test particles around one central mass.
It is not an h4nb run. No GPU is needed.
"""
from __future__ import annotations

import csv
import io
from importlib import resources
from typing import List, Optional

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
