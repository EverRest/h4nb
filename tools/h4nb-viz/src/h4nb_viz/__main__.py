"""Command line of h4nb-viz.

  h4nb-viz fake OUT_DIR [--n 20000] [--snaps 60] [--t-end 6.3125]
  h4nb-viz serve ROOT [--port 8820] [--export-dir DIR] [--no-browser]
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .fake import write_fake_run
from .server import serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="h4nb-viz", description="Show h4nb_run results in a local web page.")
    sub = parser.add_subparsers(dest="command", required=True)

    fake = sub.add_parser("fake", help="Write a fake run for testing. It needs no GPU.")
    fake.add_argument("out_dir", help="Directory of the new run.")
    fake.add_argument("--n", type=int, default=20000, help="Number of particles, the central body included.")
    fake.add_argument("--snaps", type=int, default=60, help="Number of numbered snapshots.")
    fake.add_argument("--t-end", type=float, default=6.3125, help="End time of the run.")

    srv = sub.add_parser("serve", help="Serve the runs under ROOT on 127.0.0.1.")
    srv.add_argument("root", help="Directory that holds the run directories.")
    srv.add_argument("--port", type=int, default=8820, help="TCP port. Default: 8820.")
    srv.add_argument("--export-dir", default=None, help="Directory for exported media. Default: ~/h4nb-viz-exports.")
    srv.add_argument("--no-browser", action="store_true", help="Do not open the browser.")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "fake":
        try:
            write_fake_run(args.out_dir, n=args.n, snaps=args.snaps, t_end=args.t_end)
        except ValueError as err:
            parser.error(str(err))
        print("h4nb-viz: wrote the fake run to %s" % os.path.abspath(args.out_dir))
        return 0
    if not os.path.isdir(args.root):
        parser.error("ROOT is not a directory: %s" % args.root)
    serve(args.root, port=args.port, export_dir=args.export_dir, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
