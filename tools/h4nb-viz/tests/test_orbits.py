import math

import numpy as np
import pytest

from h4nb_viz.orbits import e_inc


def _pair(r, v):
    """Central body at index 0 (at rest, off-origin); particle at index 1."""
    pos = np.array([[5.0, -3.0, 2.0], np.add([5.0, -3.0, 2.0], r)])
    vel = np.array([[0.0, 1.0, 0.0], np.add([0.0, 1.0, 0.0], v)])
    return pos, vel


def test_circular_orbit_has_zero_eccentricity():
    pos, vel = _pair([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])  # v = sqrt(mu / r)
    e, inc = e_inc(pos, vel)
    assert e[1] == pytest.approx(0.0, abs=1e-12)
    assert inc[1] == pytest.approx(0.0, abs=1e-12)


def test_eccentric_orbit_at_pericentre_has_e_half():
    # a = 1, e = 0.5: r_p = a(1 - e) = 0.5, v_p = sqrt(mu (1 + e) / r_p) = sqrt(3).
    pos, vel = _pair([0.5, 0.0, 0.0], [0.0, math.sqrt(3.0), 0.0])
    e, _ = e_inc(pos, vel)
    assert e[1] == pytest.approx(0.5, abs=1e-6)


def test_inclined_orbit_gives_its_inclination():
    # The e = 0.5 orbit, tilted 30 degrees about the x axis.
    tilt = math.radians(30.0)
    r = [0.5, 0.0, 0.0]
    v = [0.0, math.sqrt(3.0) * math.cos(tilt), math.sqrt(3.0) * math.sin(tilt)]
    pos, vel = _pair(r, v)
    e, inc = e_inc(pos, vel)
    assert inc[1] == pytest.approx(math.radians(30.0), abs=1e-6)
    assert e[1] == pytest.approx(0.5, abs=1e-6)


def test_retrograde_orbit_gives_inclination_above_90_degrees():
    pos, vel = _pair([1.0, 0.0, 0.0], [0.0, -1.0, 0.0])  # Angular momentum points to -z.
    _, inc = e_inc(pos, vel)
    assert inc[1] == pytest.approx(math.pi, abs=1e-12)


def test_unbound_particle_keeps_e_above_one():
    # r = 1, v = 2 (v^2 = 4 > 2 mu / r): e = 3, not clamped.
    pos, vel = _pair([1.0, 0.0, 0.0], [0.0, 2.0, 0.0])
    e, _ = e_inc(pos, vel)
    assert e[1] == pytest.approx(3.0, abs=1e-12)
    assert e[1] >= 1.0


def test_central_body_entry_is_nan():
    pos, vel = _pair([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    e, inc = e_inc(pos, vel)
    assert np.isnan(e[0]) and np.isnan(inc[0])


def test_output_has_one_value_per_particle():
    pos, vel = _pair([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    e, inc = e_inc(pos, vel)
    assert e.shape == inc.shape == (2,)
