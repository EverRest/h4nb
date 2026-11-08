"""HTTP server of h4nb-viz (contracts/http-api.md). It listens on 127.0.0.1 only.

The server does no rendering. It slices the arrays of a snapshot and sends them as binary frames.
The page draws them. Errors are JSON objects: {"error": "<text>"}.
"""
from __future__ import annotations

import hmac
import http.cookies
import json
import mimetypes
from collections import Counter
import os
import re
import secrets
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from . import __version__, media
from .prometheus import NAMES, Prometheus, PromError, utc_epoch
from .runs import RESCAN_SECONDS, RunIndex, central_id_of, detail, newest_change, start_utc_of, summarize, t_end_of
from .snapshots import (FIELD_MASS, FIELD_POS, FIELD_VEL, Snapshot, SubsetCache, encode_frame, encode_ids,
                        list_frames)
from .tables import SERIES_COLUMNS, read_series


def cookie_name(port: int) -> str:
    """The name of the access cookie. It depends on the port, so two servers on one host do not share it."""
    return "h4nb_token_%d" % port


MAX_EXPORT_BYTES = 1 << 30  # One export file can be 1 GiB at most.
EXPORT_EXTENSIONS = (".webm", ".mp4", ".png", ".svg")
WEB_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web"))
DEFAULT_MAX_POINTS = 200000
FIELD_BITS = {"pos": FIELD_POS, "vel": FIELD_VEL, "mass": FIELD_MASS}
RUN_ROUTE = re.compile(r"/api/runs/([^/]+)")
IDS_ROUTE = re.compile(r"/api/runs/([^/]+)/ids")
FRAME_ROUTE = re.compile(r"/api/runs/([^/]+)/frames/(\d+)")
SERIES_ROUTE = re.compile(r"/api/runs/([^/]+)/series")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def json_list(values) -> List[Optional[float]]:
    """Return the values as a list of floats. NaN and Inf become None (JSON has no NaN)."""
    return [float(v) if np.isfinite(v) else None for v in values]


def progress_ratio(run_dir: str) -> Optional[dict]:
    """The series time / t_end of energy.dat. None when the run has no t_end or no energy table."""
    data = read_series(run_dir, "sim_time")
    t_end = t_end_of(run_dir)
    if data is None or not t_end:
        return None
    return {"x": data["x"], "x_name": "time", "y": data["y"] / t_end, "metric": "energy.dat:time / t_end"}


def save_export_path(export_dir: str, base: str) -> str:
    """Return a free path in the export directory. Add a number when the name is taken."""
    stem, ext = os.path.splitext(base)
    path, number = os.path.join(export_dir, base), 1
    while os.path.exists(path):
        path = os.path.join(export_dir, "%s-%d%s" % (stem, number, ext))
        number += 1
    return path


def save_export(export_dir: str, name: str, data: bytes) -> str:
    """Write one export file. Keep only the base name, and add a number when the name is taken."""
    base = os.path.basename(name.replace("\\", "/"))
    stem, ext = os.path.splitext(base)
    if not stem or ext.lower() not in EXPORT_EXTENSIONS:
        raise ApiError(400, "name must end with one of %s" % ", ".join(EXPORT_EXTENSIONS))
    os.makedirs(export_dir, exist_ok=True)
    path = save_export_path(export_dir, base)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path


def _int_param(query: Dict[str, List[str]], name: str, default: int) -> int:
    raw = query.get(name, [None])[0]
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(400, "%s must be an integer" % name)
    if value < 1:
        raise ApiError(400, "%s must be at least 1" % name)
    return value


def _fields(query: Dict[str, List[str]]) -> int:
    """The bit mask of frame-format.md. pos is always set."""
    bits = FIELD_POS
    for name in query.get("fields", [""])[0].split(","):
        name = name.strip()
        if not name or name == "pos":
            continue
        if name not in FIELD_BITS:
            raise ApiError(400, "unknown field %s" % name)
        bits |= FIELD_BITS[name]
    return bits


