#!/usr/bin/env python3
"""Download club badges for the current UEFA competition teams from
football-logos.cc.

Steps:
    1. Fetch the competition tournament page (lists all current teams with
       64x64 logo URLs).
    2. Match site team names to the ESPN team names found in the fixtures cache.
    3. Download each badge to logos/{slug}.png (the asset CDN requires an
       Origin: https://football-logos.cc header).
    4. Merge into the shared logos/team_logos.json:
       {ESPN team name: "logos/{slug}.png"}.

Teams that cannot be matched fall back to ESPN's own logo CDN.

Usage:
    python3 fetch_logos.py                     # all competitions
    python3 fetch_logos.py --competition europa
    python3 fetch_logos.py --season 2025       # badges for a past season

Credit: logos from https://football-logos.cc (credit required by the site).
"""

import argparse
import html as html_mod
import json
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

from fetch_fixtures import default_season

ROOT = Path(__file__).parent
COMPETITIONS = {
    "champions": {"page": "uefa-champions-league",
                  "heading": "All UEFA Champions League Teams"},
    "europa": {"page": "uefa-europa-league",
               "heading": "All UEFA Europa League Teams"},
    "conference": {"page": "uefa-conference-league",
                   "heading": "All UEFA Conference League Teams"},
}
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PAGE_HEADERS = {"User-Agent": UA, "Accept": "text/html"}
ASSET_HEADERS = {
    "User-Agent": UA,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Referer": "https://football-logos.cc/",
    "Origin": "https://football-logos.cc",
}

# Normalized site-name -> normalized ESPN-name (cases where fuzzy match fails)
ALIASES = {
    "psg": "paris saint germain",
    "bayern munchen": "bayern munich",
    "slavia praha": "slavia prague",
    "sparta praha": "sparta prague",
    "rennes": "rennais",
    "saint gilloise": "st gilloise",
    "n e c": "nec",
    "omonoia": "omonia",
    "ofi": "ofi crete",
    "copenhagen": "kobenhavn",
    "hearts": "heart of midlothian",
    "inter escaldes": "inter d escaldes",
    "universitatea craiova": "csu craiova",
    "crvena zvezda": "red star belgrade",
}


# Letters NFKD does not decompose (Nordic/German/Polish)
TRANSLIT = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae",
                          "å": "a", "Å": "a", "ß": "ss",
                          "ł": "l", "Ł": "l", "đ": "d", "Đ": "d"})


