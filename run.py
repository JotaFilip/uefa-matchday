#!/usr/bin/env python3
"""Run the full pipeline: fetch fixtures, fetch badges, build the pages.

Usage:
    python3 run.py                     # all competitions, auto-detect season
    python3 run.py --season 2026       # explicit season (start year)
    python3 run.py --competition europa
    python3 run.py --image             # also render shareable PNGs
    python3 run.py --update            # quick refresh of recent scores

Runs in order:
    1. code/fetch_fixtures.py  — ESPN fixtures -> local cache
    2. code/fetch_logos.py     — club badges -> logos/
    3. code/build_standings.py — cache + badges -> HTML (+ PNG with --image)
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CODE = ROOT / "code"


def run(script: str, extra: list[str]) -> None:
    cmd = [sys.executable, str(CODE / script), *extra]
    print(f"\n=== {' '.join(cmd)} ===")
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--competition", default=None,
                    help="UEFA competition (champions/europa/conference)")
    ap.add_argument("--season", default=None, help="Season start year, e.g. 2026")
    ap.add_argument("--league-only", action="store_true",
                    help="Skip the knockout bracket page")
    ap.add_argument("--image", action="store_true",
                    help="Also render the HTML pages to PNG")
    ap.add_argument("--no-cache", action="store_true",
                    help="Re-fetch every day (replace all fixtures)")
    ap.add_argument("--update", action="store_true",
                    help="Re-fetch only days with unfinished matches")
    args = ap.parse_args()

    common = []
    if args.competition:
        common.append(f"--competition={args.competition}")
    if args.season:
        common.append(f"--season={args.season}")
    if args.league_only:
        common.append("--league-only")

    fetch_args = common
    if args.no_cache:
        fetch_args.append("--no-cache")
    if args.update:
        fetch_args.append("--update")
    run("fetch_fixtures.py", fetch_args)

    run("fetch_logos.py", common)

    build_args = list(common)
    if args.image:
        build_args.append("--image")
    run("build_standings.py", build_args)


if __name__ == "__main__":
    main()
