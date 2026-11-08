import os

import pytest

from h4nb_viz.fake import write_fake_run


@pytest.fixture
def small_run(tmp_path):
    """A fake run of 200 particles with 3 numbered snapshots and t_end = 1.0. Return its directory."""
    run_dir = str(tmp_path / "run")
    write_fake_run(run_dir, n=200, snaps=3, t_end=1.0, seed=7)
    return run_dir


@pytest.fixture
def fake_root(tmp_path):
    """A root with two runs: `eta/run1` (nested, so its name has `~`) and `flat`."""
    root = str(tmp_path / "root")
    write_fake_run(os.path.join(root, "eta", "run1"), n=200, snaps=3, t_end=1.0, seed=3)
    write_fake_run(os.path.join(root, "flat"), n=100, snaps=2, t_end=0.5, seed=4)
    return root
