import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class _FakePromHandler(BaseHTTPRequestHandler):
    """Answers the three endpoints of the Prometheus HTTP API with fixed JSON from tests/data."""

    def log_message(self, *args):
        pass

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(url.query)
        fake = self.server.fake
        if url.path == "/-/ready":
            return self._send(b"Prometheus Server is Ready.", "text/plain")
        if url.path == "/api/v1/query":
            fake.requests.append(query)
            return self._send(_read_data(fake.info_file))
        if url.path == "/api/v1/query_range":
            fake.requests.append(query)
            metric = query["query"][0].split("{")[0]
            name = "prom_%s.json" % metric[len("h4nb_"):]
            if os.path.exists(os.path.join(DATA_DIR, name)):
                return self._send(_read_data(name))
            return self._send(b'{"status": "success", "data": {"resultType": "matrix", "result": []}}')
        self._send(b'{"status": "error", "error": "not found"}', status=404)

    def _send(self, body, ctype="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _read_data(name):
    with open(os.path.join(DATA_DIR, name), "rb") as f:
        return f.read()


class FakePrometheus:
    """A stand-in for Prometheus. `requests` holds the parsed query string of each API call.
    `info_file` names the data file that answers h4nb_run_info."""

    def __init__(self, httpd):
        self.httpd = httpd
        self.url = "http://127.0.0.1:%d" % httpd.server_address[1]
        self.requests = []
        self.info_file = "prom_run_info.json"
        self.running = True

    def stop(self):
        """Stop answering. The port then refuses connections, as when Prometheus is down."""
        if self.running:
            self.running = False
            self.httpd.shutdown()
            self.httpd.server_close()


@pytest.fixture
def fake_prometheus():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakePromHandler)
    httpd.fake = FakePrometheus(httpd)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.fake
    httpd.fake.stop()
