import json
import math
import os
import re
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from h4nb_viz.server import json_list, make_server
from h4nb_viz.fake import write_fake_run
from h4nb_viz.snapshots import FRAME_HEADER, FRAME_MAGIC


@pytest.fixture
def server(fake_root, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>h4nb-viz</title>")
    (web / "app.js").write_text("console.log(1);")
    httpd = make_server(fake_root, port=0, export_dir=str(tmp_path / "exports"), web_dir=str(web))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1], httpd
    httpd.shutdown()
    httpd.server_close()


def get(base, path):
    """Return (status, headers, body) for a GET request. Error responses are returned, not raised."""
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def get_json(base, path):
    status, _, body = get(base, path)
    return status, json.loads(body)


def test_binds_to_loopback_only(server):
    _, httpd = server
    assert httpd.server_address[0] == "127.0.0.1"


def test_status_endpoint(server):
    base, _ = server
    status, body = get_json(base, "/api/status")
    assert status == 200
    assert body["version"] == "0.1.0"
    assert body["prometheus"] is None and body["prometheus_ok"] is False
    assert isinstance(body["ffmpeg"], bool)


def test_runs_list_names_and_states(server):
    base, _ = server
    status, runs = get_json(base, "/api/runs")
    assert status == 200
    assert {r["run"] for r in runs} == {"eta~run1", "flat"}
    assert all(r["state"] == "finished" for r in runs)


def test_run_detail_has_card_and_frames(server):
    base, _ = server
    status, body = get_json(base, "/api/runs/eta~run1")
    assert status == 200
    assert body["info"]["tool"] == "h4nb_viz fake"
    assert body["config"]["t_end"] == "1.0"
    assert [f["index"] for f in body["frames"]] == [0, 1, 2, 3]
    assert body["frames"][0]["file"] == "snap_000000.snap"
    assert body["frames"][-1]["file"] == "snap_final.snap"
    assert body["final_energy_rel_err"] is not None
    assert body["wall_s"] > 0


def test_ids_header_and_central_first(server):
    base, _ = server
    status, headers, body = get(base, "/api/runs/eta~run1/ids?max_points=50")
    assert status == 200
    assert headers["X-H4NB-Id-Type"] == "u32"
    assert headers["X-H4NB-Count"] == "50"
    ids = np.frombuffer(body, dtype="<u4")
    assert len(ids) == 50
    assert ids[0] == 0  # The central body is the first ID.


def test_frame_header_bytes(server):
    base, _ = server
    status, _, body = get(base, "/api/runs/eta~run1/frames/1?max_points=50&fields=pos,vel")
    assert status == 200
    magic, version, count, fields, time, cx, cy, cz, scale = FRAME_HEADER.unpack(body[:40])
    assert magic == FRAME_MAGIC and version == 1
    assert (count, fields) == (50, 3)
    assert time == pytest.approx(1 / 3)
    assert (cx, cy, cz) == (0.0, 0.0, 0.0)
    assert len(body) == 40 + 24 * 50
    assert np.allclose(np.frombuffer(body[40:52], dtype="<f4"), 0.0)  # The central body is at the center.


def test_frame_index_out_of_range_is_404(server):
    base, _ = server
    status, body = get_json(base, "/api/runs/eta~run1/frames/99")
    assert status == 404 and "error" in body


def test_unknown_run_is_404_everywhere(server):
    base, _ = server
    for path in ("/api/runs/nope", "/api/runs/nope/ids", "/api/runs/nope/frames/0", "/api/runs/nope/series?names=x"):
        status, body = get_json(base, path)
        assert status == 404 and "error" in body, path


def test_bad_query_values_are_400(server):
    base, _ = server
    assert get_json(base, "/api/runs/flat/ids?max_points=0")[0] == 400
    assert get_json(base, "/api/runs/flat/ids?max_points=abc")[0] == 400
    assert get_json(base, "/api/runs/flat/frames/0?fields=color")[0] == 400


def test_series_from_files(server):
    base, _ = server
    status, body = get_json(base, "/api/runs/eta~run1/series?names=energy_rel_err,period_max_rel_err")
    assert status == 200
    assert body["source"] == "files"
    energy = body["series"]["energy_rel_err"]
    assert len(energy["x"]) == len(energy["y"]) == 4
    assert energy["metric"] == "energy.dat:rel_err" and energy["x_name"] == "time"
    assert body["series"]["period_max_rel_err"]["x_name"] == "period"


