#!/usr/bin/env python3
"""Writes dashboards/h4nb-runs.json and dashboards/h4nb-past-runs.json.

The panels, queries and descriptions follow specs/002-run-metrics/contracts/dashboard.md. Change this file, then run
it, and commit both outputs. tests/test_dashboards.py checks that the JSON files match this script and the contract.
"""
import json
import os

DS = {"type": "prometheus", "uid": "prometheus"}
# links.md section 1. The field template uses the run of the clicked row.
VIEWER_URL = "http://127.0.0.1:8820/#run=${__data.fields.run:percentencode}"
HERE = os.path.dirname(os.path.abspath(__file__))

STATE_MAPPINGS = [{"type": "value", "options": {
    "0": {"text": "running", "color": "blue", "index": 0},
    "1": {"text": "finished", "color": "green", "index": 1},
    "2": {"text": "stopped early", "color": "red", "index": 2},
    "3": {"text": "stalled", "color": "orange", "index": 3},
}}]

# --- descriptions (tooltips): the text of contracts/dashboard.md ---------------------------------------------------
D = {
    "state": "State of the run from its files. Running: the .dat.tmp files change. Finished: t reached t_end. Stopped early: h4nb_run stopped before t_end with an error; read the screen output of the run. Stalled: the files did not change for longer than 5 segment times (minimum 300 s); the process hangs, was killed, or an MPI rank failed.",
    "progress": "Simulation time divided by t_end.",
    "eta": "Estimated wall time to t_end. It uses the speed of the last 10 diag segments, because the step size changes during a run. Compare this value with the time limit of the job.",
    "wall": "Sum of the wall time of all diag segments. Multiply by the number of GPUs to get GPU hours. Start-up time is not included.",
    "age": "Time since the run last wrote a .dat file. h4nb_run writes once each diag interval. A value much larger than the segment wall time means that the run does not progress.",
    "particles": "Number of bodies N, the central body included. Source: key n of config.used, or the header of a snapshot.",
    "rel_err": "rel_err = abs(E - E0 - W_diss) / D at each diag time. D is abs(E0) (energy_norm=e0) or abs(K0) + abs(U0) (ku). The dashed line is energy_tol. The project goal is rel_err <= 1e-8 over one period. A line that grows steadily means drift: decrease eta or dt_max.",
    "max_err": "Largest rel_err since t = 0. Green: below 1e-8. Red: above. A scrape can miss a short peak of rel_err; this value does not miss it. The exact verdict per period is in the panel \"Error per period\" at the end of the run.",
    "mean_err": "Mean of rel_err over all diag times. Noise gives a flat mean. A systematic error gives a mean that grows with time.",
    "dpdl": "dP_rel and dL_rel: change of the total momentum and angular momentum, divided by sum m abs(v) and sum m abs(r x v) of the initial state. Both must stay near the round-off level (about 1e-14). Growth of dP_rel can mean an asymmetric force sum, for example on several GPUs. Growth of dL_rel means an orbit error.",
    "wdiss": "W_diss: work of the drag force since t = 0. It is 0 with dissipation=off. The energy error already subtracts it. A large W_diss with a small error means that the energy balance is correct.",
    "periods": "Largest rel_err in each reference period T, from energy_periods.dat. h4nb_run writes this file only at the end of the run, so the panel is empty during a run.",
    "dt": "Smallest, mean and largest individual time step at each diag time. Steps are dt_max / 2^k. A fast fall of dt_min means a close encounter, and the run becomes slower. dt_min near dt_max / 2^max_level means the step limit is near.",
    "active": "Mean number of particles that move in one block step. Each block step starts the force kernel once for these particles. A value below a few thousand does not fill the GPU, and pairs/s becomes lower. This is normal for the small levels.",
    "rmin": "Smallest pair distance seen in the diag segment. The dashed line is the softening length eps. Below eps, the force is softened. A value below r_close gives a warning in the screen output.",
    "pairs": "Force pair evaluations per second in the last diag segment: active x N / wall_s. Compare with bench.dat of the same N and GPU. A fall can mean a small active count (see \"Active particles per block step\"), GPU throttling, or another job on the GPU.",
    "gflops": "60 x pairs/s / 1e9. 60 FP64 operations for each pair (research.md R6). Divide by the FP64 peak of the GPU to get the efficiency.",
    "updates": "Particles advanced per second in the last diag segment: active / wall_s. Use it to compare runs with different N.",
    "steps": "Block steps per second, averaged over 5 minutes. Many block steps with few active particles means launch overhead dominates.",
    "segment": "Wall time of the last diag interval. The files update once in this time. Use it to read the panel \"Last file update\".",
    "record": "Code, machine and settings of each run, from run_info.txt and config.used. A commit that ends with -dirty was built with local changes. Compare eta, eps and dt_max before you compare errors or speed.",
    # Part 2
    "runlist": "All runs with data in the selected time range. Click a run name to select it and to set the time range to the start and the end of the run. If a run is missing, make the time range larger or load the run with h4nb-metrics backfill.",
    "final_state": "Final state of the run. Finished: t reached t_end. Stopped early: h4nb_run stopped with an error before t_end. Stalled: the archive has only .dat.tmp files; the process hung, was killed, or an MPI rank failed.",
    "final_max_err": "Largest relative energy error from t = 0 to the end of the run. Green: below 1e-8. Red: above.",
    "final_dpdl": "Relative change of the total momentum and of the angular momentum at the last diag time. Both must be near the round-off level (about 1e-14).",
    "mean_pairs": "Mean of pairs/s over all diag segments in the time range. Compare it between runs with the same N and GPU.",
    "final_wall": "Sum of the wall time of all diag segments. Multiply by the number of GPUs to get GPU hours.",
    "final_periods": "Largest relative energy error in each reference period T, from energy_periods.dat. The goal is <= 1e-8 in period 1. A period with complete = 0 was not finished by the run.",
    "xy": "Relative energy error at each diag time, plotted against the simulation time. One reference period is T (key period). Steps in the curve at close encounters are normal. A slope that does not stop means drift.",
}

