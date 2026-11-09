import math

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
