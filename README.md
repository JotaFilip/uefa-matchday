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

```bash
# All competitions (default), auto-detects the current season
python3 fetch_fixtures.py

# A single competition
python3 fetch_fixtures.py --competition champions
python3 fetch_fixtures.py --competition europa
python3 fetch_fixtures.py --competition conference

# Explicit season (start year)
python3 fetch_fixtures.py --season 2026

# Also write a shareable PNG next to the HTML
python3 fetch_fixtures.py --image

# Options
python3 fetch_fixtures.py --out output/custom    # custom output base path
python3 fetch_fixtures.py --league-only              # skip knockout rounds
python3 fetch_fixtures.py --no-cache                 # re-fetch from ESPN
```

### Updating scores

After a matchday, re-run with `--update` to refresh only the cached days that
still have unfinished matches (e.g. today's games), then rebuild the table.
Days that are fully finished or still in the future are left untouched, so an
update takes well under a second:

```bash
python3 fetch_fixtures.py --update
python3 fetch_fixtures.py --competition europa --update
```

Generated files land in `output/<season>/` (one sub-folder per season, named
after the start year), one file per phase — each also gets a `.png` with
`--image`:

- `output/2026/champions_league_2026.html` + `champions_knockout_2026.html`
- `output/2026/europa_league_2026.html` + `europa_knockout_2026.html`
- `output/2026/conference_league_2026.html` + `conference_knockout_2026.html`

### Refreshing club badges

```bash
python3 fetch_logos.py                          # all competitions
python3 fetch_logos.py --competition champions  # a single competition
python3 fetch_logos.py --season 2025            # badges for a past season
```

Downloads 64×64 badges from football-logos.cc into `logos/` and merges them
into `team_logos.json` (ESPN team name → badge path). The site only lists the
current season's teams, so clubs from past seasons (e.g. `--season 2025`) get
badges from ESPN's logo CDN instead, stored in `logos/espn/`. If a badge is
missing, the fixtures script falls back to ESPN's logos; with no mapping at
all it falls back to plain team names.

## Folder layout

| Path | Contents |
|---|---|
| `fetch_fixtures.py` | Fetches fixtures, builds the matrix, renders HTML/PNG |
| `fetch_logos.py` | Downloads club badges, matches team names |
| `cache/<competition>-<season>/` | Cached ESPN scoreboard responses (`espn_YYYYMMDD.json`) — re-runs are instant |
| `logos/` | Badge PNGs from football-logos.cc (shared across competitions) + `team_logos.json` |
| `logos/espn/` | ESPN fallback badges (`espn_<id>.png`) — created on demand only |
| `output/<season>/` | Generated HTML pages and PNGs, one sub-folder per season |

## Notes

- ESPN exposes one date per request, so the script scans every Tue/Wed/Thu
  (plus the late-May final) from August to mid-June and caches each response.
- Matchday numbers are derived by clustering match dates (dates within 2 days
  count as the same matchday).
- 2026/27 season start is World Cup-delayed: UCL MD1 is 2026-09-08,
  Conference League MD1 is 2026-10-15.
- Knockout rounds: the knockout file stays empty until UEFA schedules them
  (the knockout draw happens after the league phase, which ends in January).
  Once fixtures exist, a re-run or `--update` fills it. The knockout page
  renders a sideways bracket tree — one column per stage (playoffs → R16 →
  QF → SF → final); two-leg ties show both leg scores plus the aggregate,
  and the winner of each tie (bold, green) feeds the next round.
  To see a finished knockout today:
  `python3 fetch_fixtures.py --season 2025 --competition champions`
