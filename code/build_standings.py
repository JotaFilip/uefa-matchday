#!/usr/bin/env python3
"""Build the UEFA standings pages (team x matchday matrix + knockout bracket)
as styled HTML from the cached ESPN fixtures and the club badge mapping.

Usage:
    python3 build_standings.py                  # all competitions, auto-detect season
    python3 build_standings.py --competition europa
    python3 build_standings.py --season 2026    # explicit season (start year)
    python3 build_standings.py --out standings/custom  # custom output base path
    python3 build_standings.py --league-only    # skip the knockout bracket page
    python3 build_standings.py --image          # also save shareable PNG

Reads the fixtures cache written by fetch_fixtures.py
(./fixtures/<competition>-<season>/) and the badge mapping written by
fetch_logos.py (./logos/team_logos.json) — run those first.

Output (two files per competition in standings/<season>/, e.g.
    standings/2026/champions_league_2026.html and
    standings/2026/champions_knockout_2026.html):
    - League phase matrix: one row per team, one column per matchday.
      Cells: `vs X` = home, `@ X` = away, number = final score (row team first).
      Matchday dates, result tints (win/draw/loss).
    - Knockout rounds (playoffs, R16, QF, SF, final) as a sideways bracket tree.

No third-party dependencies (stdlib only; playwright for --image).
"""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
COMPETITIONS = {
    "champions": {"title": "UEFA Champions League", "out": "champions"},
    "europa": {"title": "UEFA Europa League", "out": "europa"},
    "conference": {"title": "UEFA Conference League", "out": "conference"},
}


def default_season() -> str:
    """UCL season runs Aug(year) -> May(year+1); keyed by start year."""
    now = datetime.now()
    return str(now.year if now.month >= 8 else now.year - 1)


def parse_events(data: dict | None):
    if not data:
        return
    for e in data.get("events", []):
        comp = (e.get("competitions") or [{}])[0]
        competitors = comp.get("competitors") or []
        if len(competitors) != 2:
            continue
        home = next(c for c in competitors if c.get("homeAway") == "home")
        away = next(c for c in competitors if c.get("homeAway") == "away")
        status = (comp.get("status") or {}).get("type") or {}
        # altGameNote looks like "UEFA Champions League, League Phase"
        stage = (comp.get("altGameNote") or "").split(",")[-1].strip()
        if not stage:
            season_obj = e.get("season")
            slug = str(season_obj.get("slug", "")) if isinstance(season_obj, dict) else ""
            stage = "League Phase" if "league" in slug else "Knockout"
        winner = next((c.get("team", {}).get("displayName")
                       for c in competitors if c.get("winner")), None)
        yield {
            "date": e.get("date", "")[:10],
            "home": (home.get("team") or {}).get("displayName", "?"),
            "away": (away.get("team") or {}).get("displayName", "?"),
            "home_score": home.get("score"),
            "away_score": away.get("score"),
            "home_pens": home.get("shootoutScore"),
            "away_pens": away.get("shootoutScore"),
            "completed": bool(status.get("completed")),
            "status": status.get("shortDetail", ""),
            "stage": stage,
            "winner": winner,
        }


