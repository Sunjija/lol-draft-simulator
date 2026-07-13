#!/usr/bin/env python3
"""Probe public LoL meta sources without touching app data files.

This is a low-request sandbox tool. It checks whether OP.GG champion statistics
and GOL.GG tournament picks/bans can be fetched and parsed into a small summary.
Outputs are written only under .cache/ by default.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


USER_AGENT = "lol-draft-simulator-meta-probe/0.1 (+https://sunjija.github.io/lol-draft-simulator/)"
DEFAULT_OUTPUT = Path(".cache/meta-source-probe/summary.json")
DEFAULT_RAW_DIR = Path(".cache/meta-source-probe/raw")
OPGG_BASE_URL = "https://op.gg/lol/statistics/champions"
GOL_PICKS_BANS_URL = "https://gol.gg/tournament/tournament-picksandbans/MSI%202026/"
GOL_STATS_URL = "https://gol.gg/tournament/tournament-stats/MSI%202026/"
GOL_PICKS_OF_WEEK_URL = "https://gol.gg/champion/picks-of-the-week/selectdate-LAST/tournament-ALL/"
DEFAULT_GOL_TOURNAMENT_PATTERNS = (
    "MSI,LCK,First Stand,Worlds,World Championship,Season World Championship,"
    "LCK Cup,LCK Road to MSI"
)


class ProbeError(RuntimeError):
    pass


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def save_raw(raw_dir: Path, name: str, text: str) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / name).write_text(text, encoding="utf-8")


def parse_opgg_champions(html: str) -> list[dict[str, Any]]:
    # OP.GG's app-router HTML embeds escaped RSC chunks. The champion stat rows
    # are still readable after unescaping the JSON quotes.
    decoded = html.replace('\\"', '"')
    pattern = re.compile(
        r'\{"champion":\{"image_url":"(?P<image>[^"]+)",'
        r'"name":"(?P<name>[^"]+)","key":"(?P<key>[^"]+)"\},'
        r'"play":(?P<play>\d+),"kda":(?P<kda>[\d.]+),.*?'
        r'"win_rate":(?P<win_rate>[\d.]+),'
        r'"pick_rate":(?P<pick_rate>[\d.]+),'
        r'"ban_rate":(?P<ban_rate>[\d.]+)',
        re.DOTALL,
    )

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for match in pattern.finditer(decoded):
        key = match.group("key")
        play = int(match.group("play"))
        dedupe_key = (key, play)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append(
            {
                "key": key,
                "name": match.group("name"),
                "image": match.group("image"),
                "play": play,
                "winRate": round(float(match.group("win_rate")), 2),
                "pickRate": round(float(match.group("pick_rate")), 2),
                "banRate": round(float(match.group("ban_rate")), 2),
            }
        )
    if not rows:
        raise ProbeError("Could not parse OP.GG champion rows.")
    return rows


def parse_gol_picks_bans(html: str) -> list[dict[str, Any]]:
    start = html.find("Champion list")
    if start < 0:
        raise ProbeError("Could not find GOL.GG champion list.")
    chunk = html[start:]
    pattern = re.compile(
        r"champions_icon/([^'\"]+)\.png['\"][^>]*>\s*<span>\s*"
        r"Bans\s*:\s*(\d+)\s*<br/>\s*"
        r"Picks\s*:\s*(\d+)\s*<br\s*/>\s*"
        r"Winrate\s*:\s*([\d.]+)%",
        re.IGNORECASE,
    )
    rows = [
        {
            "champion": match.group(1),
            "bans": int(match.group(2)),
            "picks": int(match.group(3)),
            "winRate": float(match.group(4)),
            "presence": int(match.group(2)) + int(match.group(3)),
        }
        for match in pattern.finditer(chunk)
    ]
    if not rows:
        raise ProbeError("Could not parse GOL.GG picks/bans rows.")
    return rows


def parse_gol_stats(html: str) -> dict[str, Any]:
    games_match = re.search(r"Number of games:\s*</td>\s*<td[^>]*>\s*(\d+)", html, re.IGNORECASE)
    duration_match = re.search(
        r"Average game duration:\s*</td>\s*<td[^>]*>\s*([0-9:]+)",
        html,
        re.IGNORECASE,
    )
    if not games_match:
        text_match = re.search(r"Number of games:\s*(\d+)", html, re.IGNORECASE)
        games = int(text_match.group(1)) if text_match else None
    else:
        games = int(games_match.group(1))
    return {
        "games": games,
        "averageGameDuration": duration_match.group(1) if duration_match else None,
    }


def parse_gol_weekly_tournaments(html_text: str) -> list[dict[str, Any]]:
    table_index = html_text.find("<th style=\"width:40%\">Tournament</th>")
    if table_index < 0:
        raise ProbeError("Could not find GOL.GG weekly tournament table.")
    table_html = html_text[table_index:]
    row_pattern = re.compile(
        r"<tr><td><a class='white_link' href='(?P<href>[^']+)'>"
        r"(?P<name>.*?)</a></td><td class='text-center'>(?P<games>\d+)</td>"
        r"<td class='text-center'>(?P<patch>[^<]+)</td></tr>",
        re.DOTALL,
    )
    rows: list[dict[str, Any]] = []
    for match in row_pattern.finditer(table_html):
        name = html.unescape(re.sub(r"\s+", " ", match.group("name")).strip())
        href = match.group("href").lstrip()
        while href.startswith("../"):
            href = href[3:]
        stats_url = urllib.parse.urljoin("https://gol.gg/", href)
        picks_bans_url = stats_url.replace("/tournament-stats/", "/tournament-picksandbans/")
        rows.append(
            {
                "name": name,
                "games": int(match.group("games")),
                "patch": match.group("patch").strip(),
                "statsUrl": stats_url,
                "picksBansUrl": picks_bans_url,
            }
        )
    if not rows:
        raise ProbeError("Could not parse GOL.GG weekly tournament rows.")
    return rows


def tournament_matches_patterns(name: str, patterns: list[str]) -> bool:
    normalized = name.casefold()
    return any(pattern.casefold() in normalized for pattern in patterns)


def select_latest_tournaments(
    tournaments: list[dict[str, Any]],
    *,
    patterns: list[str],
    min_games: int,
    limit: int,
) -> list[dict[str, Any]]:
    filtered = [
        tournament
        for tournament in tournaments
        if tournament["games"] >= min_games and tournament_matches_patterns(tournament["name"], patterns)
    ]
    filtered.sort(key=lambda row: (row["games"], row["name"]), reverse=True)
    return filtered[:limit]


def opgg_url(position: str, region: str, tier: str) -> str:
    return f"{OPGG_BASE_URL}?region={region}&tier={tier}&position={position}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--region", default="kr")
    parser.add_argument("--tier", default="emerald_plus")
    parser.add_argument("--positions", default="top,jungle")
    parser.add_argument("--gol-latest", action="store_true", help="Discover recent GOL.GG tournaments from picks of the week.")
    parser.add_argument("--gol-patterns", default=DEFAULT_GOL_TOURNAMENT_PATTERNS)
    parser.add_argument("--gol-min-games", type=int, default=6)
    parser.add_argument("--gol-limit", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--save-raw", action="store_true")
    args = parser.parse_args()

    positions = [position.strip() for position in args.positions.split(",") if position.strip()]
    summary: dict[str, Any] = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "probe_only",
        "writesAppData": False,
        "sources": {},
    }

    opgg_summary: dict[str, Any] = {
        "source": "OP.GG champion statistics",
        "region": args.region,
        "tier": args.tier,
        "positions": {},
    }
    for index, position in enumerate(positions):
        if index:
            time.sleep(args.delay)
        url = opgg_url(position, args.region, args.tier)
        html = fetch_text(url)
        if args.save_raw:
            save_raw(args.raw_dir, f"opgg_{position}.html", html)
        rows = parse_opgg_champions(html)
        opgg_summary["positions"][position] = {
            "url": url,
            "rowCount": len(rows),
            "topByPickRate": sorted(rows, key=lambda row: row["pickRate"], reverse=True)[:8],
            "topByPresence": sorted(rows, key=lambda row: row["pickRate"] + row["banRate"], reverse=True)[:8],
        }

    time.sleep(args.delay)
    discovered_tournaments: list[dict[str, Any]] = []
    selected_tournaments: list[dict[str, Any]] = []
    if args.gol_latest:
        gol_weekly_html = fetch_text(GOL_PICKS_OF_WEEK_URL)
        if args.save_raw:
            save_raw(args.raw_dir, "gol_picks_of_week.html", gol_weekly_html)
        discovered_tournaments = parse_gol_weekly_tournaments(gol_weekly_html)
        patterns = [pattern.strip() for pattern in args.gol_patterns.split(",") if pattern.strip()]
        selected_tournaments = select_latest_tournaments(
            discovered_tournaments,
            patterns=patterns,
            min_games=args.gol_min_games,
            limit=args.gol_limit,
        )
    if not selected_tournaments:
        selected_tournaments = [
            {
                "name": "MSI 2026",
                "games": None,
                "patch": None,
                "statsUrl": GOL_STATS_URL,
                "picksBansUrl": GOL_PICKS_BANS_URL,
            }
        ]

    tournament_summaries: list[dict[str, Any]] = []
    for index, tournament in enumerate(selected_tournaments):
        if index:
            time.sleep(args.delay)
        gol_picks_html = fetch_text(tournament["picksBansUrl"])
        if args.save_raw:
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", tournament["name"]).strip("_").lower()
            save_raw(args.raw_dir, f"gol_{safe_name}_picks_bans.html", gol_picks_html)
        gol_rows = parse_gol_picks_bans(gol_picks_html)

        time.sleep(args.delay)
        gol_stats_html = fetch_text(tournament["statsUrl"])
        if args.save_raw:
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", tournament["name"]).strip("_").lower()
            save_raw(args.raw_dir, f"gol_{safe_name}_stats.html", gol_stats_html)
        tournament_summaries.append(
            {
                "name": tournament["name"],
                "weeklyGames": tournament["games"],
                "weeklyPatch": tournament["patch"],
                "picksBansUrl": tournament["picksBansUrl"],
                "statsUrl": tournament["statsUrl"],
                "tournament": parse_gol_stats(gol_stats_html),
                "rowCount": len(gol_rows),
                "topByPresence": sorted(gol_rows, key=lambda row: row["presence"], reverse=True)[:12],
                "topByPicks": sorted(gol_rows, key=lambda row: row["picks"], reverse=True)[:12],
            }
        )

    summary["sources"]["opgg"] = opgg_summary
    summary["sources"]["golgg"] = {
        "source": "GOL.GG tournament picks/bans",
        "latestDiscoveryUrl": GOL_PICKS_OF_WEEK_URL if args.gol_latest else None,
        "discovered": discovered_tournaments,
        "selected": selected_tournaments,
        "tournaments": tournament_summaries,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote probe summary: {args.out}")
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
