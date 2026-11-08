"""Prometheus client of h4nb-viz (specs/003 T021 and T024). Uses the fake Prometheus of conftest.py."""
import os
import re
import threading
from http.server import ThreadingHTTPServer

import pytest

from h4nb_viz.prometheus import NAMES, Prometheus
from h4nb_viz.server import App, make_server

HERE = os.path.dirname(os.path.abspath(__file__))
RESEARCH_R6 = os.path.join(HERE, "..", "..", "..", "specs", "003-run-visualization", "research.md")
METRICS_002 = os.path.join(HERE, "..", "..", "..", "specs", "002-run-metrics", "contracts", "metrics.md")
START = "2026-11-08T10:00:00Z"
START_EPOCH = 1700000000 - 60  # Before the first sample of the fake data.
END_EPOCH = 1700000100


def r6_metric_names():
    """The metric names of the table in research.md section R6."""
    with open(RESEARCH_R6, encoding="utf-8") as f:
        section = f.read().split("## R6", 1)[1].split("\n## ", 1)[0]
    return set(re.findall(r"^\| `[^`]+` \| `(h4nb_\w+)`", section, re.M))


def test_names_match_002_contract():
    names = r6_metric_names()
    assert len(names) > 20  # The table was found.
    with open(METRICS_002, encoding="utf-8") as f:
        contract = set(re.findall(r"`(h4nb_\w+)`", f.read()))
    assert sorted(names - contract) == []  # Full names. Counters keep `_total`.
    assert set(NAMES.values()) <= names  # The client uses only names of the table.


def test_query_range_joins_sim_time(fake_prometheus):
    client = Prometheus(fake_prometheus.url)
    got = client.series("eta/run1", ["energy_rel_err"], START_EPOCH, END_EPOCH)
    series = got["energy_rel_err"]
    assert series["metric"] == "h4nb_energy_rel_err"
    assert series["x"] == [0.0, 0.25, 0.5, 1.0]  # The x values come from h4nb_sim_time.
    assert series["y"] == [1e-9, 2e-9, 3e-9, 4e-9]  # The sample at +60 s has no sim_time. It is dropped.


def test_selector_has_full_run_label_and_drops_backfill(fake_prometheus):
    client = Prometheus(fake_prometheus.url)
    client.series("eta/run1", ["energy_rel_err"], START_EPOCH, END_EPOCH)
    queries = {r["query"][0] for r in fake_prometheus.requests}
    assert queries == {'h4nb_energy_rel_err{run="eta/run1",origin!="backfill"}',
                       'h4nb_sim_time{run="eta/run1",origin!="backfill"}'}


def test_step_is_at_least_15_seconds(fake_prometheus):
    client = Prometheus(fake_prometheus.url)
    client.series("eta/run1", ["energy_rel_err"], START_EPOCH, END_EPOCH)
    assert all(int(r["step"][0]) >= 15 for r in fake_prometheus.requests)


def test_run_labels_match_start_utc(fake_prometheus):
    client = Prometheus(fake_prometheus.url)
    assert client.run_labels() == {START: "eta/run1", "2026-11-08T11:00:00Z": "scan/run1"}
    assert "origin!=\"backfill\"" in fake_prometheus.requests[-1]["query"][0]


def test_backfilled_run_info_is_dropped(fake_prometheus):
    fake_prometheus.info_file = "prom_run_info_backfill.json"  # The fake ignores the matcher on purpose.
    client = Prometheus(fake_prometheus.url)
    assert client.run_labels() == {}


def test_ready_answer_is_kept_for_15_seconds(fake_prometheus):
    now = [0.0]
    client = Prometheus(fake_prometheus.url, clock=lambda: now[0])
    assert client.ok() is True
    fake_prometheus.stop()
    now[0] = 10.0
    assert client.ok() is True  # Still the kept answer.
    now[0] = 16.0
    assert client.ok() is False


def test_fallback_to_files_when_prometheus_is_down(fake_root, fake_prometheus):
    url = fake_prometheus.url
    fake_prometheus.stop()
    httpd = make_server(fake_root, port=0, export_dir=None, web_dir=fake_root, prometheus=url)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        app = httpd.app
        assert app.run_list(0.0)[0]["in_prometheus"] is False
        body = app.series("eta~run1", {"names": ["energy_rel_err"], "source": ["auto"]})
        assert body["source"] == "files"
        assert len(body["series"]["energy_rel_err"]["y"]) == 4
    finally:
        httpd.shutdown()
        httpd.server_close()