def load_fixtures(cache_dir: Path) -> list[dict]:
    """Parse every cached day's events into fixture dicts."""
    fixtures = []
    for f in sorted(cache_dir.glob("espn_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fixtures.extend(parse_events(data))
    return fixtures


def cluster_matchdays(fixtures: list[dict]) -> list[list[dict]]:
    """Group league-phase fixtures into matchdays: dates within 2 days of
    each other belong to the same matchday (some MDs span Tue+Wed)."""
    by_date: dict[str, list[dict]] = {}
    for f in fixtures:
        by_date.setdefault(f["date"], []).append(f)
    dates = sorted(by_date)
    clusters: list[list[str]] = []
    for d in dates:
        if clusters:
            prev = max(clusters[-1])
            if (date.fromisoformat(d) - date.fromisoformat(prev)).days <= 2:
                clusters[-1].append(d)
                continue
        clusters.append([d])
    return [[f for d in cl for f in by_date[d]] for cl in clusters]


def build_matrix(league_fixtures: list[dict]):
    """cells: {opp: name, home: bool, score: 'a-b' (row team first) or None}"""
    clusters = cluster_matchdays(league_fixtures)
    teams: dict[str, dict[int, dict]] = {}
    md_dates: dict[int, str] = {}
    for idx, cluster in enumerate(clusters, 1):
        md_dates[idx] = min(f["date"] for f in cluster)
        for f in cluster:
            score = None
            if f["completed"] and f["home_score"] is not None and f["away_score"] is not None:
                score = (f"{f['home_score']}-{f['away_score']}",
                         f"{f['away_score']}-{f['home_score']}")
            teams.setdefault(f["home"], {})[idx] = {
                "opp": f["away"], "home": True, "score": score[0] if score else None}
            teams.setdefault(f["away"], {})[idx] = {
                "opp": f["home"], "home": False, "score": score[1] if score else None}
    return teams, list(range(1, len(clusters) + 1)), md_dates


def md_escape(text: str) -> str:
    return text.replace("|", "\\|")


def badge(name: str, logo_map: dict, size: int, prefix: str = "") -> str:
    """Club badge image if mapped, plain name otherwise.

    prefix makes the root-relative logo path relative to the HTML file.
    """
    path = logo_map.get(name)
    if path:
        src = f"{prefix}/{path}" if prefix else path
        return f'<img src="{src}" width="{size}" alt="{md_escape(name)}" title="{md_escape(name)}">'
    return md_escape(name)


def cell_html(cell: dict, logo_map: dict, prefix: str = "") -> str:
    pre = "vs " if cell["home"] else "@ "
    score = f" {cell['score']}" if cell["score"] else ""
    return pre + badge(cell["opp"], logo_map, 22, prefix) + score


def _header_lines(season: str, title: str, phase: str) -> list[str]:
    return [f"# {title} {season}/{str(int(season) + 1)[2:]} — {phase}", "",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
            "Source: ESPN public scoreboard API", ""]


def render_league_md(season: str, title: str, teams, mds, md_dates,
                     logo_map: dict, prefix: str = "") -> str:
    """League-phase matrix: one row per team, one column per matchday."""
    lines = _header_lines(season, title, "League Phase")
    lines.append("| Team | Logo | " + " | ".join(
        f"MD {md}<br><small>{md_dates.get(md, '')}</small>" for md in mds) + " |")
    lines.append("| --- " * 2 + "| --- " * len(mds) + "|")
    for team in sorted(teams):
        row = [md_escape(team), badge(team, logo_map, 30, prefix)]
        for md in mds:
            cell = teams[team].get(md)
            row.append(cell_html(cell, logo_map, prefix) if cell else "")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    lines.append("_`vs` = home, `@` = away, number after badge = final score (row team first). "
                 "Cell tint (HTML/PNG): green = win, grey = draw, red = loss. "
                 "Badges: [football-logos.cc](https://football-logos.cc/)._")
    return "\n".join(lines)


STAGE_ORDER = ["Knockout Round Playoffs", "Round of 16", "Quarterfinals",
               "Semifinals", "Final"]


def _tie_agg(legs: list[dict]) -> str | None:
    """Aggregate 'a-b' for a two-leg tie (first leg's home team first)."""
    if len(legs) != 2:
        return None
    try:
        a = int(legs[0]["home_score"]) + int(legs[1]["away_score"])
        b = int(legs[0]["away_score"]) + int(legs[1]["home_score"])
    except (TypeError, ValueError):
        return None
    return f"{a}-{b}"


def _tie_pens(legs: list[dict]) -> str | None:
    """Penalty shootout 'a-b' (first leg's home team first) if a leg went to pens."""
    for leg in legs:
        if leg.get("home_pens") is not None and leg.get("away_pens") is not None:
            hp, ap = leg["home_pens"], leg["away_pens"]
            if leg["home"] == legs[0]["home"]:
                return f"{hp}-{ap}"
            return f"{ap}-{hp}"
    return None


def build_bracket(knockout: list[dict]) -> list[dict]:
    """Group knockout fixtures into ties, one entry per stage (in order).

    A tie is {"legs": [leg, leg?] sorted by date, "winner": name|None,
    "agg": "a-b"|None, "pens": "a-b"|None (penalty shootout)}. The two
    legs of a tie share the same team pair; the final is a single leg.
    Winner = higher aggregate, else the second leg's `winner` flag
    (penalties).
    """
    by_stage: dict[str, list[dict]] = {}
    for f in knockout:
        by_stage.setdefault(f["stage"], []).append(f)
    stages = []
    for stage in STAGE_ORDER:
        fs = by_stage.get(stage)
        if not fs:
            continue
        pairs: dict[frozenset, list[dict]] = {}
        for f in sorted(fs, key=lambda x: x["date"]):
            pairs.setdefault(frozenset((f["home"], f["away"])), []).append(f)
        ties = []
        for legs in pairs.values():
            agg = _tie_agg(legs)
            winner = None
            if agg:
                a, b = map(int, agg.split("-"))
                if a > b:
                    winner = legs[0]["home"]
                elif b > a:
                    winner = legs[0]["away"]
                else:
                    winner = legs[-1].get("winner")
            elif len(legs) == 1 and legs[0]["completed"]:
                winner = legs[0].get("winner")
            ties.append({"legs": legs, "winner": winner, "agg": agg,
                         "pens": _tie_pens(legs)})
        stages.append({"stage": stage, "ties": ties})
    return stages


BRACKET_CSS = """
.bracket{position:relative;margin:16px auto}
.bracket svg{position:absolute;top:0;left:0}
.stage-h{position:absolute;top:0;font-size:13px;font-weight:700;text-align:center}
.tie{position:absolute;width:232px;background:#fff;border:1px solid #ddd;
     border-radius:6px;padding:3px 6px;box-sizing:border-box}
.tie-date{position:relative;font-size:10px;color:#888;text-align:center}
.tie-date .pens-h{position:absolute;right:3px}
.leg{display:flex;align-items:center;gap:4px;font-size:12px;padding:2px 3px}
.leg img{width:18px;height:18px;flex:none}
.leg .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;
          white-space:nowrap}
.leg .sc{width:1.5em;text-align:right;flex:none}
.leg .agg{width:1.5em;text-align:right;font-weight:700;flex:none}
.leg .ps{width:1.5em;text-align:right;color:#888;flex:none}
.leg.win{background:#d8f0d8;font-weight:700;border-radius:3px}
"""


def _fmt_dates(dates: list[str]) -> str:
    ds = sorted({date.fromisoformat(d) for d in dates})
    if len(ds) == 1:
        return ds[0].strftime("%d %b")
    if len(ds) == 2 and ds[0].month == ds[1].month:
        return f"{ds[0].day} & {ds[1].day} {ds[0].strftime('%b')}"
    return " & ".join(d.strftime("%d %b") for d in ds)


def render_knockout_html(season: str, title: str, knockout: list[dict],
                         logo_map: dict, prefix: str = "") -> str:
    """Knockout rounds as a sideways bracket tree, one column per stage."""
    if not knockout:
        md = _header_lines(season, title, "Knockout Phase")
        md.append("_No knockout fixtures published yet — "
                  "they appear after the knockout draw._")
        return render_html("\n".join(md))

    stages = build_bracket(knockout)
    rows = max(len(s["ties"]) for s in stages)
    CARD_W, CARD_H, ROW_H, HEAD, PITCH = 232, 64, 92, 36, 288
    width = 16 + (len(stages) - 1) * PITCH + CARD_W + 16
    height = HEAD + rows * ROW_H + 8

    # Place ties: stage 0 by date order; later stages sorted by the rows of
    # the ties their winners came from, then evenly spaced in equal slots.
    placed: list[list[dict]] = []
    row_of: dict[str, float] = {}  # team name -> row centre of its tie
    for si, st in enumerate(stages):
        ties = st["ties"]
        if si == 0:
            order = list(range(len(ties)))
        else:
            def sort_key(idx):
                teams = {t for leg in ties[idx]["legs"]
                         for t in (leg["home"], leg["away"])}
                known = [row_of[t] for t in teams if t in row_of]
                d = ties[idx]["legs"][0]["date"]
                return (sum(known) / len(known) if known else 99.0, d)
            order = sorted(range(len(ties)), key=sort_key)
        block = rows / len(ties)
        cur = []
        for rank, idx in enumerate(order):
            tie = ties[idx]
            cy = HEAD + (rank * block + block / 2) * ROW_H
            cur.append({"x": 16 + si * PITCH, "cy": cy, "tie": tie})
            if tie["winner"]:
                row_of[tie["winner"]] = rank * block + block / 2
        placed.append(cur)

    # Elbow connectors from each parent tie to the tie its winner fed into
    paths = []
    for si in range(1, len(stages)):
        for p in placed[si]:
            teams = {t for leg in p["tie"]["legs"]
                     for t in (leg["home"], leg["away"])}
            for q in placed[si - 1]:
                if q["tie"]["winner"] in teams:
                    x1, y1 = q["x"] + CARD_W, q["cy"]
                    x2, y2 = p["x"], p["cy"]
                    mid = (x1 + x2) / 2
                    paths.append(f"M{x1:.0f} {y1:.0f} H{mid:.0f} "
                                 f"V{y2:.0f} H{x2:.0f}")
    svg = (f'<svg width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}">'
           f'<g fill="none" stroke="#bbb" stroke-width="1.5">'
           + "".join(f'<path d="{p}"/>' for p in paths) + "</g></svg>")

    headers = "".join(
        f'<div class="stage-h" style="left:{16 + si * PITCH}px;'
        f'width:{CARD_W}px">{st["stage"]}</div>'
        for si, st in enumerate(stages))

    cards = []
    for col in placed:
        for p in col:
            tie = p["tie"]
            legs = tie["legs"]
            teams = [legs[0]["home"], legs[0]["away"]]
            pens_vals = tie["pens"].split("-") if tie.get("pens") else None
            rows_html = []
            for i, team in enumerate(teams):
                cls = "win" if tie["winner"] == team else ""
                scores = "".join(
                    f'<span class="sc">'
                    f'{leg["home_score"] if team == leg["home"] else leg["away_score"] or ""}'
                    "</span>" for leg in legs)
                agg = ""
                if tie["agg"]:
                    a, b = tie["agg"].split("-")
                    agg = f'<span class="agg">{a if team == teams[0] else b}</span>'
                ps = f'<span class="ps">{pens_vals[i]}</span>' if pens_vals else ""
                rows_html.append(
                    f'<div class="leg {cls}">{badge(team, logo_map, 18, prefix)}'
                    f'<span class="nm">{md_escape(team)}</span>{scores}{agg}{ps}</div>')
            pens_h = '<span class="pens-h">p</span>' if pens_vals else ""
            top = p["cy"] - CARD_H / 2
            cards.append(
                f'<div class="tie" style="left:{p["x"]:.0f}px;top:{top:.0f}px">'
                f'<div class="tie-date">{_fmt_dates([l["date"] for l in legs])}{pens_h}</div>'
                + "".join(rows_html) + "</div>")

    h1 = f"{title} {season}/{str(int(season) + 1)[2:]} — Knockout Phase"
    meta = (f'<p class="meta">Generated: '
            f'{datetime.now().strftime("%Y-%m-%d %H:%M")}  '
            "Source: ESPN public scoreboard API</p>")
    legend = ('<p class="legend">Winner of each tie in bold (green). '
              "Numbers = leg scores (left to right), bold number = aggregate. "
              "<code>p</code> = tie decided on penalties; grey number = shootout score. "
              'Badges: <a href="https://football-logos.cc/">football-logos.cc</a>.</p>')
    return ('<!doctype html>\n<meta charset="utf-8">\n'
            f"<title>{h1}</title>\n"
            f"<style>{HTML_CSS}{BRACKET_CSS}</style>\n"
            f"<h1>{h1}</h1>\n{meta}\n"
            f'<div class="bracket" style="width:{width}px;height:{height}px">'
            f"{svg}{headers}{''.join(cards)}</div>\n{legend}\n")


HTML_CSS = """
body{font:14px/1.5 system-ui,-apple-system,sans-serif;margin:24px auto;max-width:1100px;
     padding:0 16px;color:#1a1a1a}
h1{font-size:22px} h2{font-size:18px;margin-top:28px} h3{font-size:15px;margin-top:18px}
.meta,.legend{color:#666;font-size:13px}
table{border-collapse:collapse}
td,th{border:1px solid #ddd;padding:4px 8px;text-align:center;white-space:nowrap}
td:first-child,th:first-child{text-align:left}
th small{display:block;font-weight:400;color:#666;font-size:11px}
td.win{background:#d8f0d8}
td.draw{background:#e9e9e9}
td.loss{background:#f8d7d7}
img{vertical-align:middle}
ul{padding-left:20px} li{margin:2px 0}
"""


def _score_cls(cell_text: str) -> str:
    """win/draw/loss tint class from a cell's trailing score (row team first)."""
    m = re.search(r"(\d+)-(\d+)$", cell_text)
    if not m:
        return ""
    a, b = int(m.group(1)), int(m.group(2))
    if a > b:
        return ' class="win"'
    if a < b:
        return ' class="loss"'
    return ' class="draw"'


def render_html(md: str) -> str:
    """Render the generated markdown as a standalone styled HTML page.

    Cell/list content already contains raw HTML (badges, <br>, <small>)
    from the markdown renderer, so it is passed through unescaped.
    """
    parts: list[str] = []
    in_table = in_list = first_row = False

    def close_blocks():
        nonlocal in_table, in_list
        if in_table:
            parts.append("</table>")
            in_table = False
        if in_list:
            parts.append("</ul>")
            in_list = False

    for raw in md.splitlines():
        line = raw.rstrip()
        if not line:
            close_blocks()
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):  # separator row
                continue
            if not in_table:
                parts.append("<table>")
                in_table = True
                first_row = True
            tag = "th" if first_row else "td"
            first_row = False
            parts.append("<tr>" + "".join(
                f"<{tag}{_score_cls(c) if tag == 'td' else ''}>{c}</{tag}>"
                for c in cells) + "</tr>")
        elif line.startswith("### "):
            close_blocks()
            parts.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            close_blocks()
            parts.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            close_blocks()
            parts.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("- "):
            if not in_list:
                close_blocks()
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{line[2:]}</li>")
        else:
            close_blocks()
            text, cls = line, ' class="meta"'
            if text.startswith("_") and text.endswith("_"):
                text, cls = text[1:-1], ' class="legend"'
            text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
            text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
            parts.append(f"<p{cls}>{text}</p>")
    close_blocks()
    m = re.search(r"^# (.+)$", md, re.M)
    title = m.group(1) if m else "Fixtures Matrix"
    return ('<!doctype html>\n<meta charset="utf-8">\n'
            f"<title>{title}</title>\n"
            f"<style>{HTML_CSS}</style>\n" + "\n".join(parts) + "\n")


def render_image(html_path: Path, png_path: Path) -> None:
    """Screenshot the HTML preview to a shareable full-page PNG (2x)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright not installed. Run: python3 -m pip install playwright")
    html_path = Path(html_path).resolve()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome")  # system Chrome
        except Exception:
            browser = p.chromium.launch()  # fallback: playwright's chromium
        page = browser.new_page(viewport={"width": 1400, "height": 900},
                                device_scale_factor=2)
        page.goto(html_path.as_uri())
        page.wait_for_load_state("networkidle")
        # Drop body centering/max-width so the fit math sees the true edges
        page.add_style_tag(content="body{margin:0;max-width:none}")
        # Fit viewport to the table itself -> no white side bars
        w, h = page.evaluate(
            "() => { const r = document.body.getBoundingClientRect();"
            " const cs = getComputedStyle(document.body);"
            " const pad = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);"
            " const els = [...document.querySelectorAll('table, .bracket')];"
            " const tw = els.length"
            "   ? Math.max(...els.map(t => t.getBoundingClientRect().width))"
            "   : r.width - pad;"
            " return [Math.ceil(tw + pad), Math.ceil(r.height)]; }")
        page.set_viewport_size({"width": w, "height": h})
        page.screenshot(path=str(png_path), full_page=True)
        browser.close()


def process(competition: str, season: str, args) -> None:
    """Build one competition's standings pages from the fixtures cache."""
    cfg = COMPETITIONS[competition]
    print(f"Building {cfg['title']} standings for season {season} ...")
    cache_dir = ROOT / "fixtures" / f"{competition}-{season}"
    fixtures = load_fixtures(cache_dir)
    if not fixtures:
        sys.exit(f"No {cfg['title']} fixtures in {cache_dir} — "
                 "run fetch_fixtures.py first.")

    league = [f for f in fixtures if "League" in f["stage"]]
    knockout = [f for f in fixtures if "League" not in f["stage"]]
    teams, mds, md_dates = build_matrix(league)
    print(f"Found {len(fixtures)} matches: {len(league)} league phase, {len(knockout)} knockout")

    logo_file = ROOT / "logos" / "team_logos.json"
    logo_map = json.loads(logo_file.read_text(encoding="utf-8")) if logo_file.exists() else {}
    if logo_map:
        print(f"Using {len(logo_map)} club badges from {logo_file}")

    base = Path(args.out) if args.out else ROOT / "standings" / str(season) / cfg["out"]
    if base.suffix in (".html", ".md", ".png"):
        base = base.with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)
    prefix = os.path.relpath(ROOT, base.parent).replace(os.sep, "/")
    if prefix in (".", ""):
        prefix = ""
    league_out = base.parent / f"{base.name}_league_{season}.html"
    knockout_out = base.parent / f"{base.name}_knockout_{season}.html"
    league_out.write_text(render_html(
        render_league_md(season, cfg["title"], teams, mds, md_dates, logo_map, prefix)),
        encoding="utf-8")
    pages = [league_out]
    if not args.league_only:
        knockout_out.write_text(render_knockout_html(
            season, cfg["title"], knockout, logo_map, prefix), encoding="utf-8")
        pages.append(knockout_out)
    print(f"Done: {len(teams)} teams, {len(mds)} matchdays -> "
          + ", ".join(p.name for p in pages))
    if args.image:
        for page_out in pages:
            png_out = page_out.with_suffix(".png")
            render_image(page_out, png_out)
            print(f"Image -> {png_out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--competition", choices=["all", *sorted(COMPETITIONS)], default="all",
                    help="UEFA competition, or all of them (default: all)")
    ap.add_argument("--season", default=None, help="Season start year, e.g. 2026 (default: auto-detect)")
    ap.add_argument("--out", default=None,
                    help="Output base path, writes <base>_league_<season>.html and "
                         "<base>_knockout_<season>.html (single competition only)")
    ap.add_argument("--league-only", action="store_true",
                    help="Skip the knockout bracket page")
    ap.add_argument("--image", action="store_true",
                    help="Also render the HTML preview to a PNG image")
    args = ap.parse_args()

    if args.out and args.competition == "all":
        sys.exit("--out requires a single --competition (not 'all')")

    season = args.season or default_season()
    comps = sorted(COMPETITIONS) if args.competition == "all" else [args.competition]
    for comp in comps:
        process(comp, season, args)


if __name__ == "__main__":
    main()