ERR_THRESHOLDS = {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": 1e-8}]}
NEUTRAL = {"mode": "absolute", "steps": [{"color": "text", "value": None}]}


class Builder:
    def __init__(self):
        self.panels = []
        self.next_id = 1
        self.y = 0

    def row(self, title):
        self.panels.append({"type": "row", "title": title, "id": self._id(), "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []})
        self.y += 1

    def _id(self):
        i = self.next_id
        self.next_id += 1
        return i

    def add(self, panel, x, w, h):
        panel["id"] = self._id()
        panel["gridPos"] = {"h": h, "w": w, "x": x, "y": self.y}
        panel["datasource"] = DS
        self.panels.append(panel)

    def newline(self, h):
        self.y += h


def target(expr, ref="A", legend="{{run}}", instant=False, table=False):
    t = {"datasource": DS, "refId": ref, "expr": expr, "legendFormat": legend, "range": not instant, "instant": instant}
    if table:
        t["format"] = "table"
    return t


def timeseries(title, desc, targets, unit="short", log=False, threshold_refs=()):
    custom = {"drawStyle": "line", "lineWidth": 1, "fillOpacity": 0, "showPoints": "never", "spanNulls": False}
    if log:
        custom["scaleDistribution"] = {"type": "log", "log": 10}
    overrides = [{"matcher": {"id": "byFrameRefID", "options": ref}, "properties": [
        {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
        {"id": "custom.fillOpacity", "value": 0},
        {"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]} for ref in threshold_refs]
    return {"type": "timeseries", "title": title, "description": desc, "targets": targets,
            "fieldConfig": {"defaults": {"unit": unit, "custom": custom, "color": {"mode": "palette-classic"}},
                            "overrides": overrides},
            "options": {"legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                        "tooltip": {"mode": "multi", "sort": "desc"}}}


def stat(title, desc, targets, unit="short", thresholds=NEUTRAL, mappings=None, color_mode="value", decimals=None):
    defaults = {"unit": unit, "thresholds": thresholds, "mappings": mappings or [], "color": {"mode": "thresholds"}}
    if decimals is not None:
        defaults["decimals"] = decimals
    return {"type": "stat", "title": title, "description": desc, "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": color_mode, "graphMode": "none", "textMode": "value_and_name",
                        "justifyMode": "auto", "orientation": "auto"}}


def bargauge(title, desc, targets, unit, min_=None, max_=None, log=False, thresholds=NEUTRAL):
    defaults = {"unit": unit, "thresholds": thresholds, "color": {"mode": "thresholds"}}
    if min_ is not None:
        defaults["min"] = min_
    if max_ is not None:
        defaults["max"] = max_
    if log:
        defaults["custom"] = {"scaleDistribution": {"type": "log", "log": 10}}
    return {"type": "bargauge", "title": title, "description": desc, "targets": targets,
            "fieldConfig": {"defaults": defaults, "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "displayMode": "gradient", "orientation": "horizontal", "showUnfilled": True,
                        "valueMode": "color", "namePlacement": "left"}}


RECORD_KEYS = ["eta", "eps", "dt_max", "diag", "energy_tol", "tile", "blocks_per_sm"]
INFO_COLUMNS = ["run", "host", "gpu", "ranks", "mpi", "commit", "build_type", "preset", "start_utc"]


def record_table(run_sel, wrap=lambda e: e):
    refs = "BCDEFGH"
    targets = [target(wrap('h4nb_run_info{%s}' % run_sel), "A", instant=True, table=True)]
    rename = {}
    for ref, key in zip(refs, RECORD_KEYS):
        targets.append(target("max by (run) (%s)" % wrap('h4nb_config_value{key="%s",%s}' % (key, run_sel)), ref,
                              instant=True, table=True))
        rename["Value #" + ref] = key
    exclude = {"Time": True, "Value #A": True, "__name__": True, "job": True, "instance": True, "origin": True}
    order = {name: i for i, name in enumerate(INFO_COLUMNS + RECORD_KEYS)}
    return {"type": "table", "title": "Run record", "description": D["record"], "targets": targets,
            "transformations": [{"id": "merge", "options": {}},
                                {"id": "organize", "options": {"excludeByName": exclude, "renameByName": rename,
                                                               "indexByName": order}}],
            "fieldConfig": {"defaults": {"custom": {"align": "auto", "minWidth": 60}}, "overrides": [
                # links.md section 1: "Open in h4nb-viz", one link per run row.
                {"matcher": {"id": "byName", "options": "run"}, "properties": [
                    {"id": "links", "value": [{"title": "Open in h4nb-viz", "url": VIEWER_URL}]}]}]},
            "options": {"showHeader": True, "cellHeight": "sm"}}


def dashboard(uid, title, panels, variables, time_from, refresh, description):
    return {
        "uid": uid, "title": title, "description": description, "tags": ["h4nb"], "editable": True,
        "schemaVersion": 39, "version": 1, "timezone": "utc", "graphTooltip": 1,
        "time": {"from": time_from, "to": "now"}, "refresh": refresh,
        "templating": {"list": variables}, "annotations": {"list": []}, "links": [
            {"type": "dashboards", "tags": ["h4nb"], "title": "h4nb dashboards", "asDropdown": True}],
        "panels": panels,
    }


def run_variable(multi):
    v = {"name": "run", "label": "Run", "type": "query", "datasource": DS, "refresh": 2, "sort": 1,
         "query": {"query": "label_values(h4nb_run_info, run)", "refId": "run"},
         "definition": "label_values(h4nb_run_info, run)", "multi": multi, "includeAll": multi}
    if multi:
        v["current"] = {"text": ["All"], "value": ["$__all"]}
    return v


def live():
    S = 'run=~"$run"'
    b = Builder()
    b.row("Status")
    b.add(stat("Run state", D["state"], [target("h4nb_run_state{%s}" % S)], mappings=STATE_MAPPINGS,
               color_mode="background"), 0, 4, 5)
    b.add(bargauge("Progress", D["progress"], [target("h4nb_progress_ratio{%s}" % S)], "percentunit", 0, 1), 4, 6, 5)
    b.add(stat("Time to end", D["eta"], [target("h4nb_eta_seconds{%s}" % S)], "s"), 10, 4, 5)
    b.add(stat("Wall time used", D["wall"], [target("h4nb_wall_seconds_total{%s}" % S)], "s"), 14, 3, 5)
    b.add(stat("Last file update", D["age"], [target("h4nb_last_update_age_seconds{%s}" % S)], "s",
               {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "orange", "value": 300}]}),
          17, 4, 5)
    b.add(stat("Particles", D["particles"], [target("h4nb_particles{%s}" % S)], "short"), 21, 3, 5)
    b.newline(5)
    b.row("Accuracy")
    b.add(timeseries("Relative energy error", D["rel_err"], [
        target("h4nb_energy_rel_err{%s}" % S),
        target('max(h4nb_config_value{key="energy_tol",%s})' % S, "B", "energy_tol")], "sci", True, ["B"]),
        0, 12, 8)
    b.add(stat("Max energy error vs tolerance", D["max_err"], [target("h4nb_energy_max_rel_err{%s}" % S)], "sci",
               ERR_THRESHOLDS, color_mode="background", decimals=2), 12, 4, 8)
    b.add(timeseries("Mean energy error", D["mean_err"], [target("h4nb_energy_mean_rel_err{%s}" % S)], "sci", True),
          16, 8, 8)
    b.newline(8)
    b.add(timeseries("Momentum and angular momentum change", D["dpdl"], [
        target("h4nb_momentum_rel_change{%s}" % S, "A", "dP_rel {{run}}"),
        target("h4nb_angular_momentum_rel_change{%s}" % S, "B", "dL_rel {{run}}")], "sci", True), 0, 10, 8)
    b.add(timeseries("Dissipated work", D["wdiss"], [target("h4nb_dissipated_work{%s}" % S)], "short"), 10, 6, 8)
    b.add(bargauge("Error per period", D["periods"], [
        target("h4nb_period_max_rel_err{%s}" % S, legend="{{run}} period {{period}}", instant=True)], "sci",
        log=True, thresholds=ERR_THRESHOLDS), 16, 8, 8)
    b.newline(8)
    b.row("Time steps")
    b.add(timeseries("Block time steps", D["dt"], [
        target("h4nb_dt_min{%s}" % S, "A", "dt_min {{run}}"), target("h4nb_dt_mean{%s}" % S, "B", "dt_mean {{run}}"),
        target("h4nb_dt_max{%s}" % S, "C", "dt_max {{run}}")], "sci", True), 0, 8, 8)
    b.add(timeseries("Active particles per block step", D["active"],
                     [target("h4nb_active_per_block_step{%s}" % S)], "short"), 8, 8, 8)
    b.add(timeseries("Minimum pair distance", D["rmin"], [
        target("h4nb_r_min{%s}" % S), target('max(h4nb_config_value{key="eps",%s})' % S, "B", "eps")],
        "sci", True, ["B"]), 16, 8, 8)
    b.newline(8)
    b.row("Performance")
    b.add(timeseries("Pair interactions per second", D["pairs"], [target("h4nb_pairs_per_second{%s}" % S)], "short"),
          0, 8, 8)
    b.add(stat("GFLOP/s", D["gflops"], [target("h4nb_gflops{%s}" % S)], "short", decimals=0), 8, 4, 8)
    b.add(timeseries("Particle updates per second", D["updates"],
                     [target("h4nb_particle_updates_per_second{%s}" % S)], "short"), 12, 6, 8)
    b.add(timeseries("Block steps per second", D["steps"],
                     [target("rate(h4nb_block_steps_total{%s}[5m])" % S)], "short"), 18, 6, 8)
    b.newline(8)
    b.add(timeseries("Segment wall time", D["segment"], [target("h4nb_segment_wall_seconds{%s}" % S)], "s"), 0, 8, 6)
    b.newline(6)
    b.row("Run record")
    b.add(record_table(S), 0, 24, 6)
    return dashboard("h4nb-runs", "h4nb runs", b.panels, [run_variable(True)], "now-1h", "15s",
                     "Live view of h4nb_run runs, from h4nb-metrics serve. specs/002-run-metrics.")


def past():
    S = 'run="$run"'
    last = lambda e: "last_over_time(%s[$__range])" % e
    b = Builder()
    b.row("Runs")
    list_targets = [
        target("max by (run) (%s) * 1000" % last("h4nb_run_start_timestamp_seconds"), "A", instant=True, table=True),
        target("max by (run) (%s) * 1000" % last("h4nb_run_end_timestamp_seconds"), "B", instant=True, table=True),
        target("max by (run) (%s)" % last("h4nb_run_state"), "C", instant=True, table=True),
        target("max by (run) (%s)" % last("h4nb_particles"), "D", instant=True, table=True),
        target("max by (run) (%s)" % last("h4nb_energy_max_rel_err"), "E", instant=True, table=True),
    ]
    link = ("/d/h4nb-past-runs/h4nb-past-runs?var-run=${__value.raw}"
            "&from=${__data.fields[\"start\"]}&to=${__data.fields[\"end\"]}")
    runlist = {"type": "table", "title": "Run list", "description": D["runlist"], "targets": list_targets,
               "transformations": [
                   {"id": "merge", "options": {}},
                   {"id": "organize", "options": {"excludeByName": {"Time": True}, "renameByName": {
                       "Value #A": "start", "Value #B": "end", "Value #C": "state", "Value #D": "N",
                       "Value #E": "max_rel_err"}, "indexByName": {"run": 0, "start": 1, "end": 2, "state": 3,
                                                                    "N": 4, "max_rel_err": 5}}},
                   {"id": "sortBy", "options": {"sort": [{"field": "start", "desc": True}]}}],
               "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": [
                   {"matcher": {"id": "byName", "options": "run"}, "properties": [
                       {"id": "links", "value": [{"title": "Open this run", "url": link}]}]},
                   {"matcher": {"id": "byName", "options": "start"}, "properties": [{"id": "unit", "value": "dateTimeAsIso"}]},
                   {"matcher": {"id": "byName", "options": "end"}, "properties": [{"id": "unit", "value": "dateTimeAsIso"}]},
                   {"matcher": {"id": "byName", "options": "state"}, "properties": [
                       {"id": "mappings", "value": STATE_MAPPINGS},
                       {"id": "custom.cellOptions", "value": {"type": "color-background"}}]},
                   {"matcher": {"id": "byName", "options": "max_rel_err"}, "properties": [
                       {"id": "unit", "value": "sci"}, {"id": "decimals", "value": 2},
                       {"id": "thresholds", "value": ERR_THRESHOLDS},
                       {"id": "custom.cellOptions", "value": {"type": "color-text"}}]}]},
               "options": {"showHeader": True, "cellHeight": "sm"}}
    b.add(runlist, 0, 24, 7)
    b.newline(7)
    b.row("Result of the selected run")
    b.add(stat("Final state", D["final_state"], [target(last("h4nb_run_state{%s}" % S), instant=True)],
               mappings=STATE_MAPPINGS, color_mode="background"), 0, 4, 5)
    b.add(stat("Max energy error", D["final_max_err"], [target(last("h4nb_energy_max_rel_err{%s}" % S), instant=True)],
               "sci", ERR_THRESHOLDS, color_mode="background", decimals=2), 4, 4, 5)
    b.add(stat("Final dP_rel and dL_rel", D["final_dpdl"], [
        target(last("h4nb_momentum_rel_change{%s}" % S), "A", "dP_rel", instant=True),
        target(last("h4nb_angular_momentum_rel_change{%s}" % S), "B", "dL_rel", instant=True)], "sci",
        decimals=2), 8, 5, 5)
    b.add(stat("Mean pair rate", D["mean_pairs"], [
        target("avg_over_time(h4nb_pairs_per_second{%s}[$__range])" % S, instant=True)], "short"), 13, 4, 5)
    b.add(stat("Wall time", D["final_wall"], [target(last("h4nb_wall_seconds_total{%s}" % S), instant=True)], "s"),
          17, 3, 5)
    b.add(bargauge("Error per period", D["final_periods"], [
        target(last("h4nb_period_max_rel_err{%s}" % S), legend="period {{period}}", instant=True)], "sci", log=True,
        thresholds=ERR_THRESHOLDS), 20, 4, 5)
    b.newline(5)
    b.row("Curves of the selected run")
    xy = {"type": "xychart", "title": "Energy error against simulation time", "description": D["xy"],
          "targets": [target("max(h4nb_sim_time{%s})" % S, "A", "sim_time"),
                      target("max(h4nb_energy_rel_err{%s})" % S, "B", "rel_err")],
          "transformations": [{"id": "joinByField", "options": {"byField": "Time", "mode": "outer"}}],
          "fieldConfig": {"defaults": {"unit": "sci", "custom": {
              "show": "lines", "lineWidth": 1, "pointSize": {"fixed": 3},
              "scaleDistribution": {"type": "log", "log": 10}, "axisPlacement": "auto"}, "color": {"mode": "palette-classic"}},
              "overrides": [{"matcher": {"id": "byName", "options": "sim_time"}, "properties": [
                  {"id": "unit", "value": "short"}, {"id": "custom.scaleDistribution", "value": {"type": "linear"}},
                  {"id": "custom.axisLabel", "value": "simulation time"}]}]},
          "options": {"seriesMapping": "auto", "dims": {"frame": 0, "x": "sim_time", "exclude": ["Time"]},
                      "series": [], "legend": {"showLegend": True, "displayMode": "list", "placement": "bottom"},
                      "tooltip": {"mode": "single"}}}
    b.add(xy, 0, 24, 9)
    b.newline(9)
    b.add(timeseries("Relative energy error", D["rel_err"], [
        target("h4nb_energy_rel_err{%s}" % S),
        target('max(h4nb_config_value{key="energy_tol",%s})' % S, "B", "energy_tol")], "sci", True, ["B"]),
        0, 12, 8)
    b.add(timeseries("Momentum and angular momentum change", D["dpdl"], [
        target("h4nb_momentum_rel_change{%s}" % S, "A", "dP_rel {{run}}"),
        target("h4nb_angular_momentum_rel_change{%s}" % S, "B", "dL_rel {{run}}")], "sci", True), 12, 12, 8)
    b.newline(8)
    b.add(timeseries("Block time steps", D["dt"], [
        target("h4nb_dt_min{%s}" % S, "A", "dt_min {{run}}"), target("h4nb_dt_mean{%s}" % S, "B", "dt_mean {{run}}"),
        target("h4nb_dt_max{%s}" % S, "C", "dt_max {{run}}")], "sci", True), 0, 8, 8)
    b.add(timeseries("Active particles per block step", D["active"],
                     [target("h4nb_active_per_block_step{%s}" % S)], "short"), 8, 8, 8)
    b.add(timeseries("Minimum pair distance", D["rmin"], [
        target("h4nb_r_min{%s}" % S), target('max(h4nb_config_value{key="eps",%s})' % S, "B", "eps")],
        "sci", True, ["B"]), 16, 8, 8)
    b.newline(8)
    b.add(timeseries("Pair interactions per second", D["pairs"], [target("h4nb_pairs_per_second{%s}" % S)], "short"),
          0, 24, 7)
    b.newline(7)
    b.row("Run record")
    b.add(record_table(S, last), 0, 24, 5)
    return dashboard("h4nb-past-runs", "h4nb past runs", b.panels, [run_variable(False)], "now-1y", "",
                     "Finished runs from h4nb-metrics backfill or from the Prometheus history. specs/002-run-metrics.")


def render(d):
    return json.dumps(d, indent=2, sort_keys=False) + "\n"


def outputs():
    return {"h4nb-runs.json": render(live()), "h4nb-past-runs.json": render(past())}


if __name__ == "__main__":
    for name, text in outputs().items():
        path = os.path.join(HERE, "dashboards", name)
        with open(path, "w") as f:
            f.write(text)
        print("wrote", path)
