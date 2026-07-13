#!/usr/bin/env python3
"""Update compact solo queue role stats from OP.GG champion statistics."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from probe_public_meta_sources import fetch_text, opgg_url, parse_opgg_champions
from update_gol_tournament_meta import (
    ALIASES,
    build_champion_id_lookup,
    champion_id_for_gol_name,
    load_app_champion_roles,
    normalize_key,
    read_js_assignment,
)


DEFAULT_INPUT = Path("data/league_draft_context_compact.js")
DEFAULT_OUTPUT = Path("data/league_draft_context_compact.js")
DEFAULT_INDEX = Path("index.html")
ROLE_TO_POSITION = {
    "TOP": "top",
    "JUNGLE": "jungle",
    "MID": "mid",
    "ADC": "adc",
    "SUPPORT": "support",
}
POSITION_TO_ROLE = {value: key for key, value in ROLE_TO_POSITION.items()}


class OpggContextUpdateError(RuntimeError):
    pass


def write_js_assignment(path: Path, variable_name: str, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"window.{variable_name} = {payload};\n", encoding="utf-8")


def load_existing_context(path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig").strip()
    match = re.match(r"window\.LEAGUE_DRAFT_CONTEXT\s*=\s*(.*);?\s*$", text, re.DOTALL)
    if not match:
        raise OpggContextUpdateError(f"{path} does not expose window.LEAGUE_DRAFT_CONTEXT.")
    payload = match.group(1)
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


def existing_champion_ids(context: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for rows in context.get("roleStats", {}).values():
        for row in rows:
            if row:
                ids.add(str(row[0]))
                for counter_id in row[6] if len(row) > 6 and isinstance(row[6], list) else []:
                    ids.add(str(counter_id))
    for group_rows in context.get("synergies", {}).values():
        for row in group_rows:
            if len(row) >= 2:
                ids.add(str(row[0]))
                ids.add(str(row[1]))
    return ids


def build_opgg_lookup(context: dict[str, Any], index_path: Path) -> dict[str, str]:
    roles_by_id = load_app_champion_roles(index_path)
    all_ids = {champion_id: roles for champion_id, roles in roles_by_id.items()}
    for champion_id in existing_champion_ids(context):
        all_ids.setdefault(champion_id, [])
    lookup = build_champion_id_lookup(all_ids)
    for alias, champion_id in ALIASES.items():
        if champion_id in all_ids:
            lookup[alias] = champion_id
    return lookup


def opgg_row_champion_id(row: dict[str, Any], lookup: dict[str, str]) -> str | None:
    return (
        lookup.get(normalize_key(str(row.get("key", ""))))
        or champion_id_for_gol_name(str(row.get("name", "")), lookup)
    )


def existing_role_payload(context: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    payload: dict[str, dict[str, dict[str, Any]]] = {}
    for role, rows in context.get("roleStats", {}).items():
        role_payload: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not row:
                continue
            role_payload[str(row[0])] = {
                "counters": row[6] if len(row) > 6 and isinstance(row[6], list) else [],
                "sourceKey": row[7] if len(row) > 7 else row[0],
            }
        payload[role] = role_payload
    return payload


def opgg_role_score(row: dict[str, Any]) -> float:
    win_rate = float(row["winRate"])
    pick_rate = float(row["pickRate"])
    ban_rate = float(row["banRate"])
    play = int(row["play"])
    play_bonus = min(8.0, max(0.0, (play.bit_length() - 10) * 0.65))
    return (win_rate - 50) * 1.9 + pick_rate * 2.2 + min(ban_rate, 18.0) * 0.08 + play_bonus


def filter_role_rows(
    rows: list[dict[str, Any]],
    *,
    lookup: dict[str, str],
    min_pick_rate: float,
    min_play: int,
    max_rows: int,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        champion_id = opgg_row_champion_id(row, lookup)
        if not champion_id or champion_id in seen:
            continue
        if float(row["pickRate"]) < min_pick_rate:
            continue
        if int(row["play"]) < min_play:
            continue
        seen.add(champion_id)
        filtered.append({**row, "championId": champion_id, "score": opgg_role_score(row)})

    filtered.sort(
        key=lambda row: (
            row["score"],
            float(row["pickRate"]),
            int(row["play"]),
        ),
        reverse=True,
    )
    return filtered[:max_rows]


def build_role_stats(
    opgg_by_position: dict[str, list[dict[str, Any]]],
    *,
    context: dict[str, Any],
    lookup: dict[str, str],
    min_pick_rate: float,
    min_play: int,
    max_rows: int,
) -> dict[str, list[list[Any]]]:
    preserved = existing_role_payload(context)
    role_stats: dict[str, list[list[Any]]] = {}
    for role, position in ROLE_TO_POSITION.items():
        selected = filter_role_rows(
            opgg_by_position[position],
            lookup=lookup,
            min_pick_rate=min_pick_rate,
            min_play=min_play,
            max_rows=max_rows,
        )
        total = len(selected)
        rows: list[list[Any]] = []
        for rank, row in enumerate(selected, start=1):
            champion_id = row["championId"]
            previous = preserved.get(role, {}).get(champion_id, {})
            rows.append(
                [
                    champion_id,
                    rank,
                    total,
                    round(float(row["winRate"]), 2),
                    round(float(row["pickRate"]), 2),
                    round(float(row["banRate"]), 2),
                    previous.get("counters", []),
                    previous.get("sourceKey", row["key"]),
                ]
            )
        role_stats[role] = rows
    return role_stats


def patch_from_opgg_rows(rows: list[dict[str, Any]]) -> str | None:
    for row in rows:
        match = re.search(r"/lol/(\d+\.\d+)", str(row.get("image", "")))
        if match:
            return match.group(1)
    return None


def fetch_opgg_role_stats(*, region: str, tier: str, delay: float) -> dict[str, list[dict[str, Any]]]:
    by_position: dict[str, list[dict[str, Any]]] = {}
    for index, position in enumerate(ROLE_TO_POSITION.values()):
        if index:
            time.sleep(delay)
        html = fetch_text(opgg_url(position, region, tier))
        by_position[position] = parse_opgg_champions(html)
    return by_position


def update_context_from_opgg(
    context: dict[str, Any],
    *,
    opgg_by_position: dict[str, list[dict[str, Any]]],
    lookup: dict[str, str],
    region: str,
    tier: str,
    min_pick_rate: float,
    min_play: int,
    max_rows: int,
) -> dict[str, Any]:
    role_stats = build_role_stats(
        opgg_by_position,
        context=context,
        lookup=lookup,
        min_pick_rate=min_pick_rate,
        min_play=min_play,
        max_rows=max_rows,
    )
    all_rows = [row for rows in opgg_by_position.values() for row in rows]
    patch = patch_from_opgg_rows(all_rows)
    metadata = {
        **context.get("metadata", {}),
        "source": "OP.GG champion statistics and preserved synergy data",
        "sourceDetail": "OP.GG 등 공개 LoL 통계 데이터와 대회 메타 데이터 참고",
        "region": region,
        "tier": tier,
        "patches": [patch] if patch else context.get("metadata", {}).get("patches", []),
        "collectedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "roleFilters": {
            "minPickRate": min_pick_rate,
            "minPlay": min_play,
            "maxRows": max_rows,
            "banRateNote": "Ban rate is preserved as a secondary signal; role inclusion is based on pick rate and play count.",
        },
        "errors": [],
    }
    return {
        **context,
        "metadata": metadata,
        "roleStats": role_stats,
        "synergies": context.get("synergies", {}),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--region", default="kr")
    parser.add_argument("--tier", default="emerald_plus")
    parser.add_argument("--min-pick-rate", type=float, default=0.45)
    parser.add_argument("--min-play", type=int, default=3000)
    parser.add_argument("--max-rows", type=int, default=70)
    parser.add_argument("--delay", type=float, default=0.8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    context = load_existing_context(args.input)
    lookup = build_opgg_lookup(context, args.index)
    opgg_by_position = fetch_opgg_role_stats(region=args.region, tier=args.tier, delay=args.delay)
    updated = update_context_from_opgg(
        context,
        opgg_by_position=opgg_by_position,
        lookup=lookup,
        region=args.region,
        tier=args.tier,
        min_pick_rate=args.min_pick_rate,
        min_play=args.min_play,
        max_rows=args.max_rows,
    )

    if args.dry_run:
        summary = {
            "metadata": updated["metadata"],
            "roleCounts": {role: len(rows) for role, rows in updated["roleStats"].items()},
            "topRows": {role: rows[:5] for role, rows in updated["roleStats"].items()},
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    write_js_assignment(args.out, "LEAGUE_DRAFT_CONTEXT", updated)
    print(f"Updated {args.out} from OP.GG role statistics")
    print(json.dumps({role: len(rows) for role, rows in updated["roleStats"].items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
