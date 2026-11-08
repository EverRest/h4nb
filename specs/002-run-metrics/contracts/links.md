# Contract: links from the dashboards to other tools

This file defines the links that leave the dashboards. Each link has one target, one URL template and one place in a dashboard.

## 1. Link "Open in h4nb-viz"

| Item | Value |
|---|---|
| Target | The local viewer of specs/003-run-visualization (`h4nb-viz serve`) |
| URL template | `http://127.0.0.1:8820/#run=${__data.fields.run:percentencode}` |
| Where | Data link on the column `run` of the table "Run record" (part 1, panel 21, and part 2, panel 15). Grafana shows it when the user clicks a run name. |
| Link title | Open in h4nb-viz |
| Port | 8820 (default of `h4nb-viz serve`) |
| Host | `127.0.0.1` only. The viewer listens on that address (specs/003 FR-002). |

### Why the field and not the variable

The variable `${run}` holds all selected runs when the user selects several. A data link needs the run of the clicked row. `${__data.fields.run}` gives that run. For one selected run, both templates give the same value.

### Value of the `run` parameter

- The value is the run label of specs/002 (`metrics.md` section 0, `run` label), unchanged.
- A label can contain `/` when two run directories have the same name (spec.md, Key Entities). The label is then the path relative to the parent of the given path. Its first part is the name of the given directory.
- `:percentencode` encodes every character that is not allowed in a URL, including `/`. A `/` in the label becomes `%2F` in the link. The viewer decodes the value after `run=` before it matches the value with its run list.
- The viewer maps `/` to `~` only in its own run names (specs/003, `/api/runs/{run}`). It does not change the label that Grafana sends.

### Matching rule for the viewer

The viewer selects the run whose name is the label. The viewer shows a message when no run has that name. The message says that the run is in Grafana but not on the disk of the viewer.

## 2. Other links

The dashboard "h4nb past runs" has one internal data link: the run list sets `var-run`, `from` and `to` (dashboard.md, part 2, panel 1). This link is not an external link. It is not defined in this file.

## 3. Implementation notes

- The links are part of `grafana/build_dashboards.py` (the JSON is generated). A change of this file changes both dashboard JSON files.
- `tools/h4nb-metrics/tests/test_dashboards.py` checks that the "Run record" table of each dashboard has the link with this URL. The URL is the one in section 1.

## 4. Viewer side of the link

Resolved in specs/003 `http-api.md`, section "Run name and label" (2026-11-08). The viewer reads the text after `run=` and applies `decodeURIComponent` once. The decoded value must equal the run label exactly. One match selects the run. No match shows a message. Two matches show a message. The viewer does not match on the last part of the label and does not use the `~` form.
