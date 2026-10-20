#!/usr/bin/env python3
"""Fetch UEFA Champions/Europa/Conference League fixtures from ESPN's public
API into the local cache.

Usage:
    python3 fetch_fixtures.py                  # all competitions, auto-detect season
    python3 fetch_fixtures.py --competition europa
    python3 fetch_fixtures.py --season 2026    # explicit season (start year)
    python3 fetch_fixtures.py --league-only    # only the league-phase window
    python3 fetch_fixtures.py --no-cache       # re-fetch every day (replace all fixtures)
    python3 fetch_fixtures.py --update         # quick refresh of recent scores

How it works:
    ESPN's scoreboard API only serves one date per request, so the script
    scans every Tue/Wed/Thu (UCL match days) across the season window plus
    late-May/early-June Saturdays (the final). Raw responses are cached in
    ./fixtures/<competition>-<season>/ so re-runs are instant: days with
    matches are cached permanently, and empty PAST days are cached too (a
    past day can never gain matches). Empty FUTURE days are re-checked
    every run until fixtures appear (e.g. knockout dates after the draw).
    --no-cache re-fetches every day (replace all fixtures); --update
    re-fetches only cached days with unfinished matches.

This script only fetches. To get club badges run fetch_logos.py, and to
render the standings HTML/PNG from the cache run build_standings.py.

No API key, no third-party dependencies (stdlib only).
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent
SCOREBOARD_URL = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
                  "{slug}/scoreboard?dates={d}")
COMPETITIONS = {
    "champions": {"espn": "uefa.champions", "title": "UEFA Champions League"},
    "europa": {"espn": "uefa.europa", "title": "UEFA Europa League"},
    "conference": {"espn": "uefa.europa.conf", "title": "UEFA Conference League"},
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


def default_season() -> str:
    """UCL season runs Aug(year) -> May(year+1); keyed by start year."""
    now = datetime.now()
    return str(now.year if now.month >= 8 else now.year - 1)


def season_window(season: str) -> tuple[date, date]:
    start_year = int(season)
    return date(start_year, 8, 1), date(start_year + 1, 6, 15)


def scan_dates(start: date, end: date):
    """UCL games are played Tue/Wed/Thu; the final is a late-May Saturday."""
    d = start
    while d <= end:
        wd = d.weekday()  # Mon=0 .. Sun=6
        is_matchday = wd in (1, 2, 3)  # Tue, Wed, Thu
        is_final_weekend = wd == 5 and d.month in (5, 6)  # Sat, May/Jun
        if is_matchday or is_final_weekend:
            yield d
        d += timedelta(days=1)


def fetch_day(day: date, espn_slug: str, cache_dir: Path, use_cache: bool = True) -> dict | None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"espn_{day.strftime('%Y%m%d')}.json"
    if use_cache and cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if cached.get("events"):
            return cached
        if day <= date.today():
            return cached  # past empty day: stays empty, trust the marker
        cache_file.unlink()  # future day: fixtures may have been published since

    url = SCOREBOARD_URL.format(slug=espn_slug, d=day.strftime("%Y%m%d"))
    req = urllib.request.Request(url, headers=HEADERS)
    last_err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("events"):
                cache_file.write_text(json.dumps(data), encoding="utf-8")
            elif day <= date.today():
                # past day with no matches: cache the empty result so
                # re-runs don't re-fetch it (force a re-fetch: --no-cache)
                cache_file.write_text(json.dumps({"events": []}), encoding="utf-8")
            else:
                cache_file.unlink(missing_ok=True)  # future empty: re-check next run
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                if day <= date.today():
                    cache_file.write_text(json.dumps({"events": []}), encoding="utf-8")
                return None  # no data for this date
            last_err = e
        except Exception as e:  # noqa: BLE001 - network hiccups
            last_err = e
        time.sleep(1.5 * (attempt + 1))
    print(f"  ! failed for {day}: {last_err}", file=sys.stderr)
    return None


def stale_days(cache_dir: Path) -> set[date]:
    """Cached days on/before today that still list unfinished matches.

    Postponed matches don't count — they won't complete on their listed day.
    """
    today = date.today()
    out: set[date] = set()
    for f in cache_dir.glob("espn_*.json"):
        try:
            s = f.stem  # espn_YYYYMMDD
            d = date(int(s[5:9]), int(s[9:11]), int(s[11:13]))
        except ValueError:
            continue
        if d > today:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            out.add(d)
            continue
        for e in data.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            st = (comp.get("status") or {}).get("type") or {}
            if st.get("completed") or "postpon" in st.get("shortDetail", "").lower():
                continue
            out.add(d)
            break
    return out


def fetch_season(season: str, espn_slug: str, cache_dir: Path,
                 use_cache: bool, league_only: bool, update: bool = False) -> int:
    """Fetch every scan day into the cache; return the number of matches."""
    start, end = season_window(season)
    if league_only:
        end = min(end, date(int(season) + 1, 1, 31))
    refresh = stale_days(cache_dir) if update else set()
    if update:
        if refresh:
            print(f"  refreshing {len(refresh)} day(s): "
                  + ", ".join(d.isoformat() for d in sorted(refresh)))
        else:
            print("  all cached days up to date, nothing to refresh")
    matches = 0
    days = list(scan_dates(start, end))
    for i, day in enumerate(days, 1):
        cached = use_cache and (cache_dir / f"espn_{day.strftime('%Y%m%d')}.json").exists()
        data = fetch_day(day, espn_slug, cache_dir,
                         use_cache=use_cache and day not in refresh)
        matches += len(data.get("events", [])) if data else 0
        if i % 20 == 0 or i == len(days):
            print(f"  scanned {i}/{len(days)} days, {matches} matches so far")
        if not cached:
            time.sleep(0.15)
    return matches


def process(competition: str, season: str, args) -> None:
    """Fetch one competition's fixtures into the cache."""
    cfg = COMPETITIONS[competition]
    print(f"{'Updating' if args.update else 'Fetching'} {cfg['title']} fixtures for season {season} ...")
    cache_dir = ROOT / "fixtures" / f"{competition}-{season}"
    matches = fetch_season(season, cfg["espn"], cache_dir,
                           use_cache=not args.no_cache, league_only=args.league_only,
                           update=args.update)
    if matches == 0:
        sys.exit(f"No {cfg['title']} fixtures found. Check network or try an explicit --season.")
    print(f"Done: {matches} matches cached -> {cache_dir.relative_to(ROOT)}/")
    print(f"Next: python3 fetch_logos.py --season {season} "
          f"&& python3 build_standings.py --season {season}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--competition", choices=["all", *sorted(COMPETITIONS)], default="all",
                    help="UEFA competition, or all of them (default: all)")
    ap.add_argument("--season", default=None, help="Season start year, e.g. 2026 (default: auto-detect)")
    ap.add_argument("--league-only", action="store_true",
                    help="Only fetch the league-phase window (Aug -> Jan)")
    ap.add_argument("--no-cache", action="store_true",
                    help="Ignore the cache and re-fetch every day (replace all fixtures)")
    ap.add_argument("--update", action="store_true",
                    help="Re-fetch only cached days whose matches are not all finished")
    args = ap.parse_args()

    season = args.season or default_season()
    comps = sorted(COMPETITIONS) if args.competition == "all" else [args.competition]
    for comp in comps:
        process(comp, season, args)


if __name__ == "__main__":
    main()
