from __future__ import annotations

import argparse
import csv
import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DESKTOP_HELPER = Path.home() / "Desktop" / "opgg-copy-helper"

POSITIONS = {"top", "jungle", "mid", "adc", "support"}
POSITION_LABELS = {
    "top": "탑",
    "jungle": "정글",
    "mid": "미드",
    "adc": "원딜",
    "support": "서폿",
}

ID_ALIASES = {
    "chogath": "chogath",
    "drmundo": "drmundo",
    "jarvaniv": "jarvaniv",
    "ksante": "ksante",
    "monkeyking": "monkeyking",
    "masteryi": "masteryi",
    "tahmkench": "tahmkench",
    "xinzhao": "xinZhao",
}

REQUEST_TIMEOUT = 20
RETRIES = 3
REQUEST_DELAY = 0.0


def fetch(url: str) -> str:
    last_error = None
    for attempt in range(RETRIES):
        try:
            if REQUEST_DELAY > 0:
                time.sleep(REQUEST_DELAY)
            request = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0 Safari/537.36"
                    ),
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                },
            )
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            last_error = error
            if error.code in {429, 500, 502, 503, 504}:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except URLError as error:
            last_error = error
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"Request failed after retries: {last_error}")


def clean_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", "", value or ""))
    return re.sub(r"\s+", " ", value).strip()


def app_id(opgg_id: str) -> str:
    return ID_ALIASES.get(opgg_id, opgg_id)


def extract_patch(text: str) -> str:
    match = re.search(r"Patch\s+([0-9.]+)", text)
    return match.group(1) if match else ""


def champions_url(region: str, tier: str, position: str) -> str:
    return f"https://op.gg/lol/champions?region={region}&tier={tier}&position={position}"


def matchup_url(region: str, tier: str, position: str, champion_opgg_id: str, target_opgg_id: str) -> str:
    return (
        f"https://www.op.gg/champions/{quote(champion_opgg_id)}/counters/{position}"
        f"?region={region}&tier={tier}&target_champion={quote(target_opgg_id)}"
    )


def extract_rows(text: str, position: str) -> list[dict]:
    tbody_match = re.search(r"<tbody>(.*?)</tbody>", text, re.S)
    if not tbody_match:
        raise RuntimeError("Could not find OP.GG champion table body.")

    champion_pattern = re.compile(
        rf'href="/lol/champions/([^/]+)/build/{re.escape(position)}[^"]*".*?<strong[^>]*>(.*?)</strong>',
        re.S,
    )

    rows = []
    for row_html in re.findall(r"<tr>(.*?)</tr>", tbody_match.group(1), re.S):
        champion_match = champion_pattern.search(row_html)
        if not champion_match:
            continue

        rank_match = re.search(r'<span class="w-5[^"]*text-gray-400">(\d+)</span>', row_html)
        rates = [
            float(value)
            for value in re.findall(r'text-xs text-gray-600[^"]*">([0-9.]+)<!-- -->%', row_html)
        ]

        champion_opgg_id = unquote(champion_match.group(1))
        counters = []
        for counter_name, counter_id in re.findall(
            r'data-tooltip-content="([^"]+)".*?target_champion=([^&"]+)',
            row_html,
            re.S,
        ):
            counter_opgg_id = unquote(counter_id)
            counters.append({
                "championId": app_id(counter_opgg_id),
                "opggId": counter_opgg_id,
                "championName": html.unescape(counter_name),
            })

        rows.append({
            "rank": int(rank_match.group(1)) if rank_match else len(rows) + 1,
            "championId": app_id(champion_opgg_id),
            "opggId": champion_opgg_id,
            "championName": clean_text(champion_match.group(2)),
            "winRate": rates[0] if len(rates) > 0 else None,
            "pickRate": rates[1] if len(rates) > 1 else None,
            "banRate": rates[2] if len(rates) > 2 else None,
            "counters": counters[:3],
        })
    return rows