def test_progress_ratio_is_time_over_t_end(server):
    base, _ = server
    status, body = get_json(base, "/api/runs/flat/series?names=progress_ratio")
    assert status == 200
    series = body["series"]["progress_ratio"]
    assert series["y"][-1] == pytest.approx(1.0)  # The last row is at t_end = 0.5.
    assert series["y"][0] == 0.0
    assert series["x_name"] == "time"
    assert "unit" not in series and "x" in series


def test_series_source_rules(server):
    base, _ = server
    status, body = get_json(base, "/api/runs/flat/series?names=energy_rel_err&source=auto")
    assert status == 200 and body["source"] == "files"
    status, body = get_json(base, "/api/runs/flat/series?names=energy_rel_err&source=prometheus")
    assert status == 503 and "error" in body


def test_series_unknown_name_is_400(server):
    base, _ = server
    assert get_json(base, "/api/runs/flat/series?names=eta_seconds")[0] == 400
    assert get_json(base, "/api/runs/flat/series")[0] == 400


def test_index_and_web_files(server):
    base, _ = server
    status, _, body = get(base, "/")
    assert status == 200 and b"h4nb-viz" in body
    status, headers, _ = get(base, "/web/app.js")
    assert status == 200 and headers["Cache-Control"] == "max-age=3600"


def test_files_outside_web_are_not_served(server):
    base, _ = server
    status, _, _ = get(base, "/web/../../../../etc/hosts")
    assert status == 404
    assert get(base, "/web/missing.js")[0] == 404


def test_json_list_turns_nan_into_none():
    assert json_list(np.array([1.0, np.nan, np.inf])) == [1.0, None, None]
    assert all(v is None or math.isfinite(v) for v in json_list(np.array([0.5, -2.0])))


def post(base, path, body=b"", origin=None):
    """Return (status, body) for a POST request. The origin header is sent when given."""
    headers = {"Content-Type": "application/octet-stream"}
    if origin is not None:
        headers["Origin"] = origin
    request = urllib.request.Request(base + path, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_export_writes_file_for_the_page_origin(server, tmp_path):
    base, _ = server
    status, body = post(base, "/api/export?name=clip.webm", b"video", origin=base)
    assert status == 200
    assert body["mp4"] is False and body["path"].endswith("clip.webm")
    with open(body["path"], "rb") as f:
        assert f.read() == b"video"


def test_export_refuses_other_origins(server):
    base, _ = server
    assert post(base, "/api/export?name=x.png", b"1", origin="http://evil.example")[0] == 403
    assert post(base, "/api/export?name=x.png", b"1")[0] == 403  # No origin at all.


def test_export_keeps_only_the_base_name_and_numbers_repeats(server, tmp_path):
    base, _ = server
    status, body = post(base, "/api/export?name=../../evil.png", b"a", origin=base)
    assert status == 200 and body["path"].endswith("evil.png")
    assert body["path"].startswith(str(tmp_path / "exports"))
    _, again = post(base, "/api/export?name=evil.png", b"b", origin=base)
    assert again["path"].endswith("evil-1.png")


def test_export_rejects_bad_names(server):
    base, _ = server
    assert post(base, "/api/export?name=run.exe", b"x", origin=base)[0] == 400
    assert post(base, "/api/export", b"x", origin=base)[0] == 400
    assert post(base, "/api/nothing", b"x", origin=base)[0] == 404


def call(base, path, method="GET", host=None, origin=None, body=b""):
    """Return (status, body) for one request. `host` sets the Host header, to test DNS rebinding."""
    headers = {"Content-Type": "application/octet-stream"}
    if host is not None:
        headers["Host"] = host
    if origin is not None:
        headers["Origin"] = origin
    data = body if method == "POST" else None
    request = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read() or b"null")


def test_get_with_foreign_host_is_refused(server):
    base, httpd = server
    port = httpd.server_address[1]
    assert call(base, "/api/status", host="evil.example:%d" % port)[0] == 403
    assert call(base, "/api/runs", host="attacker.test")[0] == 403


def test_get_with_right_host_is_served(server):
    base, httpd = server
    port = httpd.server_address[1]
    assert call(base, "/api/status", host="127.0.0.1:%d" % port)[0] == 200
    assert call(base, "/api/status", host="localhost:%d" % port)[0] == 200


