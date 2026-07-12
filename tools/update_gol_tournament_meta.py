#!/usr/bin/env python3
"""Update compact tournament meta data from GOL.GG picks/bans pages."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probe_public_meta_sources import (
    DEFAULT_GOL_TOURNAMENT_PATTERNS,
    GOL_PICKS_BANS_URL,
    GOL_STATS_URL,
    fetch_text,
    parse_gol_picks_bans,
    parse_gol_stats,
    parse_gol_weekly_tournaments,
    select_latest_tournaments,
)


DEFAULT_OUTPUT = Path("data/tournament_meta_2026_compact.js")
DEFAULT_INDEX = Path("index.html")
DEFAULT_EXISTING_META = Path("data/tournament_meta_2026_compact.js")
GOL_PICKS_OF_WEEK_URL = "https://gol.gg/champion/picks-of-the-week/selectdate-LAST/tournament-ALL/"
ROLES = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]
ALIASES = {
    "wukong": "monkeyking",
    "nunu": "nunu",
    "nunuandwillump": "nunu",
    "jarvaniv": "jarvaniv",
    "jarvan4": "jarvaniv",
    "leesin": "leeSin",
    "xinzhao": "xinZhao",
    "drmundo": "drmundo",
    "ksante": "ksante",
    "kaisa": "kaisa",
    "kogmaw": "kogmaw",
    "chogath": "chogath",
    "reksai": "reksai",
    "tahmkench": "tahmkench",
    "twistedfate": "twistedfate",
    "aurelionsol": "aurelionsol",
    "velkoz": "velkoz",
    "belveth": "belveth",
    "khazix": "khazix",
    "renataglasc": "renata",
}


class TournamentMetaUpdateError(RuntimeError):
    pass


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def read_js_assignment(path: Path, prefix: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith(prefix):
        raise TournamentMetaUpdateError(f"{path} does not start with {prefix!r}.")
    payload = text[len(prefix) :].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


def load_app_champion_roles(index_path: Path = DEFAULT_INDEX) -> dict[str, list[str]]:
    text = index_path.read_text(encoding="utf-8")
    pattern = re.compile(r'c\("(?P<id>[^"]+)",\s*"[^"]+",\s*\[(?P<roles>[^\]]*)\]')
    roles_by_id: dict[str, list[str]] = {}
    for match in pattern.finditer(text):
        champion_id = match.group("id")
        roles = re.findall(r'"(TOP|JUNGLE|MID|ADC|SUPPORT)"', match.group("roles"))
        if roles:
            roles_by_id[champion_id] = roles
    if not roles_by_id:
        raise TournamentMetaUpdateError("Could not parse champion roles from index.html.")
    return roles_by_id


def load_existing_role_priors(path: Path = DEFAULT_EXISTING_META) -> dict[str, dict[str, int]]:
    if not path.exists():
        return {}
    data = read_js_assignment(path, "window.TOURNAMENT_2026_META = ")
    priors: dict[str, dict[str, int]] = {}
    for row in data.get("champions", []):
        if len(row) >= 8 and isinstance(row[7], dict):
            priors[row[0]] = {role: int(row[7].get(role, 0) or 0) for role in ROLES}
    return priors


def build_champion_id_lookup(roles_by_id: dict[str, list[str]]) -> dict[str, str]:
    lookup = {normalize_key(champion_id): champion_id for champion_id in roles_by_id}
    for alias, champion_id in ALIASES.items():
        if champion_id in roles_by_id:
            lookup[alias] = champion_id
    return lookup


def champion_id_for_gol_name(name: str, lookup: dict[str, str]) -> str | None:
    normalized = normalize_key(name)
    return lookup.get(normalized) or lookup.get(ALIASES.get(normalized, ""))


def infer_roles(champion_id: str, picks: int, roles_by_id: dict[str, list[str]], priors: dict[str, dict[str, int]]) -> dict[str, int]:
    empty = {role: 0 for role in ROLES}
    if picks <= 0:
        return empty

    prior = priors.get(champion_id, {})
    prior_total = sum(int(prior.get(role, 0) or 0) for role in ROLES)
    if prior_total > 0:
        result = empty.copy()
        remaining = picks
        ordered_roles = sorted(ROLES, key=lambda role: int(prior.get(role, 0) or 0), reverse=True)
        for role in ordered_roles:
            prior_value = int(prior.get(role, 0) or 0)
            if prior_value <= 0:
                continue
            value = int(round(picks * prior_value / prior_total))
            result[role] = max(0, value)
            remaining -= result[role]
        if remaining:
            result[ordered_roles[0]] += remaining
        return result

    champion_roles = roles_by_id.get(champion_id, [])
    if not champion_roles:
        return empty
    result = empty.copy()
    result[champion_roles[0]] = picks
    return result


def priority_score(bans: int, picks: int, games: int) -> float:
    if games <= 0:
        return 0.0
    presence = ((bans + picks) / games) * 100
    pick_share = (picks / max(1, games)) * 100
    return round(clamp(presence * 0.82 + pick_share * 0.18, 0, 100), 1)


def average_pick_round(bans: int, picks: int, priority: float) -> float:
    if picks <= 0:
        return 3.0
    ban_share = bans / max(1, bans + picks)
    value = 3.15 - priority * 0.012 + ban_share * 0.25
    return round(clamp(value, 1.2, 3.4), 2)


def discover_gol_tournaments(
    *,
    patterns: list[str],
    min_games: int,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    weekly_html = fetch_text(GOL_PICKS_OF_WEEK_URL)
    discovered = parse_gol_weekly_tournaments(weekly_html)
    selected = select_latest_tournaments(discovered, patterns=patterns, min_games=min_games, limit=limit)
    if selected:
        return discovered, selected
    return discovered, [
        {
            "name": "MSI 2026",
            "games": None,
            "patch": None,
            "statsUrl": GOL_STATS_URL,
            "picksBansUrl": GOL_PICKS_BANS_URL,
        }
    ]


def fetch_tournament_rows(selected: list[dict[str, Any]], delay: float) -> list[dict[str, Any]]:
    tournaments: list[dict[str, Any]] = []
    for index, tournament in enumerate(selected):
        if index:
            time.sleep(delay)
        picks_html = fetch_text(tournament["picksBansUrl"])
        rows = parse_gol_picks_bans(picks_html)
        time.sleep(delay)
        stats_html = fetch_text(tournament["statsUrl"])
        stats = parse_gol_stats(stats_html)
        tournaments.append({**tournament, "stats": stats, "rows": rows})
    return tournaments


def build_compact_meta(
    tournaments: list[dict[str, Any]],
    *,
    roles_by_id: dict[str, list[str]],
    role_priors: dict[str, dict[str, int]],
) -> dict[str, Any]:
    lookup = build_champion_id_lookup(roles_by_id)
    aggregate: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    total_games = 0

    for tournament in tournaments:
        games = int(tournament.get("stats", {}).get("games") or tournament.get("weeklyGames") or tournament.get("games") or 0)
        total_games += games
        for row in tournament["rows"]:
            champion_id = champion_id_for_gol_name(row["champion"], lookup)
            if not champion_id:
                errors.append(f"unmapped champion: {row['champion']}")
                continue
            target = aggregate.setdefault(
                champion_id,
                {
                    "bans": 0,
                    "picks": 0,
                    "wins": 0.0,
                    "roles": {role: 0 for role in ROLES},
                },
            )
            picks = int(row["picks"])
            bans = int(row["bans"])
            target["bans"] += bans
            target["picks"] += picks
            target["wins"] += picks * (float(row["winRate"]) / 100)
            inferred = infer_roles(champion_id, picks, roles_by_id, role_priors)
            for role in ROLES:
                target["roles"][role] += inferred.get(role, 0)

    champion_rows: list[list[Any]] = []
    for champion_id, row in aggregate.items():
        bans = int(row["bans"])
        picks = int(row["picks"])
        win_rate = round((row["wins"] / picks) * 100, 2) if picks else 0.0
        priority = priority_score(bans, picks, total_games)
        series_presence = round(clamp(((bans + picks) / max(1, total_games)) * 100, 0, 100), 1)
        champion_rows.append(
            [
                champion_id,
                bans,
                picks,
                win_rate,
                priority,
                series_presence,
                average_pick_round(bans, picks, priority),
                row["roles"],
            ]
        )

    champion_rows.sort(key=lambda item: (item[1] + item[2], item[4], item[2]), reverse=True)
    collected_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "metadata": {
            "source": "GOL.GG tournament picks/bans",
            "sourceDetail": "OP.GG 등 공개 LoL 통계 데이터와 대회 메타 데이터 참고",
            "tournaments": [tournament["name"] for tournament in tournaments],
            "patches": sorted({str(tournament.get("patch") or tournament.get("weeklyPatch") or "") for tournament in tournaments if tournament.get("patch") or tournament.get("weeklyPatch")}),
            "games": total_games,
            "collectedAt": collected_at,
            "champions": len(champion_rows),
            "errors": sorted(set(errors)),
        },
        "champions": champion_rows,
    }


def write_compact_meta(path: Path, meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"window.TOURNAMENT_2026_META = {payload};\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--existing-meta", type=Path, default=DEFAULT_EXISTING_META)
    parser.add_argument("--patterns", default=DEFAULT_GOL_TOURNAMENT_PATTERNS)
    parser.add_argument("--min-games", type=int, default=6)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    patterns = [pattern.strip() for pattern in args.patterns.split(",") if pattern.strip()]
    roles_by_id = load_app_champion_roles(args.index)
    role_priors = load_existing_role_priors(args.existing_meta)
    _, selected = discover_gol_tournaments(patterns=patterns, min_games=args.min_games, limit=args.limit)
    tournaments = fetch_tournament_rows(selected, delay=args.delay)
    meta = build_compact_meta(tournaments, roles_by_id=roles_by_id, role_priors=role_priors)

    if args.dry_run:
        print(json.dumps(meta, ensure_ascii=False, indent=2)[:4000])
        return 0

    write_compact_meta(args.out, meta)
    print(f"Updated {args.out} from {', '.join(meta['metadata']['tournaments'])}")
    if meta["metadata"]["errors"]:
        print("warnings:", "; ".join(meta["metadata"]["errors"][:10]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
