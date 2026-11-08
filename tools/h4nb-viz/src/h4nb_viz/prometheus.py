"""Prometheus client of h4nb-viz (specs/003 research.md R6, contracts/http-api.md).

It uses urllib only. It reads the metrics that specs/002 writes. Backfilled samples (origin="backfill")
never reach the page. Each series is joined with h4nb_sim_time, so the x axis is simulation time.
"""
from __future__ import annotations

import calendar
import http.client
import json
import math
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional

READY_SECONDS = 15.0  # The answer of the ready check is kept this long.
MAX_STEPS = 2000  # The query range has at most this many steps (R6).
MIN_STEP = 15  # Seconds.
RUN_INFO = "h4nb_run_info"

# Series name of the page -> Prometheus metric (R6 table). period_max_rel_err is not here: its x axis
# is the period, not the time, so the server reads it from the files.
NAMES = {
    "sim_time": "h4nb_sim_time",
    "energy_rel_err": "h4nb_energy_rel_err",
    "dissipated_work": "h4nb_dissipated_work",
    "momentum_rel_change": "h4nb_momentum_rel_change",
    "angular_momentum_rel_change": "h4nb_angular_momentum_rel_change",
    "dt_min": "h4nb_dt_min",
    "dt_mean": "h4nb_dt_mean",
    "dt_max": "h4nb_dt_max",
    "r_min": "h4nb_r_min",
    "pairs_per_second": "h4nb_pairs_per_second",
    "active_per_block_step": "h4nb_active_per_block_step",
    "progress_ratio": "h4nb_progress_ratio",
}


class PromError(Exception):
    """Prometheus is not reachable or it answered with an error."""


def query_step(start: float, end: float) -> int:
    """The step of query_range: 15 s, or the range in 2000 steps when that is longer."""
    return int(max(MIN_STEP, math.ceil((end - start) / MAX_STEPS)))


def utc_epoch(text: Optional[str]) -> Optional[float]:
    """Unix time of a start_utc value such as 2026-11-08T10:00:00Z. None when it does not parse."""
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return None


def selector(metric: str, run_label: str) -> str:
    """The PromQL selector of one run. The label is the full run label of specs/002."""
    value = run_label.replace("\\", "\\\\").replace('"', '\\"')
    value = value.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return '%s{run="%s",origin!="backfill"}' % (metric, value)


class Prometheus:
    def __init__(self, url: str, clock: Callable[[], float] = time.monotonic, timeout: float = 5.0):
        self.url = url.rstrip("/")
        self._clock = clock
        self._timeout = timeout
        self._ready: Optional[tuple] = None  # (answer, clock time) of the last ready check.

    def ready(self) -> bool:
        """True when GET /-/ready answers 200 within 1 s."""
        try:
            with urllib.request.urlopen(self.url + "/-/ready", timeout=1.0) as r:
                return r.status == 200
        except (OSError, http.client.HTTPException):
            return False

    def ok(self) -> bool:
        """The ready check. The answer is kept for READY_SECONDS."""
        now = self._clock()
        if self._ready is None or now - self._ready[1] >= READY_SECONDS:
            self._ready = (self.ready(), now)
        return self._ready[0]

    def _api(self, path: str, params: Dict[str, object]) -> List[dict]:
        """Call the HTTP API and return data.result. Raise PromError on any failure."""
        url = "%s%s?%s" % (self.url, path, urllib.parse.urlencode(params))
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as r:
                body = json.loads(r.read())
        except (OSError, ValueError, http.client.HTTPException) as err:
            raise PromError(str(err))
        if not isinstance(body, dict) or body.get("status") != "success":
            raise PromError(body.get("error", "query failed") if isinstance(body, dict) else "bad answer")
        try:
            result = body["data"]["result"]
        except (KeyError, TypeError) as err:
            raise PromError("bad answer: %s" % err)
        if not isinstance(result, list):
            raise PromError("bad answer: result is not a list")
        return result

    def run_labels(self) -> Dict[str, str]:
        """Return {start_utc: run label} for the runs that have an h4nb_run_info series. A start_utc that two
        runs share is left out: the match would pick the wrong run."""
        result = self._api("/api/v1/query", {"query": '%s{origin!="backfill"}' % RUN_INFO})
        labels: Dict[str, str] = {}
        shared = set()
        for item in result:
            meta = item.get("metric", {})
            if meta.get("origin") == "backfill" or "start_utc" not in meta or "run" not in meta:
                continue  # The matcher is in the query. This check also drops backfill on a bad answer.
            start = meta["start_utc"]
            if start in labels and labels[start] != meta["run"]:
                shared.add(start)
            labels.setdefault(start, meta["run"])
        for start in shared:
            del labels[start]
        return labels

    def _samples(self, metric: str, run_label: str, start: float, end: float, step: int) -> Dict[float, float]:
        """Return {time stamp: value} of one metric of one run."""
        params = {"query": selector(metric, run_label), "start": start, "end": end, "step": step}
        samples: Dict[float, float] = {}
        for item in self._api("/api/v1/query_range", params):
            if item.get("metric", {}).get("origin") == "backfill":
                continue
            for stamp, value in item.get("values", []):
                samples[float(stamp)] = float(value)
        return samples

    def series(self, run_label: str, names: List[str], start: float, end: float) -> Dict[str, dict]:
        """Return {name: {"x", "x_name", "y", "metric"}} for the page names in NAMES.
        x is h4nb_sim_time at the same time stamp. A point with no sim_time sample is dropped."""
        step = query_step(start, end)
        sim_time = self._samples(NAMES["sim_time"], run_label, start, end, step)
        out = {}
        for name in names:
            values = self._samples(NAMES[name], run_label, start, end, step)
            pairs = [(sim_time[t], v) for t, v in sorted(values.items()) if t in sim_time]
            out[name] = {"x": [x for x, _ in pairs], "x_name": "time", "y": [y for _, y in pairs],
                         "metric": NAMES[name]}
        return out
