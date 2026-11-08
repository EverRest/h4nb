import time

from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from helpers import make_run, snapshot_tree
from h4nb_metrics.exporter import make_registry
from h4nb_metrics.metrics import METRICS


def families(text):
    return {f.name: f for f in text_string_to_metric_families(text)}


def test_exposes_contract_metrics(tmp_path):
    make_run(tmp_path / "r1")
    make_run(tmp_path / "r2", seed=2)
    text = generate_latest(make_registry([str(tmp_path)], rescan=0)).decode()
    fams = families(text)
    exposed = {n for n in METRICS if n in fams}
    # Not exposed for a finished run: none. h4nb_eta_seconds is 0.
    assert exposed == set(METRICS)
    runs = {s.labels["run"] for s in fams["h4nb_energy_rel_err"].samples}
    assert runs == {"r1", "r2"}
    assert fams["h4nb_exporter_runs"].samples[0].value == 2


def test_exporter_only_reads(tmp_path):
    make_run(tmp_path / "r1")
    make_run(tmp_path / "r2", hang_at=0.5)
    before = snapshot_tree(tmp_path)
    reg = make_registry([str(tmp_path)], rescan=0)
    for _ in range(3):
        generate_latest(reg)
    assert snapshot_tree(tmp_path) == before


def test_scrape_time_20_runs(tmp_path):
    for i in range(20):
        make_run(tmp_path / ("r%02d" % i), t_end=4.0, seed=i)
    reg = make_registry([str(tmp_path)], rescan=10)
    generate_latest(reg)  # The first scrape reads the whole files.
    t0 = time.perf_counter()
    for _ in range(5):
        generate_latest(reg)
    assert (time.perf_counter() - t0) / 5 < 0.2  # SC-003
