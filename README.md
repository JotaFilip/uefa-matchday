# UEFA Fixtures Matrix

Fetches UEFA Champions League, Europa League and Conference League fixtures from
ESPN's public scoreboard API and renders a team × matchday matrix as a styled
HTML page (optionally a shareable PNG).

- `vs` = home, `@` = away; the number after the badge is the final score (row team first)
- Cell tint: green = win, grey = draw, red = loss (row team's perspective)
- Club badges: [football-logos.cc](https://football-logos.cc/) — credit required per site terms

## Requirements

- Python 3 (stdlib only for fetching and HTML rendering)
- For `--image`: `python3 -m pip install playwright` plus a local Chrome or Chromium

## Usage

Three scripts, one job each: fetch fixtures, fetch badges, build the pages.

```bash
# 1. Fetch fixtures into the local cache (all competitions, auto season)
python3 fetch_fixtures.py

# A single competition / explicit season (start year)
python3 fetch_fixtures.py --competition champions
python3 fetch_fixtures.py --season 2026

# 2. Fetch club badges
python3 fetch_logos.py

# 3. Build the HTML pages (optionally also shareable PNGs)
python3 build_standings.py
python3 build_standings.py --image

# Options
python3 fetch_fixtures.py --no-cache           # re-fetch every day (replace all fixtures)
python3 fetch_fixtures.py --update             # refresh only days with unfinished matches
python3 build_standings.py --out standings/custom  # custom output base path
python3 build_standings.py --league-only       # skip the knockout bracket page
```

### Updating scores

After a matchday, re-run the fetch with `--update` to refresh only the cached
days that still have unfinished matches (e.g. today's games), then rebuild.
Days that are fully finished or still in the future are left untouched, so an
update takes well under a second:

```bash
python3 fetch_fixtures.py --update
python3 build_standings.py
```

Generated files land in `standings/<season>/` (one sub-folder per season,
named after the start year), one file per phase. Only the HTML pages are
committed; with `--image` each also gets a `.png` (gitignored — the daily
job uploads them to the season release instead):

- `standings/2026/champions_league_2026.html` + `champions_knockout_2026.html`
- `standings/2026/europa_league_2026.html` + `europa_knockout_2026.html`
- `standings/2026/conference_league_2026.html` + `conference_knockout_2026.html`

### Shareable links

PNGs are not committed — they're published to a per-season GitHub Release
that is updated daily while the season is live and freezes when it ends:

- [Season 2026 (live)](https://github.com/JotaFilip/uefa-matchday/releases/tag/2026)
- [Season 2025 (final)](https://github.com/JotaFilip/uefa-matchday/releases/tag/2025)

### Refreshing club badges

```bash
python3 fetch_logos.py                          # all competitions
python3 fetch_logos.py --competition champions  # a single competition
python3 fetch_logos.py --season 2025            # badges for a past season
```

Downloads badges from football-logos.cc into `logos/` and merges them into
`team_logos.json` (ESPN team name → badge path). Clubs in the site's
current-season list are matched by name; clubs missing from that list (e.g.
past seasons' smaller clubs) are looked up in the site-wide search index;
anything still unmatched gets a badge from ESPN's logo CDN (`logos/espn/`).
With no mapping at all the fixtures script falls back to plain team names.

## Folder layout

| Path | Contents |
|---|---|
| `fetch_fixtures.py` | Fetches fixtures from ESPN into the local cache |
| `fetch_logos.py` | Downloads club badges, matches team names |
| `build_standings.py` | Builds the matrix + bracket HTML (and optional PNG) from the cache |
| `fixtures/<competition>-<season>/` | Cached ESPN scoreboard responses (`espn_YYYYMMDD.json`) — re-runs are instant |
| `logos/` | Badge PNGs from football-logos.cc (shared across competitions) + `team_logos.json` |
| `logos/espn/` | ESPN fallback badges (`espn_<id>.png`) — created on demand only |
| `standings/<season>/` | Generated HTML pages, one sub-folder per season (PNGs from `--image` are gitignored — published as release assets) |

## Notes

- ESPN exposes one date per request, so the script scans every Tue/Wed/Thu
  (plus the late-May final) from August to mid-June and caches each response.
- Matchday numbers are derived by clustering match dates (dates within 2 days
  count as the same matchday).
- 2026/27 season start is World Cup-delayed: UCL MD1 is 2026-09-08,
  Conference League MD1 is 2026-10-15.
- Knockout rounds: the knockout file stays empty until UEFA schedules them
  (the knockout draw happens after the league phase, which ends in January).
  Once fixtures exist, a re-run of the fetch fills it. The knockout page
  renders a sideways bracket tree — one column per stage (playoffs → R16 →
  QF → SF → final); two-leg ties show both leg scores plus the aggregate,
  and the winner of each tie (bold, green) feeds the next round.
  To see a finished knockout today:
  `python3 fetch_fixtures.py --season 2025 --competition champions`
  then `python3 build_standings.py --season 2025 --competition champions`