class App:
    """State of one server: the root directory, the run index, the subset cache and Prometheus."""

    def __init__(self, root: str, export_dir: Optional[str] = None, web_dir: str = WEB_DIR,
                 prometheus: Optional[str] = None, grafana_url: Optional[str] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.root = os.path.abspath(root)
        self.web_dir = os.path.abspath(web_dir)
        self.export_dir = export_dir or os.path.expanduser("~/h4nb-viz-exports")
        self.runs = RunIndex(self.root)
        self.subsets = SubsetCache()
        self.prom = Prometheus(prometheus, clock=clock) if prometheus else None
        self.grafana_url = grafana_url
        self._clock = clock
        self._labels: Dict[str, str] = {}  # {start_utc: run label}, read at each rescan.
        self._labels_at: Optional[float] = None

        # Every /api/ request must send this token. The page gets it from index.html (same origin only).
        self.token = secrets.token_urlsafe(32)
        # The link that the server prints works once. It is not the session secret, so it cannot
        # authorize API requests, and a copied link stops working after the first use.
        self.link_token = secrets.token_urlsafe(32)
        self._link_used = False
        self._link_lock = threading.Lock()

    def run_dir(self, name: str) -> str:
        path = self.runs.runs().get(name)
        if path is None:
            raise ApiError(404, "no run named %s" % name)
        return path

    def first_frame(self, name: str, run_dir: str) -> Tuple[Snapshot, List[Snapshot]]:
        frames = list_frames(run_dir)
        if not frames:
            raise ApiError(404, "run %s has no snapshot" % name)
        return frames[0], frames

    def status(self) -> dict:
        return {"version": __version__, "root": self.root,
                "prometheus": self.prom.url if self.prom else None,
                "prometheus_ok": bool(self.prom and self.prom.ok()),
                "ffmpeg": media.find_ffmpeg() is not None, "grafana_url": self.grafana_url}

    def prom_labels(self) -> Dict[str, str]:
        """{start_utc: run label} of Prometheus. One h4nb_run_info query runs per rescan."""
        if self.prom is None:
            return {}
        now = self._clock()
        if self._labels_at is None or now - self._labels_at >= RESCAN_SECONDS:
            self._labels_at = now
            try:
                self._labels = self.prom.run_labels()
            except PromError:
                self._labels = {}  # Prometheus is down. The runs are then not in Prometheus.
        return self._labels

    def matched_labels(self) -> Dict[str, str]:
        """{start_utc: run label} for the start values that exactly one local run has. A start value that two
        local runs share is left out: the match would give both runs the same Prometheus data."""
        labels = self.prom_labels()
        counts = Counter(start_utc_of(path) for path in self.runs.runs().values())
        return {start: label for start, label in labels.items() if counts[start] == 1}

    def run_list(self, now: float) -> List[dict]:
        found = [(newest_change(path), name, path) for name, path in self.runs.runs().items()]
        found.sort(key=lambda item: -item[0])
        labels = self.matched_labels()
        return [summarize(name, path, now, labels.get(start_utc_of(path))) for _, name, path in found]

    def series(self, name: str, query: Dict[str, List[str]]) -> dict:
        run_dir = self.run_dir(name)
        source = query.get("source", ["auto"])[0]
        if source not in ("auto", "files", "prometheus"):
            raise ApiError(400, "source must be auto, files or prometheus")
        names = [n for n in query.get("names", [""])[0].split(",") if n]
        if not names:
            raise ApiError(400, "names is required")
        if source == "files":
            return {"source": "files", "series": self.file_series(run_dir, names)}
        label = self.matched_labels().get(start_utc_of(run_dir)) if self.prom else None
        start = utc_epoch(start_utc_of(run_dir))
        prom_names = [n for n in names if n in NAMES]
        if source == "prometheus":
            if self.prom is None:
                raise ApiError(503, "Prometheus is not configured")
            if label is None or start is None:
                raise ApiError(503, "run %s is not in Prometheus" % name)
            missing = [n for n in names if n not in NAMES]
            if missing:
                raise ApiError(400, "not in Prometheus: %s" % ",".join(missing))
        if label is None or start is None or not prom_names:
            return {"source": "files", "series": self.file_series(run_dir, names)}
        try:
            out = self.prom.series(label, prom_names, start, time.time())
        except PromError as err:
            if source == "prometheus":
                raise ApiError(503, "Prometheus is not reachable: %s" % err)
            return {"source": "files", "series": self.file_series(run_dir, names)}
        if source == "auto" and not any(out[n]["x"] for n in prom_names):
            # Prometheus has no samples for this run (scrape gap, or past its retention). The files may have them.
            return {"source": "files", "series": self.file_series(run_dir, names)}
        # NaN and Inf from Prometheus become null, as in the file path. JSON has no NaN.
        out = {n: {**s, "x": json_list(s["x"]), "y": json_list(s["y"])} for n, s in out.items()}
        rest = [n for n in names if n not in NAMES]
        out.update(self.file_series(run_dir, rest))
        return {"source": "prometheus", "series": {n: out[n] for n in names if n in out}}

    def file_series(self, run_dir: str, names: List[str]) -> dict:
        """The series of the files of the run (specs/001 file formats)."""
        out = {}
        for series_name in names:
            if series_name == "progress_ratio":
                data = progress_ratio(run_dir)
            elif series_name in SERIES_COLUMNS:
                data = read_series(run_dir, series_name)
            else:
                raise ApiError(400, "unknown or not available from files: %s" % series_name)
            if data is not None:
                out[series_name] = {"x": json_list(data["x"]), "x_name": data["x_name"],
                                    "y": json_list(data["y"]), "metric": data["metric"]}
        return out

    def ids(self, name: str, query: Dict[str, List[str]]) -> Tuple[str, bytes, int]:
        run_dir = self.run_dir(name)
        first, _ = self.first_frame(name, run_dir)
        subset = self.subset(name, run_dir, first, query)
        ids = np.asarray(first.array("id"))[subset.indices]
        kind, body = encode_ids(ids)
        return kind, body, len(ids)

    def frame(self, name: str, index: int, query: Dict[str, List[str]]) -> bytes:
        run_dir = self.run_dir(name)
        first, frames = self.first_frame(name, run_dir)
        if index >= len(frames):
            raise ApiError(404, "run %s has no frame %d" % (name, index))
        subset = self.subset(name, run_dir, first, query)
        return encode_frame(frames[index], subset, _fields(query))

    def subset(self, name: str, run_dir: str, first: Snapshot, query: Dict[str, List[str]]):
        max_points = _int_param(query, "max_points", DEFAULT_MAX_POINTS)
        seed = _int_param(query, "seed", 1)
        return self.subsets.get(name, first, central_id_of(run_dir), max_points, seed)


class Handler(BaseHTTPRequestHandler):
    server_version = "h4nb-viz"
    timeout = 30  # Seconds to wait for each read. A request body that stops early gives 408.

    def log_message(self, format, *args):  # Keep the terminal quiet. Errors go to the status line.
        pass

    def _check_host(self):
        """Accept only the names of this server. This blocks DNS rebinding: a web page on another name
        must not read the runs through the browser."""
        port = self.server.server_address[1]
        if self.headers.get("Host") not in ("127.0.0.1:%d" % port, "localhost:%d" % port):
            raise ApiError(403, "the Host header is not allowed")

    def _token_ok(self, given: str) -> bool:
        return bool(given) and hmac.compare_digest(given.encode("utf-8"), self.server.app.token.encode("utf-8"))

    def _authorized(self) -> bool:
        """True when the request has the token in the header or in the access cookie."""
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            pass
        name = cookie_name(self.server.server_address[1])
        cookie = jar[name].value if name in jar else ""
        return self._token_ok(self.headers.get("X-H4NB-Token", "")) or self._token_ok(cookie)

    def _check_token(self):
        """Require access for every request except the page (it checks itself) and the static files.
        The path is decoded the same way as in _route, so an encoded path cannot skip the check."""
        path = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path == "/" or path.startswith("/web/"):
            return
        if not self._authorized():
            raise ApiError(403, "the token is missing or wrong")

    def do_GET(self):
        try:
            self._check_host()
            self._check_token()
            self._route()
        except ApiError as err:
            self._json(err.status, {"error": err.message})
        except Exception:  # Unexpected error: report it without the stack trace.
            traceback.print_exc()
            self._json(500, {"error": "internal error"})

    def _route(self):
        url = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(url.path)
        query = urllib.parse.parse_qs(url.query)
        app = self.server.app
        if path == "/":
            return self._index(app, query)
        if path.startswith("/web/"):
            return self._file(app.web_dir, path[len("/web/"):])
        if path == "/api/status":
            return self._json(200, app.status())
        if path == "/api/runs":
            return self._json(200, app.run_list(time.time()))
        match = FRAME_ROUTE.fullmatch(path)
        if match:
            body = app.frame(match.group(1), int(match.group(2)), query)
            return self._bytes(200, "application/octet-stream", body)
        match = IDS_ROUTE.fullmatch(path)
        if match:
            kind, body, count = app.ids(match.group(1), query)
            headers = {"X-H4NB-Id-Type": kind, "X-H4NB-Count": str(count)}
            return self._bytes(200, "application/octet-stream", body, headers)
        match = SERIES_ROUTE.fullmatch(path)
        if match:
            return self._json(200, app.series(match.group(1), query))
        match = RUN_ROUTE.fullmatch(path)
        if match:
            run_dir = app.run_dir(match.group(1))
            return self._json(200, detail(match.group(1), run_dir))
        raise ApiError(404, "no such path")

    def do_POST(self):
        try:
            self._check_host()
            self._check_token()
            self._post_route()
        except ApiError as err:
            self._json(err.status, {"error": err.message})
        except Exception:
            traceback.print_exc()
            self._json(500, {"error": "internal error"})

    def _post_route(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path != "/api/export":
            raise ApiError(404, "no such path")
        # Only the page of this server may write. Check the origin before the body is read.
        port = self.server.server_address[1]
        if self.headers.get("Origin") not in ("http://127.0.0.1:%d" % port, "http://localhost:%d" % port):
            raise ApiError(403, "the origin is not allowed")
        length = self.headers.get("Content-Length")
        if length is None:
            raise ApiError(411, "Content-Length is required")
        # Digits only. A negative or odd value would make read() wait for the connection to close.
        if not re.fullmatch(r"[0-9]+", length):
            raise ApiError(400, "Content-Length must be a number")
        size = int(length)
        if size > MAX_EXPORT_BYTES:
            raise ApiError(413, "the file is too large")
        name = urllib.parse.parse_qs(url.query).get("name", [""])[0]
        if not name:
            raise ApiError(400, "name is required")
        try:
            data = self.rfile.read(size)
        except OSError:  # Includes the timeout of the socket.
            raise ApiError(408, "the body did not arrive in time")
        if len(data) != size:
            raise ApiError(400, "the body is shorter than Content-Length")
        path = save_export(self.server.app.export_dir, name, data)
        body = {"path": path, "mp4": False}
        if path.endswith(".webm") and media.find_ffmpeg():
            mp4 = save_export_path(self.server.app.export_dir, os.path.basename(path)[:-5] + ".mp4")
            try:
                media.to_mp4(path, mp4)
                body = {"path": mp4, "webm": path, "mp4": True}
            except media.FfmpegError as err:
                body["mp4_error"] = str(err)  # Keep the WebM. Show the error.
        self._json(200, body)

    def _use_link(self, app: App, given: str) -> bool:
        """Accept the link token once. Return False for a wrong token or a token that was used."""
        with app._link_lock:
            if app._link_used or not given:
                return False
            if not hmac.compare_digest(given.encode("utf-8"), app.link_token.encode("utf-8")):
                return False
            app._link_used = True
            return True

    def _index(self, app: App, query: Dict[str, List[str]]):
        """The page. A link with the one-time token sets the access cookie and redirects to the clean
        address, so the token leaves the address bar. The session secret is never written into the page."""
        given = query.get("token", [""])[0]
        if given:
            if not self._use_link(app, given):
                raise ApiError(403, "this link is wrong or was already used. Restart the server for a new link.")
            self.send_response(303)
            self.send_header("Location", "/")
            name = cookie_name(self.server.server_address[1])
            self.send_header("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Strict" % (name, app.token))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._authorized():
            raise ApiError(403, "open the page with the link that the server printed")
        full = os.path.join(app.web_dir, "index.html")
        if not os.path.isfile(full):
            raise ApiError(404, "no such file")
        with open(full, "rb") as f:
            body = f.read()
        self._bytes(200, "text/html; charset=utf-8", body, {"Cache-Control": "no-store"})

    def _file(self, base: str, rel: str):
        full = os.path.normpath(os.path.join(base, rel))
        if not full.startswith(base + os.sep) or not os.path.isfile(full):
            raise ApiError(404, "no such file")
        with open(full, "rb") as f:
            body = f.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        self._bytes(200, ctype, body, {"Cache-Control": "max-age=3600"})

    def _json(self, status: int, obj) -> None:
        self._bytes(status, "application/json; charset=utf-8", json.dumps(obj, allow_nan=False).encode("utf-8"))

    def _bytes(self, status: int, ctype: str, body: bytes, headers: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


def make_server(root: str, port: int = 8820, export_dir: Optional[str] = None, web_dir: str = WEB_DIR,
                prometheus: Optional[str] = None, grafana_url: Optional[str] = None,
                clock: Callable[[], float] = time.monotonic) -> ThreadingHTTPServer:
    """Return a server bound to 127.0.0.1. Use port 0 to get a free port."""
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.app = App(root, export_dir, web_dir, prometheus, grafana_url, clock)
    return httpd


def serve(root: str, port: int = 8820, export_dir: Optional[str] = None, open_browser: bool = True,
          prometheus: Optional[str] = None, grafana_url: Optional[str] = None) -> None:
    httpd = make_server(root, port, export_dir, prometheus=prometheus, grafana_url=grafana_url)
    url = "http://127.0.0.1:%d/?token=%s" % (httpd.server_address[1], httpd.app.link_token)
    print("h4nb-viz: serving %s. Open this link (Ctrl+C stops the server):\n  %s" % (httpd.app.root, url), flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