def write_counter_outputs(payload: dict, region: str, tier: str, position: str) -> list[Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_HELPER.mkdir(parents=True, exist_ok=True)

    patch = payload["metadata"].get("patch") or "unknown"
    stamp = datetime.now().strftime("%Y%m%d")
    position_label = POSITION_LABELS[position]
    base_name = f"opgg_{position}_counters_{region}_{tier}_{patch}_{stamp}"
    outputs = []

    json_path = DATA_DIR / f"{base_name}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(json_path)

    csv_path = DATA_DIR / f"{base_name}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "rank",
            "championId",
            "championName",
            "winRate",
            "pickRate",
            "banRate",
            "counter1Id",
            "counter1Name",
            "counter2Id",
            "counter2Name",
            "counter3Id",
            "counter3Name",
        ])
        for row in payload["champions"]:
            counters = row.get("counters", [])
            flat = []
            for index in range(3):
                counter = counters[index] if index < len(counters) else {}
                flat.extend([counter.get("championId", ""), counter.get("championName", "")])
            writer.writerow([
                row.get("rank"),
                row.get("championId"),
                row.get("championName"),
                row.get("winRate"),
                row.get("pickRate"),
                row.get("banRate"),
                *flat,
            ])
    outputs.append(csv_path)

    txt_path = DESKTOP_HELPER / f"{stamp}_OPGG_{position_label}_상성_카운터.txt"
    lines = [
        f"source: {payload['metadata']['source']}",
        f"patch: {patch}",
        f"region: {region}",
        f"tier: {tier}",
        f"position: {position}",
        "",
    ]
    for row in payload["champions"]:
        counters = ", ".join(
            f"{counter['championName']}({counter['championId']})"
            for counter in row.get("counters", [])
        )
        lines.append(
            f"{row['rank']:>2}. {row['championName']}({row['championId']}) "
            f"WR {row['winRate']}% PR {row['pickRate']}% BR {row['banRate']}% "
            f"badInto: {counters}"
        )
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    outputs.append(txt_path)

    desktop_json = DESKTOP_HELPER / f"{stamp}_OPGG_{position_label}_상성_카운터.json"
    desktop_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(desktop_json)

    return outputs


def collect_champions(region: str, tier: str, position: str) -> tuple[dict, list[Path]]:
    url = champions_url(region, tier, position)
    text = fetch(url)
    rows = extract_rows(text, position)
    if not rows:
        raise RuntimeError(f"No champion rows parsed from OP.GG for position={position}.")

    payload = {
        "metadata": {
            "source": url,
            "site": "OP.GG",
            "region": region,
            "tier": tier,
            "position": position.upper(),
            "patch": extract_patch(text),
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "note": "Each row's counters are champions OP.GG displays as difficult matchups for that row champion.",
        },
        "champions": rows,
    }
    return payload, write_counter_outputs(payload, region, tier, position)


