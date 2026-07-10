from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
POSITIONS = ("top", "jungle", "mid", "adc", "support")
ROLE_NAMES = {position: position.upper() for position in POSITIONS}
ID_ALIASES = {
    "jarvaniv": "jarvaniv",
    "leesin": "leeSin",
    "masteryi": "masteryi",
    "monkeyking": "monkeyking",
    "nunu": "nunu",
    "tahmkench": "tahmkench",
    "twistedfate": "twistedfate",
    "xinzhao": "xinZhao",
}
SYNERGY_OBJECT = re.compile(
    r'\{\\"play\\":(?P<play>\d+),'
    r'\\"synergy_position\\":\\"(?P<role>TOP|JUNGLE|MID|ADC|SUPPORT)\\",'
    r'\\"win_rate\\":(?P<win>[0-9.eE+-]+),'
    r'\\"pick_rate\\":(?P<pick>[0-9.eE+-]+),'
    r'\\"synergy_champion_name\\":\\"(?P<name>[^"\\]*)\\",'
    r'[^{}]*?\\"synergy_champion_key\\":\\"(?P<key>[^"\\]+)\\",'
    r'\\"tier_rank\\":(?P<tier>\d+)\}',
)


def app_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", str(value or "").lower())
    return ID_ALIASES.get(normalized, normalized)


def fetch(url: str, retries: int = 3) -> str:
    last_error = None
    for attempt in range(retries):
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                    ),
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
            with urlopen(request, timeout=25) as response:
                return response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            time.sleep(1.0 + attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def latest_counter_file(position: str) -> Path:
    files = sorted(
        DATA_DIR.glob(f"opgg_{position}_counters_kr_emerald_plus_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"No OP.GG counter file for {position}")
    return files[0]


def load_role_stats() -> tuple[dict, dict]:
    role_stats = {}
    metadata = {}
    for position in POSITIONS:
        payload = json.loads(latest_counter_file(position).read_text(encoding="utf-8"))
        role = ROLE_NAMES[position]
        champions = payload.get("champions") or []
        rows = []
        for row in champions:
            rows.append([
                app_id(row.get("championId") or row.get("opggId")),
                int(row.get("rank") or 0),
                len(champions),
                row.get("winRate"),
                row.get("pickRate"),
                row.get("banRate"),
                [app_id(counter.get("championId") or counter.get("opggId")) for counter in row.get("counters", [])],
                row.get("opggId") or row.get("championId"),
            ])
        role_stats[role] = rows
        metadata[role] = payload.get("metadata") or {}
    return role_stats, metadata


def synergy_url(opgg_id: str, position: str) -> str:
    return (
        f"https://op.gg/lol/champions/{quote(opgg_id)}/synergies/{position}"
        "?region=kr&tier=emerald_plus"
    )


def parse_synergies(text: str, base_id: str, base_role: str) -> list[dict]:
    wanted_roles = {"JUNGLE": {"TOP", "MID"}, "ADC": {"SUPPORT"}}[base_role]
    rows = []
    for match in SYNERGY_OBJECT.finditer(text):
        partner_role = match.group("role")
        if partner_role not in wanted_roles:
            continue
        rows.append({
            "baseId": base_id,
            "baseRole": base_role,
            "partnerId": app_id(match.group("key")),
            "partnerRole": partner_role,
            "play": int(match.group("play")),
            "winRate": round(float(match.group("win")) * 100, 2),
            "pickRate": round(float(match.group("pick")) * 100, 3),
            "partnerTier": int(match.group("tier")),
        })
    return rows


def stat_lookup(role_stats: dict) -> dict:
    return {
        role: {row[0]: {"winRate": row[3], "rank": row[1], "total": row[2]} for row in rows}
        for role, rows in role_stats.items()
    }


def score_synergy(row: dict, lookup: dict) -> float:
    base = lookup.get(row["baseRole"], {}).get(row["baseId"], {})
    partner = lookup.get(row["partnerRole"], {}).get(row["partnerId"], {})
    baselines = [value for value in (base.get("winRate"), partner.get("winRate")) if value is not None]
    baseline = sum(baselines) / len(baselines) if baselines else 50.0
    lift = row["winRate"] - baseline
    confidence = min(1.0, math.log1p(row["play"]) / math.log1p(500))
    return round(max(38.0, min(68.0, 50.0 + lift * 2.6 * confidence)), 1)


def collect_synergies(role_stats: dict, workers: int) -> tuple[dict, list[str]]:
    tasks = []
    for role in ("JUNGLE", "ADC"):
        position = role.lower()
        for row in role_stats[role]:
            tasks.append((row[0], role, row[7], position))

    collected = []
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(fetch, synergy_url(opgg_id, position)): (base_id, role, opgg_id)
            for base_id, role, opgg_id, position in tasks
        }
        for future in as_completed(futures):
            base_id, role, opgg_id = futures[future]
            try:
                rows = parse_synergies(future.result(), base_id, role)
                if not rows:
                    errors.append(f"{role}:{base_id}: no synergy rows")
                collected.extend(rows)
            except Exception as error:
                errors.append(f"{role}:{base_id}: {error}")

    lookup = stat_lookup(role_stats)
    grouped = {"jungleMid": [], "topJungle": [], "botDuo": []}
    for row in collected:
        if row["play"] < 60:
            continue
        score = score_synergy(row, lookup)
        compact = [row["baseId"], row["partnerId"], score, row["winRate"], row["play"]]
        if row["baseRole"] == "JUNGLE" and row["partnerRole"] == "MID":
            grouped["jungleMid"].append(compact)
        elif row["baseRole"] == "JUNGLE" and row["partnerRole"] == "TOP":
            grouped["topJungle"].append([row["partnerId"], row["baseId"], score, row["winRate"], row["play"]])
        elif row["baseRole"] == "ADC" and row["partnerRole"] == "SUPPORT":
            grouped["botDuo"].append(compact)

    for key in grouped:
        grouped[key].sort(key=lambda item: (item[0], item[1]))
    return grouped, errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Build compact OP.GG role and synergy data for the draft simulator.")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()

    role_stats, source_metadata = load_role_stats()
    synergies, errors = collect_synergies(role_stats, args.workers)
    patches = sorted({str(meta.get("patch") or "") for meta in source_metadata.values() if meta.get("patch")})
    payload = {
        "metadata": {
            "source": "OP.GG champion tier and synergy pages",
            "region": "kr",
            "tier": "emerald_plus",
            "patches": patches,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "minimumSynergyGames": 60,
            "synergyScoreNote": "Pair win-rate lift versus both champions' role win-rate baseline, sample-confidence adjusted and capped at 38-68.",
            "errors": errors,
        },
        "roleStats": role_stats,
        "synergies": synergies,
    }

    stamp = datetime.now().strftime("%Y%m%d")
    json_path = DATA_DIR / f"opgg_draft_context_kr_emerald_plus_{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    compact_path = DATA_DIR / "opgg_draft_context_compact.js"
    compact_path.write_text(
        "window.OPGG_DRAFT_CONTEXT = " + json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "roleCounts": {role: len(rows) for role, rows in role_stats.items()},
        "synergyCounts": {key: len(rows) for key, rows in synergies.items()},
        "errors": len(errors),
        "json": str(json_path),
        "compact": str(compact_path),
    }, ensure_ascii=False, indent=2))
    if errors:
        print("\n".join(errors[:20]))


if __name__ == "__main__":
    main()
