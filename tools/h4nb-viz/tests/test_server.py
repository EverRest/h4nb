import http.client
import json
import math
import os
import re
import threading
import urllib.error
import urllib.request

import numpy as np
import pytest

from h4nb_viz import server as h4nb_viz_server
from h4nb_viz.server import cookie_name, json_list, make_server
from h4nb_viz.fake import write_fake_run
from h4nb_viz.snapshots import FRAME_HEADER, FRAME_MAGIC


_TOKEN = {"value": ""}  # The token of the running test server.


@pytest.fixture
def server(fake_root, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<!doctype html><title>h4nb-viz</title>")
    (web / "app.js").write_text("console.log(1);")
    httpd = make_server(fake_root, port=0, export_dir=str(tmp_path / "exports"), web_dir=str(web))
    _TOKEN["value"] = getattr(httpd.app, "token", "")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1], httpd
    httpd.shutdown()
    httpd.server_close()


def get(base, path, token=None):
    """Return (status, headers, body) for a GET request. Error responses are returned, not raised.
    The token header is the one of the test server, unless `token` is given."""
    token = _TOKEN["value"] if token is None else token
    request = urllib.request.Request(base + path, headers={"X-H4NB-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read()


def get_json(base, path, token=None):
    status, _, body = get(base, path, token)
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
    headers = {"Content-Type": "application/octet-stream", "X-H4NB-Token": _TOKEN["value"]}
    if origin is not None:
        headers["Origin"] = origin
    request = urllib.request.Request(base + path, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def test_export_writes_file_for_the_page_origin(server, tmp_path, no_ffmpeg):
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


def call(base, path, method="GET", host=None, origin=None, body=b"", token=None):
    """Return (status, body) for one request. `host` sets the Host header, to test DNS rebinding.
    `token` defaults to the token of the test server. Pass "" to send no token."""
    headers = {"Content-Type": "application/octet-stream",
               "X-H4NB-Token": _TOKEN["value"] if token is None else token}
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
    _TOKEN["value"] = httpd.app.token
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


def test_api_request_without_token_is_refused(server):
    base, _ = server
    status, body = call(base, "/api/status", token="")
    assert status == 403 and "error" in body


def test_api_request_with_wrong_token_is_refused(server):
    base, _ = server
    assert call(base, "/api/runs", token="guess")[0] == 403


def test_api_request_with_token_is_served(server):
    base, _ = server
    assert call(base, "/api/status")[0] == 200


def test_export_without_token_is_refused(server):
    base, _ = server
    status, body = call(base, "/api/export?name=t.png", method="POST", origin=base, body=b"1", token="")
    assert status == 403 and "error" in body


def test_page_without_token_is_refused(server):
    base, _ = server
    assert get(base, "/", token="")[0] == 403


def test_page_does_not_contain_the_token(server):
    base, _ = server
    status, _, body = get(base, "/")
    assert status == 200
    assert _TOKEN["value"].encode() not in body


def raw_get(port, path, headers):
    """GET without following redirects. Return (status, headers, body)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers=dict(headers, Host="127.0.0.1:%d" % port))
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response.status, response, body


def test_link_with_token_sets_http_only_cookie_and_redirects(server):
    base, httpd = server
    port = httpd.server_address[1]
    status, response, _ = raw_get(port, "/?token=" + _TOKEN["value"], {})
    cookie = response.getheader("Set-Cookie")
    assert status == 303 and response.getheader("Location") == "/"
    assert cookie.startswith(cookie_name(port) + "=" + _TOKEN["value"])
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie


def test_link_with_wrong_token_is_refused(server):
    base, httpd = server
    status, response, _ = raw_get(httpd.server_address[1], "/?token=guess", {})
    assert status == 403 and response.getheader("Set-Cookie") is None


def test_cookie_authorizes_api_requests(server):
    base, httpd = server
    port = httpd.server_address[1]
    assert raw_get(port, "/api/status", {"Cookie": cookie_name(port) + "=" + _TOKEN["value"]})[0] == 200
    assert raw_get(port, "/api/status", {"Cookie": cookie_name(port) + "=guess"})[0] == 403


def test_cookie_name_is_specific_to_the_port():
    assert cookie_name(8820) == "h4nb_token_8820"
    assert cookie_name(8820) != cookie_name(8821)


def test_cookie_of_another_port_does_not_authorize(server):
    base, httpd = server
    port = httpd.server_address[1]
    other = cookie_name(port + 1)
    assert raw_get(port, "/api/status", {"Cookie": other + "=" + _TOKEN["value"]})[0] == 403


def test_static_files_need_no_token(server):
    base, _ = server
    assert get(base, "/web/app.js", token="")[0] == 200


def raw_post(port, path, length_header, body=b"", origin=True):
    """Send a POST with a given Content-Length header, without the helpers. Return (status, body)."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    conn.putrequest("POST", path, skip_accept_encoding=True)
    conn.putheader("Host", "127.0.0.1:%d" % port)
    if origin:
        conn.putheader("Origin", "http://127.0.0.1:%d" % port)
    conn.putheader("X-H4NB-Token", _TOKEN["value"])
    conn.putheader("Content-Length", length_header)
    conn.endheaders(body)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data


def test_content_length_must_be_a_number(server):
    base, httpd = server
    status, body = raw_post(httpd.server_address[1], "/api/export?name=a.png", "abc", b"1")
    assert status == 400 and b"error" in body


def test_negative_content_length_is_refused(server):
    base, httpd = server
    status, body = raw_post(httpd.server_address[1], "/api/export?name=a.png", "-5", b"1")
    assert status == 400 and b"error" in body


def test_content_length_above_limit_is_refused_before_reading(server, monkeypatch):
    base, httpd = server
    monkeypatch.setattr(h4nb_viz_server, "MAX_EXPORT_BYTES", 10)
    status, body = raw_post(httpd.server_address[1], "/api/export?name=a.png", "20", b"x" * 20)
    assert status == 413 and b"error" in body


def test_body_shorter_than_length_times_out_with_408(server, monkeypatch):
    base, httpd = server
    monkeypatch.setattr(h4nb_viz_server.Handler, "timeout", 1)
    status, body = raw_post(httpd.server_address[1], "/api/export?name=a.png", "20", b"x" * 5)
    assert status == 408 and b"error" in body


def test_percent_encoded_api_path_needs_the_token(server):
    """The token check and the router must see the same path. %61 is "a"."""
    base, httpd = server
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
    conn.request("GET", "/%61pi/status", headers={"Host": "127.0.0.1:%d" % httpd.server_address[1]})
    response = conn.getresponse()
    response.read()
    conn.close()
    assert response.status == 403
def test_shared_start_in_local_runs_is_not_matched(prom_server, fake_root):
    base, _ = prom_server
    align_start(os.path.join(fake_root, "flat"), START)  # Same start_utc as eta/run1.
    runs = runs_by_name(base)
    assert runs["eta~run1"]["in_prometheus"] is False and runs["flat"]["in_prometheus"] is False


def test_shared_start_in_prometheus_is_not_matched(prom_server):
    base, fake = prom_server
    fake.info_file = "prom_run_info_shared.json"
    assert runs_by_name(base)["eta~run1"]["in_prometheus"] is False


def test_bad_prometheus_answer_keeps_runs_listed(prom_server):
    base, fake = prom_server
    fake.info_file = "prom_bad_list.json"
    status, body = get_json(base, "/api/runs")
    assert status == 200 and len(body) == 2
    assert all(run["in_prometheus"] is False for run in body)


def test_auto_falls_back_when_prometheus_has_no_samples(prom_server):
    base, _ = prom_server
    status, body = get_json(base, "/api/runs/eta~run1/series?names=dt_min&source=auto")
    assert status == 200 and body["source"] == "files"


def test_explicit_prometheus_keeps_an_empty_answer(prom_server):
    base, _ = prom_server
    status, body = get_json(base, "/api/runs/eta~run1/series?names=dt_min&source=prometheus")
    assert status == 200 and body["source"] == "prometheus"


def test_export_accepts_localhost_origin(server):
    base, httpd = server
    port = httpd.server_address[1]
    status, body = call(base, "/api/export?name=lh.png", method="POST", host="localhost:%d" % port,
                        origin="http://localhost:%d" % port, body=b"1")
    assert status == 200 and body["path"].endswith("lh.png")



FAKE_CONVERTER = """#!/bin/sh
for a; do last=$a; done
if [ -n "$FAKE_FFMPEG_ERR" ]; then echo "$FAKE_FFMPEG_ERR" >&2; exit 1; fi
printf mp4 > "$last"
"""


@pytest.fixture
def fake_ffmpeg(tmp_path, monkeypatch):
    """A fake ffmpeg on PATH. It writes the text 'mp4' to its last argument."""
    bin_dir = tmp_path / "ffbin"
    bin_dir.mkdir()
    exe = bin_dir / "ffmpeg"
    exe.write_text(FAKE_CONVERTER)
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.delenv("FAKE_FFMPEG_ERR", raising=False)


@pytest.fixture
def no_ffmpeg(tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


def test_status_reports_ffmpeg_on_path(server, fake_ffmpeg):
    base, _ = server
    assert get_json(base, "/api/status")[1]["ffmpeg"] is True


def test_status_reports_no_ffmpeg(server, no_ffmpeg):
    base, _ = server
    assert get_json(base, "/api/status")[1]["ffmpeg"] is False


def test_export_converts_webm_to_mp4_when_ffmpeg_exists(server, fake_ffmpeg, tmp_path):
    base, _ = server
    status, body = post(base, "/api/export?name=clip.webm", b"video", origin=base)
    assert status == 200 and body["mp4"] is True
    assert body["path"].endswith("clip.mp4") and body["webm"].endswith("clip.webm")
    with open(body["path"], "rb") as f:
        assert f.read() == b"mp4"


def test_export_does_not_overwrite_an_existing_mp4(server, fake_ffmpeg, tmp_path):
    base, _ = server
    post(base, "/api/export?name=clip.mp4", b"old", origin=base)
    _, body = post(base, "/api/export?name=clip.webm", b"video", origin=base)
    assert body["path"].endswith("clip-1.mp4")
    with open(tmp_path / "exports" / "clip.mp4", "rb") as f:
        assert f.read() == b"old"


def test_export_keeps_webm_without_ffmpeg(server, no_ffmpeg):
    base, _ = server
    status, body = post(base, "/api/export?name=clip.webm", b"video", origin=base)
    assert status == 200 and body["mp4"] is False and body["path"].endswith("clip.webm")
    assert "mp4_error" not in body


def test_export_keeps_webm_when_ffmpeg_fails(server, fake_ffmpeg, monkeypatch):
    base, _ = server
    monkeypatch.setenv("FAKE_FFMPEG_ERR", "Invalid data found")
    status, body = post(base, "/api/export?name=clip.webm", b"video", origin=base)
    assert status == 200 and body["mp4"] is False and body["path"].endswith("clip.webm")
    assert "Invalid data found" in body["mp4_error"]


def test_series_nan_and_inf_become_null(prom_server):
    base, fake = prom_server
    fake.range_files = {"dissipated_work": "prom_dissipated_work.json"}
    status, body = get_json(base, "/api/runs/eta~run1/series?names=dissipated_work&source=auto")
    assert status == 200 and body["source"] == "prometheus"
    series = body["series"]["dissipated_work"]
    assert series["y"] == [None, None, 2e-9]
    assert series["x"] == [0.0, 0.25, 0.5]


def test_series_source_auto_reports_time_axis(prom_server):
    base, _ = prom_server
    _, body = get_json(base, "/api/runs/eta~run1/series?names=energy_rel_err&source=auto")
    assert body["series"]["energy_rel_err"]["x_name"] == "time"


def test_series_prometheus_without_label_is_503(prom_server):
    base, fake = prom_server
    fake.info_file = "prom_run_info_backfill.json"  # The run has no label in Prometheus.
    status, body = get_json(base, "/api/runs/eta~run1/series?names=energy_rel_err&source=prometheus")
    assert status == 503 and "error" in body


def test_series_prometheus_name_outside_table_is_400(prom_server):
    base, _ = prom_server
    status, body = get_json(base, "/api/runs/eta~run1/series?names=period_max_rel_err&source=prometheus")
    assert status == 400 and "error" in body