def latest_counter_file(region: str, tier: str, position: str) -> Path:
    files = sorted(
        DATA_DIR.glob(f"opgg_{position}_counters_{region}_{tier}_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"No saved counter file for position={position}. Run without --use-existing-counters first.")
    return files[0]


def load_existing_champions(region: str, tier: str, position: str) -> tuple[dict, list[Path]]:
    path = latest_counter_file(region, tier, position)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload, [path]


def cache_path(region: str, tier: str, position: str, metadata: dict) -> Path:
    patch = metadata.get("patch") or "unknown"
    return DATA_DIR / f"opgg_{position}_lane_kill_cache_{region}_{tier}_{patch}.json"


def output_base(region: str, tier: str, position: str, metadata: dict) -> str:
    patch = metadata.get("patch") or "unknown"
    stamp = datetime.now().strftime("%Y%m%d")
    return f"opgg_{position}_lane_kill_{region}_{tier}_{patch}_{stamp}"


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def parse_lane_kill_rates(text: str) -> tuple[float, float]:
    marker = "Lane kill rate"
    index = text.find(marker)
    if index < 0:
        raise ValueError("Lane kill rate marker not found.")

    before = text[max(0, index - 900):index]
    after = text[index:index + 900]
    left_values = re.findall(r">([0-9]+(?:\.[0-9]+)?)%</span>", before)
    right_values = re.findall(r">([0-9]+(?:\.[0-9]+)?)%</span>", after)
    if not left_values or not right_values:
        raise ValueError("Could not parse lane kill rate values.")
    return float(left_values[-1]), float(right_values[0])


def scrape_pair(region: str, tier: str, position: str, champion: dict, target: dict) -> dict:
    url = matchup_url(region, tier, position, champion["opggId"], target["opggId"])
    text = fetch(url)
    lane_kill, target_lane_kill = parse_lane_kill_rates(text)
    return {
        "championId": champion["championId"],
        "championName": champion["championName"],
        "targetChampionId": target["championId"],
        "targetChampionName": target["championName"],
        "laneKillRate": lane_kill,
        "targetLaneKillRate": target_lane_kill,
        "url": url,
    }


def round_percent(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def average(values: list[float]) -> float | None:
    if not values:
        return None
    return round_percent(sum(values) / len(values))


def build_paired_matchups(rows: list[dict], champions: list[dict]) -> list[dict]:
    by_id = {champion["championId"]: champion for champion in champions}
    pair_map: dict[str, dict] = {}

    for row in rows:
        champion_id = row.get("championId")
        target_id = row.get("targetChampionId")
        lane_kill = row.get("laneKillRate")
        target_lane_kill = row.get("targetLaneKillRate")
        if (
            champion_id not in by_id
            or target_id not in by_id
            or champion_id == target_id
            or lane_kill is None
            or target_lane_kill is None
        ):
            continue

        a_id, b_id = sorted([champion_id, target_id])
        key = f"{a_id}__{b_id}"
        pair = pair_map.setdefault(
            key,
            {
                "championAId": a_id,
                "championAName": by_id[a_id]["championName"],
                "championBId": b_id,
                "championBName": by_id[b_id]["championName"],
                "_aValues": [],
                "_bValues": [],
                "_urls": [],
            },
        )

        if champion_id == a_id:
            pair["_aValues"].append(float(lane_kill))
            pair["_bValues"].append(float(target_lane_kill))
        else:
            pair["_bValues"].append(float(lane_kill))
            pair["_aValues"].append(float(target_lane_kill))
        pair["_urls"].append(row.get("url", ""))

    paired = []
    for pair in pair_map.values():
        a_rate = average(pair["_aValues"])
        b_rate = average(pair["_bValues"])
        if a_rate is None or b_rate is None:
            continue

        signed_diff = round_percent(a_rate - b_rate) or 0
        if abs(signed_diff) < 0.01:
            favored_id = ""
            favored_name = ""
            favored_rate = None
        elif signed_diff > 0:
            favored_id = pair["championAId"]
            favored_name = pair["championAName"]
            favored_rate = a_rate
        else:
            favored_id = pair["championBId"]
            favored_name = pair["championBName"]
            favored_rate = b_rate

        paired.append({
            "championAId": pair["championAId"],
            "championAName": pair["championAName"],
            "championALaneKillRate": a_rate,
            "championBId": pair["championBId"],
            "championBName": pair["championBName"],
            "championBLaneKillRate": b_rate,
            "laneKillDiff": round_percent(abs(signed_diff)),
            "favoredChampionId": favored_id,
            "favoredChampionName": favored_name,
            "favoredLaneKillRate": favored_rate,
            "sampledDirections": len(pair["_urls"]),
            "urls": sorted(set(url for url in pair["_urls"] if url)),
        })

    return sorted(paired, key=lambda row: (row["championAId"], row["championBId"]))


def build_lane_outputs(metadata: dict, champions: list[dict], cache: dict, region: str, tier: str, position: str) -> dict:
    by_id = {champion["championId"]: champion for champion in champions}
    rows = list(cache.values())
    all_matchups = sorted(
        [
            row
            for row in rows
            if row.get("championId") in by_id
            and row.get("targetChampionId") in by_id
            and row.get("laneKillRate") is not None
        ],
        key=lambda row: (row.get("championId", ""), -(row.get("laneKillRate") or 0)),
    )
    paired_matchups = build_paired_matchups(all_matchups, champions)

    grouped = []
    for champion in champions:
        champion_rows = [row for row in all_matchups if row.get("championId") == champion["championId"]]
        top3 = sorted(champion_rows, key=lambda row: row.get("laneKillRate", 0), reverse=True)[:3]
        grouped.append({
            "championId": champion["championId"],
            "championName": champion["championName"],
            "laneKillMatchups": top3,
            "topLaneKillMatchups": top3,
        })

    return {
        "metadata": {
            "source": "OP.GG detailed champion counter pages",
            "region": region,
            "tier": tier,
            "position": position.upper(),
            "patch": metadata.get("patch") or "",
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "note": (
                "laneKillRate is the selected champion's Lane kill rate against targetChampion "
                "from the OP.GG detailed counter page. pairedMatchups merges both directions "
                "of the same champion pair into one row."
            ),
        },
        "champions": grouped,
        "allMatchups": all_matchups,
        "pairedMatchups": paired_matchups,
    }


def write_compact_js(payload: dict, region: str, tier: str, position: str, base: str) -> Path:
    compact = {
        "metadata": {
            "source": payload["metadata"].get("source"),
            "region": region,
            "tier": tier,
            "position": position.upper(),
            "patch": payload["metadata"].get("patch"),
            "collectedAt": payload["metadata"].get("collectedAt"),
        },
        "pairs": [
            [
                row["championAId"],
                row["championBId"],
                row["championALaneKillRate"],
                row["championBLaneKillRate"],
            ]
            for row in payload["pairedMatchups"]
        ],
    }
    path = DATA_DIR / f"opgg_{position}_lane_matchups_compact.js"
    var_name = f"OPGG_{position.upper()}_LANE_MATCHUPS"
    path.write_text(
        f"window.{var_name} = " + json.dumps(compact, ensure_ascii=True, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    return path


def write_lane_outputs(payload: dict, region: str, tier: str, position: str) -> list[Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_HELPER.mkdir(parents=True, exist_ok=True)

    base = output_base(region, tier, position, payload["metadata"])
    stamp = datetime.now().strftime("%Y%m%d")
    position_label = POSITION_LABELS[position]
    outputs = []

    json_path = DATA_DIR / f"{base}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(json_path)

    top3_csv_path = DATA_DIR / f"{base}_top3.csv"
    with top3_csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "championId",
            "championName",
            "rank",
            "targetChampionId",
            "targetChampionName",
            "laneKillRate",
            "targetLaneKillRate",
            "url",
        ])
        for champion in payload["champions"]:
            for index, row in enumerate(champion.get("laneKillMatchups") or champion["topLaneKillMatchups"], start=1):
                writer.writerow([
                    champion["championId"],
                    champion["championName"],
                    index,
                    row["targetChampionId"],
                    row["targetChampionName"],
                    row["laneKillRate"],
                    row["targetLaneKillRate"],
                    row["url"],
                ])
    outputs.append(top3_csv_path)

    all_csv_path = DATA_DIR / f"{base}_all.csv"
    with all_csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "championId",
            "championName",
            "targetChampionId",
            "targetChampionName",
            "laneKillRate",
            "targetLaneKillRate",
            "url",
        ])
        for row in payload["allMatchups"]:
            writer.writerow([
                row["championId"],
                row["championName"],
                row["targetChampionId"],
                row["targetChampionName"],
                row["laneKillRate"],
                row["targetLaneKillRate"],
                row["url"],
            ])
    outputs.append(all_csv_path)

    pairs_json_payload = {
        "metadata": payload["metadata"],
        "pairedMatchups": payload["pairedMatchups"],
    }
    pairs_json_path = DATA_DIR / f"{base}_paired.json"
    pairs_json_path.write_text(json.dumps(pairs_json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(pairs_json_path)

    pairs_csv_path = DATA_DIR / f"{base}_paired.csv"
    with pairs_csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            "championAId",
            "championAName",
            "championALaneKillRate",
            "championBId",
            "championBName",
            "championBLaneKillRate",
            "laneKillDiff",
            "favoredChampionId",
            "favoredChampionName",
            "favoredLaneKillRate",
            "sampledDirections",
        ])
        for row in payload["pairedMatchups"]:
            writer.writerow([
                row["championAId"],
                row["championAName"],
                row["championALaneKillRate"],
                row["championBId"],
                row["championBName"],
                row["championBLaneKillRate"],
                row["laneKillDiff"],
                row["favoredChampionId"],
                row["favoredChampionName"],
                row["favoredLaneKillRate"],
                row["sampledDirections"],
            ])
    outputs.append(pairs_csv_path)

    compact_path = write_compact_js(payload, region, tier, position, base)
    outputs.append(compact_path)

    top3_txt = DESKTOP_HELPER / f"{stamp}_OPGG_{position_label}_상세라인킬_TOP3.txt"
    top3_lines = [
        f"source: {payload['metadata']['source']}",
        f"patch: {payload['metadata']['patch']}",
        f"region: {region}",
        f"tier: {tier}",
        f"position: {position}",
        "",
    ]
    for champion in payload["champions"]:
        parts = [
            f"{row['targetChampionName']}({row['targetChampionId']}) {row['laneKillRate']}%"
            for row in (champion.get("laneKillMatchups") or champion["topLaneKillMatchups"])
        ]
        top3_lines.append(f"{champion['championName']}({champion['championId']}): " + " / ".join(parts))
    top3_txt.write_text("\n".join(top3_lines) + "\n", encoding="utf-8")
    outputs.append(top3_txt)

    desktop_all_json = DESKTOP_HELPER / f"{stamp}_OPGG_{position_label}_상세라인킬_전체.json"
    desktop_all_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(desktop_all_json)

    desktop_all_csv = DESKTOP_HELPER / f"{stamp}_OPGG_{position_label}_상세라인킬_전체.csv"
    desktop_all_csv.write_bytes(all_csv_path.read_bytes())
    outputs.append(desktop_all_csv)

    desktop_pairs_json = DESKTOP_HELPER / f"{stamp}_OPGG_{position_label}_상세라인킬_상호매치업.json"
    desktop_pairs_json.write_text(json.dumps(pairs_json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(desktop_pairs_json)

    desktop_pairs_csv = DESKTOP_HELPER / f"{stamp}_OPGG_{position_label}_상세라인킬_상호매치업.csv"
    desktop_pairs_csv.write_bytes(pairs_csv_path.read_bytes())
    outputs.append(desktop_pairs_csv)

    desktop_pairs_txt = DESKTOP_HELPER / f"{stamp}_OPGG_{position_label}_상세라인킬_상호매치업.txt"
    pair_lines = [
        f"source: {payload['metadata']['source']}",
        f"patch: {payload['metadata']['patch']}",
        f"region: {region}",
        f"tier: {tier}",
        f"position: {position}",
        "",
    ]
    for row in sorted(payload["pairedMatchups"], key=lambda item: item["laneKillDiff"], reverse=True):
        if row["favoredChampionName"]:
            pair_lines.append(
                f"{row['championAName']}({row['championAId']}) {row['championALaneKillRate']}% "
                f"vs {row['championBName']}({row['championBId']}) {row['championBLaneKillRate']}% "
                f"=> {row['favoredChampionName']} +{row['laneKillDiff']}%"
            )
        else:
            pair_lines.append(
                f"{row['championAName']}({row['championAId']}) {row['championALaneKillRate']}% "
                f"vs {row['championBName']}({row['championBId']}) {row['championBLaneKillRate']}% => even"
            )
    desktop_pairs_txt.write_text("\n".join(pair_lines) + "\n", encoding="utf-8")
    outputs.append(desktop_pairs_txt)

    return outputs


def collect_lane_matchups(
    metadata: dict,
    champions: list[dict],
    region: str,
    tier: str,
    position: str,
    workers: int,
) -> tuple[dict, list[Path]]:
    path = cache_path(region, tier, position, metadata)
    cache = load_cache(path)
    lock = threading.Lock()

    tasks = []
    for champion in champions:
        for target in champions:
            if champion["championId"] == target["championId"]:
                continue
            key = f"{champion['championId']}__{target['championId']}"
            if key in cache and cache[key].get("laneKillRate") is not None:
                continue
            tasks.append((key, champion, target))

    total_pairs = len(champions) * (len(champions) - 1)
    print(f"position={position} champions={len(champions)} total_pairs={total_pairs} cached={len(cache)} remaining={len(tasks)}")

    completed = 0
    if tasks:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(scrape_pair, region, tier, position, champion, target): (key, champion, target)
                for key, champion, target in tasks
            }
            for future in as_completed(futures):
                key, champion, target = futures[future]
                try:
                    row = future.result()
                except Exception as error:
                    row = {
                        "championId": champion["championId"],
                        "championName": champion["championName"],
                        "targetChampionId": target["championId"],
                        "targetChampionName": target["championName"],
                        "laneKillRate": None,
                        "targetLaneKillRate": None,
                        "error": str(error),
                        "url": matchup_url(region, tier, position, champion["opggId"], target["opggId"]),
                    }
                with lock:
                    cache[key] = row
                    completed += 1
                    done = len(cache)
                    if completed % 50 == 0 or completed == len(tasks):
                        save_cache(path, cache)
                        print(f"progress={done}/{total_pairs} latest={champion['championId']} vs {target['championId']}")

    save_cache(path, cache)
    payload = build_lane_outputs(metadata, champions, cache, region, tier, position)
    outputs = write_lane_outputs(payload, region, tier, position)

    error_count = sum(1 for row in cache.values() if row.get("error"))
    print(f"done_pairs={len(cache)} errors={error_count}")
    print(f"all_matchups={len(payload['allMatchups'])} paired_matchups={len(payload['pairedMatchups'])}")
    for champion in payload["champions"][:3]:
        print(json.dumps(champion, ensure_ascii=False))
    return payload, outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect OP.GG champion counters and detailed lane-kill matchups.")
    parser.add_argument("--position", required=True, choices=sorted(POSITIONS))
    parser.add_argument("--region", default="kr")
    parser.add_argument("--tier", default="emerald_plus")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--counters-only", action="store_true")
    parser.add_argument("--use-existing-counters", action="store_true")
    parser.add_argument("--request-delay", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    global REQUEST_DELAY
    args = parse_args()
    REQUEST_DELAY = max(0.0, args.request_delay)
    if args.use_existing_counters:
        payload, counter_outputs = load_existing_champions(args.region, args.tier, args.position)
    else:
        payload, counter_outputs = collect_champions(args.region, args.tier, args.position)
    print(f"parsed_champions={len(payload['champions'])}")
    print("sample=" + json.dumps(payload["champions"][:3], ensure_ascii=False))
    for path in counter_outputs:
        print(path)

    if args.counters_only:
        return

    _, matchup_outputs = collect_lane_matchups(
        payload["metadata"],
        payload["champions"],
        args.region,
        args.tier,
        args.position,
        max(1, args.workers),
    )
    for path in matchup_outputs:
        print(path)


if __name__ == "__main__":
    main()
