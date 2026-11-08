import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GRAFANA = os.path.join(HERE, "..", "grafana")
CONTRACT = os.path.join(HERE, "..", "..", "..", "specs", "002-run-metrics", "contracts", "dashboard.md")
sys.path.insert(0, GRAFANA)

import build_dashboards  # noqa: E402


def panels(d):
    return [p for p in d["panels"] if p["type"] != "row"]


def contract_rows():
    """{part: {title: description}} from the tables of contracts/dashboard.md."""
    parts, part = {}, 0
    with open(CONTRACT) as f:
        for line in f:
            if line.startswith("# Part "):
                part = int(line.split()[2].rstrip(":"))
            m = re.match(r"^\| (\d+) \| ([^|]+) \|", line)
            if m and part:
                cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
                parts.setdefault(part, {})[int(cells[0])] = (cells[1], cells[-1])
    return parts


def test_json_files_match_generator():
    for name, text in build_dashboards.outputs().items():
        with open(os.path.join(GRAFANA, "dashboards", name)) as f:
            assert f.read() == text, "run grafana/build_dashboards.py"


def test_every_panel_has_contract_description():  # FR-010, SC-005
    rows = contract_rows()

    def resolve(part, num):
        title, desc = rows[part][num]
        m = re.match(r"as part 1 panel (\d+)", desc)
        return title, (rows[1][int(m.group(1))][1] if m else desc)

    for part, d in ((1, build_dashboards.live()), (2, build_dashboards.past())):
        ps = panels(d)
        assert len(ps) == len(rows[part])
        for i, p in enumerate(ps, start=1):
            title, desc = resolve(part, i)
            assert p["title"] == title
            assert p["description"].strip(), title
            assert p["description"] == desc.replace("`", ""), title
