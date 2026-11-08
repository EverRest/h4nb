import os

import pytest

from h4nb_viz.fake import write_fake_run
from h4nb_viz.tables import read_table

HEADERS = {
    "energy.dat": ["time", "K", "U", "E", "rel_err", "max_rel_err", "mean_rel_err", "W_diss"],
    "momentum.dat": ["time", "Px", "Py", "Pz", "Lx", "Ly", "Lz", "dP_rel", "dL_rel"],
    "timesteps.dat": ["time", "dt_min", "dt_max", "dt_mean", "mean_active_per_block_step", "r_min"],
    "performance.dat": ["time", "wall_s", "block_steps", "active", "pairs_per_s"],
    "energy_periods.dat": ["period", "t_start", "t_end", "max_rel_err", "mean_rel_err", "complete"],
}


def test_writes_all_files_with_contract_headers(tmp_path):
    out = str(tmp_path / "run")
    write_fake_run(out, n=40, snaps=2, t_end=1.0)
    for name in ("config.used", "run_info.txt"):
        assert os.path.isfile(os.path.join(out, name))
    for name, columns in HEADERS.items():
        table = read_table(out, name)
        assert list(table) == columns, name
        assert len(next(iter(table.values()))) > 0, name


def test_energy_table_rows_match_snapshots(tmp_path):
    out = str(tmp_path / "run")
    write_fake_run(out, n=40, snaps=2, t_end=1.0)
    energy = read_table(out, "energy.dat")
    assert len(energy["time"]) == 3  # Two numbered snapshots and the final one.
    assert energy["time"][-1] == 1.0
    assert (energy["rel_err"] < 1e-9).all()  # Random walk near 1e-10 (invented, see fake.py).


def test_rejects_bad_sizes(tmp_path):
    with pytest.raises(ValueError):
        write_fake_run(str(tmp_path / "a"), n=1)
    with pytest.raises(ValueError):
        write_fake_run(str(tmp_path / "b"), n=10, snaps=0)


def test_kepler_state_circular_orbit_keeps_radius_and_speed():
    import numpy as np

    from h4nb_viz.fake import kepler_state

    a = np.array([1.0, 2.0])
    zero = np.zeros(2)
    for t in (0.0, 0.7, 3.1):
        pos, vel = kepler_state(a, zero, zero, zero, zero, zero, t)
        assert np.allclose(np.linalg.norm(pos, axis=1), a)  # Circular: r = a.
        assert np.allclose(np.linalg.norm(vel, axis=1), 1 / np.sqrt(a))  # v = sqrt(mu / a).


def test_kepler_state_returns_to_start_after_one_period():
    import numpy as np

    from h4nb_viz.fake import PERIOD, kepler_state

    a = np.array([1.5])
    e = np.array([0.03])
    zero = np.zeros(1)
    p0, _ = kepler_state(a, e, zero, zero, zero, zero, 0.0)
    p1, _ = kepler_state(a, e, zero, zero, zero, zero, PERIOD * 1.5 ** 1.5)
    assert np.allclose(p0, p1, atol=1e-10)
