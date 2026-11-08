"""The metric table of contracts/metrics.md section 0 equals the names of metrics.py (spec SC-005 style check)."""
import os
import re

from h4nb_metrics.metrics import COUNTER, EXPORTER_METRICS, METRICS

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT = os.path.join(HERE, "..", "..", "..", "specs", "002-run-metrics", "contracts", "metrics.md")


def table_names():
    text = open(CONTRACT, encoding="utf-8").read()
    section = text.split("## 0. Metric table")[1].split("## 1. Run status")[0]
    return set(re.findall(r"^\| `(h4nb_[a-z_]+)`", section, re.M))


def test_table_names_equal_prototype_names():
    expected = set()
    for name, (kind, _) in list(METRICS.items()) + list(EXPORTER_METRICS.items()):
        expected.add(name + "_total" if kind == COUNTER else name)
    assert table_names() == expected
