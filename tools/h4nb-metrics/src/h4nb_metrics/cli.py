"""Command line: h4nb-metrics serve | dump | backfill | fake-run."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from typing import Optional

from . import __version__


def cmd_serve(a) -> int:
    from prometheus_client import start_http_server

    from .exporter import make_registry

    registry = make_registry(a.paths, a.max_depth, a.rescan, a.stale_min)
    start_http_server(a.port, addr=a.addr, registry=registry)
    print("h4nb-metrics: serving http://%s:%d/metrics for %s" % (a.addr, a.port, " ".join(a.paths)), flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


def cmd_dump(a) -> int:
    from prometheus_client import generate_latest

    from .exporter import make_registry

    sys.stdout.write(generate_latest(make_registry(a.paths, a.max_depth, 0.0, a.stale_min)).decode())
    return 0


def cmd_backfill(a) -> int:
    from .backfill import load_runs, write_openmetrics

    runs = load_runs(a.paths, a.max_depth)
    if not runs:
        print("h4nb-metrics backfill: no h4nb_run directory found in %s" % " ".join(a.paths), file=sys.stderr)
        return 1
    out = a.output
    if a.load and out == "-":
        out = os.path.join(a.compose_dir, "backfill", "h4nb-backfill.om")
    if a.load and out != "-" and backfill_rel(a.compose_dir, out) is None:  # check before any write
        print("h4nb-metrics backfill: with --load, the output must be in %s/backfill" % a.compose_dir, file=sys.stderr)
        return 2
    if out == "-":
        n = write_openmetrics(runs, sys.stdout)
    else:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w") as f:
            n = write_openmetrics(runs, f)
    print("h4nb-metrics backfill: %d runs, %d samples -> %s" % (len(runs), n, out), file=sys.stderr)
    for r in runs:
        print("  %s" % r.label, file=sys.stderr)
    if not a.load:
        return 0
    return load_into_compose(a.compose_dir, out)


def backfill_rel(compose_dir: str, om_file: str) -> Optional[str]:
    """The path of om_file inside <compose_dir>/backfill, or None when it is outside."""
    rel = os.path.relpath(os.path.abspath(om_file), os.path.join(os.path.abspath(compose_dir), "backfill"))
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return rel


def _run(cmd) -> int:
    print("+ " + " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd).returncode


def load_into_compose(compose_dir: str, om_file: str) -> int:
    """Adds the blocks with promtool to the Prometheus data volume of docker-compose.yml (spec FR-016, plan P6).
    Prometheus is stopped while promtool writes. It is started again even when promtool fails.
    The compose file mounts <compose_dir>/backfill at /backfill."""
    if shutil.which("docker") is None:
        print("h4nb-metrics backfill: docker is not found. Run promtool by hand:\n"
              "  promtool tsdb create-blocks-from openmetrics %s <prometheus data dir>" % om_file, file=sys.stderr)
        return 1
    rel = backfill_rel(compose_dir, om_file)
    if rel is None:
        print("h4nb-metrics backfill: with --load, the output must be in %s/backfill" % compose_dir, file=sys.stderr)
        return 2
    # The compose files of this directory. Only the default file is used: promtool needs no network.
    base = ["docker", "compose", "--project-directory", compose_dir]
    if _run(base + ["stop", "prometheus"]) != 0:  # stop fails: nothing was written, Prometheus is unchanged.
        return 1
    # One-off container from the same image and the same data volume.
    rc = _run(base + ["run", "--rm", "--no-deps", "--entrypoint", "promtool", "prometheus", "tsdb",
                      "create-blocks-from", "openmetrics", "/backfill/" + rel, "/prometheus"])
    start_rc = _run(base + ["start", "prometheus"])  # Prometheus loads the new blocks at the start.
    return rc or start_rc


def cmd_fake_run(a) -> int:
    from .fakerun import fake_run

    start = None
    if a.start_utc:
        from .runs import parse_utc

        start = parse_utc(a.start_utc)
        if start is None:
            print("h4nb-metrics fake-run: --start-utc must be YYYY-MM-DDTHH:MM:SSZ", file=sys.stderr)
            return 2
    return fake_run(a.out, n=a.n, t_end=a.t_end, diag=a.diag, interval=a.interval, eta=a.eta, eps=a.eps,
                    fail_at=a.fail_at, hang_at=a.hang_at, instant=a.instant, start_utc=start, seed=a.seed)


def default_compose_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", ".."), os.getcwd()):
        if os.path.exists(os.path.join(cand, "docker-compose.yml")):
            return os.path.normpath(cand)
    return os.getcwd()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="h4nb-metrics", description="Expose the output files of h4nb_run as "
                                "Prometheus metrics. Reads files only.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    def paths_args(sp):
        sp.add_argument("paths", nargs="+", help="Run directories, parent directories or h4nb_logs_*.tar.gz archives.")
        sp.add_argument("--max-depth", type=int, default=2, help="Search depth in a parent directory (default 2).")
        sp.add_argument("--stale-min", type=float, default=300.0,
                        help="Minimum time without a file change before a run is stalled, in s (default 300).")

    s = sub.add_parser("serve", help="Start the HTTP exporter.")
    paths_args(s)
    s.add_argument("--addr", default="127.0.0.1", help="Listen address (default 127.0.0.1). 0.0.0.0 opens it to the network.")
    s.add_argument("--port", type=int, default=9810, help="Port (default 9810).")
    s.add_argument("--rescan", type=float, default=10.0, help="Minimum time between two searches for new runs, in s.")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("dump", help="Print the metrics once and exit.")
    paths_args(s)
    s.set_defaults(func=cmd_dump)

    s = sub.add_parser("backfill", help="Write all rows of finished runs as OpenMetrics with time stamps.")
    paths_args(s)
    s.add_argument("-o", "--output", default="-", help="Output file (default: standard output).")
    s.add_argument("--load", action="store_true", help="Load the file into the Prometheus of docker-compose.yml.")
    s.add_argument("--compose-dir", default=default_compose_dir(), help="Directory of docker-compose.yml.")
    s.set_defaults(func=cmd_backfill)

    s = sub.add_parser("fake-run", help="Write a fake run (no GPU) to check the exporter and the dashboards.")
    s.add_argument("out", help="Output directory.")
    s.add_argument("--n", type=int, default=131072, help="Particle count written to config.used (default 131072).")
    s.add_argument("--t-end", type=float, default=6.3125)
    s.add_argument("--diag", type=float, default=0.0625)
    s.add_argument("--interval", type=float, default=1.0, help="Wall seconds for each diag segment (default 1).")
    s.add_argument("--eta", type=float, default=0.0005)
    s.add_argument("--eps", type=float, default=0.01)
    s.add_argument("--fail-at", type=float, help="Stop with NaN at this simulation time (state: stopped early).")
    s.add_argument("--hang-at", type=float, help="Stop writing at this simulation time (state: stalled).")
    s.add_argument("--instant", action="store_true", help="Do not sleep. Use for backfill tests.")
    s.add_argument("--start-utc", help="Start time written to run_info.txt, YYYY-MM-DDTHH:MM:SSZ.")
    s.add_argument("--seed", type=int, default=1)
    s.set_defaults(func=cmd_fake_run)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