def normalize(name: str) -> str:
    s = name.translate(TRANSLIT)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("&", " ").replace("/", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch(url: str, headers: dict) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def site_teams(comp: str) -> list[dict]:
    """Parse the 'All ... Teams' section of the competition page."""
    cfg = COMPETITIONS[comp]
    html = fetch(f"https://football-logos.cc/tournaments/{cfg['page']}/",
                 PAGE_HEADERS).decode("utf-8", "replace")
    i = html.find(cfg["heading"])
    if i < 0:
        sys.exit("Teams section not found on tournament page.")
    section = html[i:html.find("<h2 ", i)]
    teams = []
    for m in re.finditer(r'<a href="/([a-z-]+)/([a-z0-9-]+)/"[^>]*>(.*?)</a>',
                         section, re.S):
        country, slug, block = m.groups()
        asset = re.search(r"url\((https://assets\.football-logos\.cc/logos/[^)]+)\)", block)
        name_m = re.findall(r"<span[^>]*>([^<]+)</span>", block)
        if asset and name_m:
            teams.append({"name": html_mod.unescape(name_m[-1].strip()),
                          "country": country, "slug": slug, "asset": asset.group(1)})
    return teams


def espn_teams(cache_dir: Path) -> dict[str, str]:
    """ESPN displayName -> ESPN logo URL, from the fixtures cache."""
    urls: dict[str, str] = {}
    for fn in cache_dir.glob("espn_*.json"):
        data = json.loads(fn.read_text(encoding="utf-8"))
        for e in data.get("events", []):
            for c in (e.get("competitions") or [{}])[0].get("competitors", []):
                t = c.get("team") or {}
                if t.get("displayName") and t.get("logo"):
                    urls[t["displayName"]] = t["logo"]
    return urls


def match_team(site_name: str, espn_norms: dict[str, str]) -> str | None:
    """Return ESPN displayName for a site team name, or None."""
    n = normalize(site_name)
    # word-boundary replace: "ofi" must not fire inside "sOFIa"
    for k, v in ALIASES.items():
        n = re.sub(rf"\b{re.escape(k)}\b", v, n)
    for espn, en in espn_norms.items():
        if n == en:
            return espn
    for espn, en in espn_norms.items():
        a, b = sorted([n, en], key=len)
        if len(a) >= 4 and a in b:
            return espn
    return None


def download(url: str, dest: Path, headers: dict) -> bool:
    try:
        data = fetch(url, headers)
        if len(data) < 500:
            print(f"  ! tiny response ({len(data)}b) for {url}: {data[:120]!r}")
            return False
        dest.write_bytes(data)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ! download failed {url}: {e!r}")
        return False


def process(comp: str, season: str) -> None:
    """Download badges and merge into the shared team_logos.json."""
    logo_dir = ROOT / "logos"
    cache_dir = ROOT / "cache" / f"{comp}-{season}"
    logo_dir.mkdir(parents=True, exist_ok=True)
    print(f"Fetching {comp} team list from football-logos.cc ...")
    teams = site_teams(comp)
    print(f"Found {len(teams)} teams on site")
    if not teams:
        sys.exit("No teams parsed.")

    espn = espn_teams(cache_dir)
    if not espn:
        sys.exit("No ESPN teams in cache — run fetch_fixtures.py first.")
    espn_norms = {name: normalize(name) for name in espn}

    mapping: dict[str, str] = {}
    used: set[str] = set()
    for t in teams:
        espn_name = match_team(t["name"], {k: v for k, v in espn_norms.items() if k not in used})
        if not espn_name:
            print(f"  ? no ESPN match for site team {t['name']!r}")
            continue
        used.add(espn_name)
        dest = logo_dir / f"{t['slug']}.png"
        if not dest.exists() and not download(t["asset"], dest, ASSET_HEADERS):
            print(f"  ! logo download failed for {t['name']}")
            continue
        mapping[espn_name] = f"logos/{t['slug']}.png"
        print(f"  ok  {espn_name:25} <- {t['slug']}.png")
        time.sleep(0.1)

    # Fallback: ESPN logo CDN for teams the site list didn't cover
    espn_dir = logo_dir / "espn"
    espn_dir.mkdir(parents=True, exist_ok=True)
    for espn_name, url in espn.items():
        if espn_name in mapping:
            continue
        tid = url.rstrip("/").rsplit("/", 1)[-1].split(".")[0]
        dest = espn_dir / f"espn_{tid}.png"
        if not dest.exists() and download(url, dest, {"User-Agent": UA}):
            mapping[espn_name] = f"logos/espn/espn_{tid}.png"
            print(f"  ok  {espn_name:25} <- espn/espn_{tid}.png (ESPN fallback)")

    out = logo_dir / "team_logos.json"
    existing = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    mapping = {**existing, **mapping}
    # An ESPN fallback must not downgrade a badge the site already provided
    for name, path in mapping.items():
        if "espn_" in path and "espn_" not in existing.get(name, ""):
            mapping[name] = existing[name]
    out.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")
    missing = [n for n in espn if n not in mapping]
    got = sum(1 for n in espn if n in mapping)
    print(f"\nDone: {got}/{len(espn)} teams ({len(mapping)} total) -> {out}")
    if missing:
        print(f"Missing: {missing}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--competition", choices=["all", *sorted(COMPETITIONS)], default="all",
                    help="UEFA competition, or all of them (default: all)")
    ap.add_argument("--season", default=None,
                    help="Season start year to pull ESPN team names from (default: auto-detect)")
    args = ap.parse_args()
    season = args.season or default_season()
    comps = sorted(COMPETITIONS) if args.competition == "all" else [args.competition]
    for comp in comps:
        process(comp, season)


if __name__ == "__main__":
    main()