def test_get_with_right_name_but_wrong_port_is_refused(server):
    base, httpd = server
    port = httpd.server_address[1]
    assert call(base, "/api/status", host="127.0.0.1:%d" % (port + 1))[0] == 403


def test_post_with_foreign_host_is_refused(server):
    base, httpd = server
    port = httpd.server_address[1]
    status, body = call(base, "/api/export?name=x.png", method="POST", host="evil.example:%d" % port,
                        origin=base, body=b"1")
    assert status == 403 and "error" in body


def test_post_with_right_host_is_accepted(server, tmp_path):
    base, httpd = server
    port = httpd.server_address[1]
    status, body = call(base, "/api/export?name=ok.png", method="POST", host="localhost:%d" % port,
                        origin=base, body=b"1")
    assert status == 200 and body["path"].endswith("ok.png")

# Prometheus (specs/003 T022). The run eta~run1 gets the start time of the fake h4nb_run_info series.
START = "2026-11-08T10:00:00Z"


def align_start(run_dir, start):
    """Set start_utc of run_info.txt, so that the run matches the fake Prometheus."""
    path = os.path.join(run_dir, "run_info.txt")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(re.sub(r"start_utc: .*", "start_utc: " + start, text))


@pytest.fixture
def prom_server(fake_root, tmp_path, fake_prometheus):
    align_start(os.path.join(fake_root, "eta", "run1"), START)
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>h4nb-viz</title>")
    httpd = make_server(fake_root, port=0, export_dir=str(tmp_path / "exports"), web_dir=str(web),
                        prometheus=fake_prometheus.url, grafana_url="http://127.0.0.1:3000")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1], fake_prometheus
    httpd.shutdown()
    httpd.server_close()


def runs_by_name(base):
    return {r["run"]: r for r in get_json(base, "/api/runs")[1]}


def test_runs_in_prometheus(prom_server):
    base, _ = prom_server
    run = runs_by_name(base)["eta~run1"]
    assert run["in_prometheus"] is True and run["prom_label"] == "eta/run1"


def test_run_without_match(prom_server):
    base, _ = prom_server
    run = runs_by_name(base)["flat"]  # Its start time is not in the fake data.
    assert run["in_prometheus"] is False and run["prom_label"] is None


def test_full_label_is_matched_not_its_last_part(prom_server, fake_root):
    base, _ = prom_server
    scan = os.path.join(fake_root, "scan", "run1")
    write_fake_run(scan, n=50, snaps=1, t_end=0.5, seed=5)
    align_start(scan, "2026-11-08T11:00:00Z")
    runs = runs_by_name(base)
    assert runs["scan~run1"]["prom_label"] == "scan/run1"
    assert runs["eta~run1"]["prom_label"] == "eta/run1"


def test_backfill_only_run_not_in_prometheus(prom_server):
    base, fake = prom_server
    fake.info_file = "prom_run_info_backfill.json"
    run = runs_by_name(base)["eta~run1"]
    assert run["in_prometheus"] is False


def test_series_source_auto_uses_prometheus(prom_server):
    base, _ = prom_server
    status, body = get_json(base, "/api/runs/eta~run1/series?names=energy_rel_err&source=auto")
    assert status == 200 and body["source"] == "prometheus"
    assert body["series"]["energy_rel_err"]["metric"] == "h4nb_energy_rel_err"
    assert body["series"]["energy_rel_err"]["x"] == [0.0, 0.25, 0.5, 1.0]


def test_series_source_auto_falls_back(prom_server):
    base, fake = prom_server
    fake.stop()
    status, body = get_json(base, "/api/runs/eta~run1/series?names=energy_rel_err&source=auto")
    assert status == 200 and body["source"] == "files"


def test_series_prometheus_503(prom_server):
    base, fake = prom_server
    fake.stop()
    status, body = get_json(base, "/api/runs/eta~run1/series?names=energy_rel_err&source=prometheus")
    assert status == 503 and "error" in body


def test_series_origin_filter(prom_server):
    base, fake = prom_server
    get_json(base, "/api/runs/eta~run1/series?names=energy_rel_err&source=auto")
    assert all('origin!="backfill"' in r["query"][0] for r in fake.requests)
    assert fake.requests  # The query did reach the fake.
