"""Command line of h4nb-viz.

  h4nb-viz fake OUT_DIR [--n 20000] [--snaps 60] [--t-end 6.3125]
  h4nb-viz thin RUN_DIR OUT_DIR [--max-points 200000] [--seed 1]
  h4nb-viz gallery OUT_DIR [--frames 120] [--size 480] [--fps 20]
  h4nb-viz serve ROOT [--port 8820] [--export-dir DIR] [--no-browser] [--prometheus URL] [--grafana URL]
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from .fake import write_fake_run
from .gallery import make_gallery
from .server import serve
from .thin import thin_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="h4nb-viz", description="Show h4nb_run results in a local web page.")
    sub = parser.add_subparsers(dest="command", required=True)

    fake = sub.add_parser("fake", help="Write a fake run for testing. It needs no GPU.")
    fake.add_argument("out_dir", help="Directory of the new run.")
    fake.add_argument("--n", type=int, default=20000, help="Number of particles, the central body included.")
    fake.add_argument("--snaps", type=int, default=60, help="Number of numbered snapshots.")
    fake.add_argument("--t-end", type=float, default=6.3125, help="End time of the run.")

    thin = sub.add_parser("thin", help="Write a thinned copy of a run, for a light file to view.")
    thin.add_argument("run_dir", help="Run directory to thin.")
    thin.add_argument("out_dir", help="Directory of the thinned run.")
    thin.add_argument("--max-points", type=int, default=200000, help="Most particles per snapshot. Default: 200000.")
    thin.add_argument("--seed", type=int, default=1, help="Seed of the particle subset. Default: 1.")

    gal = sub.add_parser("gallery", help="Write the README preview GIFs. Kepler motion, not an h4nb run.")
    gal.add_argument("out_dir", help="Directory of the GIF files.")
    gal.add_argument("--frames", type=int, default=180, help="Frames in each GIF. Default: 180.")
    gal.add_argument("--size", type=int, default=480, help="Width and height in pixels. Default: 480.")
    gal.add_argument("--fps", type=int, default=15, help="Frames per second. Default: 15.")

    srv = sub.add_parser("serve", help="Serve the runs under ROOT on 127.0.0.1.")
    srv.add_argument("root", help="Directory that holds the run directories.")
    srv.add_argument("--port", type=int, default=8820, help="TCP port. Default: 8820.")
    srv.add_argument("--export-dir", default=None, help="Directory for exported media. Default: ~/h4nb-viz-exports.")
    srv.add_argument("--no-browser", action="store_true", help="Do not open the browser.")
    srv.add_argument("--prometheus", default=None, metavar="URL", help="Prometheus URL, for example http://127.0.0.1:9090.")
    srv.add_argument("--grafana", default=None, metavar="URL", help="Grafana URL. The page shows a link to it.")
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
    if args.command == "thin":
        if not os.path.isdir(args.run_dir):
            parser.error("RUN_DIR is not a directory: %s" % args.run_dir)
        written = thin_run(args.run_dir, args.out_dir, max_points=args.max_points, seed=args.seed)
        print("h4nb-viz: wrote %d thin snapshots to %s" % (len(written), os.path.abspath(args.out_dir)))
        return 0
    if args.command == "gallery":
        try:
            paths = make_gallery(args.out_dir, frames=args.frames, size=args.size, fps=args.fps)
        except RuntimeError as err:
            parser.error(str(err))
        print("h4nb-viz: wrote %d GIF files to %s" % (len(paths), os.path.abspath(args.out_dir)))
        return 0
    if not os.path.isdir(args.root):
        parser.error("ROOT is not a directory: %s" % args.root)
    serve(args.root, port=args.port, export_dir=args.export_dir, open_browser=not args.no_browser,
          prometheus=args.prometheus, grafana_url=args.grafana)
    return 0


if __name__ == "__main__":
    sys.exit(main())
