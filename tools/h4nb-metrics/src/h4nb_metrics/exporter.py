"""Prometheus exporter: reads the runs at each scrape and exposes their values (spec FR-003 to FR-009, FR-013)."""
from __future__ import annotations

import threading
import time
from typing import List

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import CollectorRegistry

from .metrics import COUNTER, EXPORTER_METRICS, METRICS
from .runs import RunSet


def family(name: str, kind: str, help_text: str, labels: List[str]):
    cls = CounterMetricFamily if kind == COUNTER else GaugeMetricFamily
    return cls(name, help_text, labels=labels)


class RunCollector:
    def __init__(self, runset: RunSet, stale_min: float = 300.0):
        self.runset, self.stale_min = runset, stale_min
        self._lock = threading.Lock()
        self._scrape_s = 0.0

    def collect(self):
        with self._lock:
            t0 = time.perf_counter()
            self.runset.refresh()
            now = time.time()
            per_metric = {}
            for label, run in sorted(self.runset.runs.items()):
                try:
                    samples = run.samples(now, self.stale_min)
                except Exception:  # FR-013
                    self.runset.errors[label] += 1
                    continue
                for name, values in samples.items():
                    for extra, value in values:
                        per_metric.setdefault(name, []).append((dict(run=label, **extra), value))
            families = []
            for name, (kind, help_text) in METRICS.items():
                values = per_metric.get(name)
                if not values:
                    continue
                keys = list(values[0][0].keys())
                fam = family(name, kind, help_text, keys)
                for labels, value in values:
                    fam.add_metric([labels.get(k, "") for k in keys], value)
                families.append(fam)
            runs = GaugeMetricFamily("h4nb_exporter_runs", EXPORTER_METRICS["h4nb_exporter_runs"][1])
            runs.add_metric([], len(self.runset.runs))
            errs = CounterMetricFamily("h4nb_exporter_read_errors", EXPORTER_METRICS["h4nb_exporter_read_errors"][1],
                                       labels=["run"])
            for label, n in sorted(self.runset.errors.items()):
                errs.add_metric([label], n)
            scrape = GaugeMetricFamily("h4nb_exporter_scrape_seconds", EXPORTER_METRICS["h4nb_exporter_scrape_seconds"][1])
            scrape.add_metric([], self._scrape_s)
            self._scrape_s = time.perf_counter() - t0
        return families + [runs, errs, scrape]


def make_registry(paths: List[str], max_depth: int = 2, rescan: float = 10.0, stale_min: float = 300.0):
    registry = CollectorRegistry()
    registry.register(RunCollector(RunSet(paths, max_depth, rescan), stale_min))
    return registry
