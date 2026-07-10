from __future__ import annotations

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
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DESKTOP_HELPER = Path.home() / "Desktop" / "opgg-copy-helper"

REGION = "kr"
TIER = "emerald_plus"
POSITION = "top"
MAX_WORKERS = 4
REQUEST_TIMEOUT = 20
RETRIES = 3


def latest_counter_file() -> Path:
    files = sorted(
        DATA_DIR.glob(f"opgg_top_counters_{REGION}_{TIER}_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError("Run scrape_opgg_top_counters.py first.")
    return files[0]


def fetch(url: str) -> str:
    last_error = None
    for attempt in range(RETRIES):
        try:
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


def matchup_url(champion_opgg_id: str, target_opgg_id: str) -> str:
    return (
        f"https://www.op.gg/champions/{quote(champion_opgg_id)}/counters/{POSITION}"
        f"?region={REGION}&tier={TIER}&target_champion={quote(target_opgg_id)}"
    )


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


def load_seed() -> tuple[dict, list[dict]]:
    source = latest_counter_file()
    payload = json.loads(source.read_text(encoding="utf-8"))
    champions = payload["champions"]
    return payload["metadata"], champions


def cache_path(metadata: dict) -> Path:
    patch = metadata.get("patch") or "unknown"
    return DATA_DIR / f"opgg_top_lane_kill_cache_{REGION}_{TIER}_{patch}.json"


def output_base(metadata: dict) -> str:
    patch = metadata.get("patch") or "unknown"
    stamp = datetime.now().strftime("%Y%m%d")
    return f"opgg_top_lane_kill_{REGION}_{TIER}_{patch}_{stamp}"


def load_cache(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def scrape_pair(champion: dict, target: dict) -> dict:
    url = matchup_url(champion["opggId"], target["opggId"])
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


def build_outputs(metadata: dict, champions: list[dict], cache: dict) -> dict:
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
        champion_rows = [
            row
            for row in all_matchups
            if row.get("championId") == champion["championId"]
        ]
        top3 = sorted(champion_rows, key=lambda row: row.get("laneKillRate", 0), reverse=True)[:3]
        grouped.append({
            "championId": champion["championId"],
            "championName": champion["championName"],
            "topLaneKillMatchups": top3,
        })

    return {
        "metadata": {
            "source": "OP.GG detailed champion counter pages",
            "region": REGION,
            "tier": TIER,
            "position": POSITION.upper(),
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


def write_top3_outputs_legacy(payload: dict) -> list[Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_HELPER.mkdir(parents=True, exist_ok=True)
    base = output_base(payload["metadata"])
    outputs = []

    json_path = DATA_DIR / f"{base}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(json_path)

    csv_path = DATA_DIR / f"{base}.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
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
            for index, row in enumerate(champion["topLaneKillMatchups"], start=1):
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
    outputs.append(csv_path)

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

    pairs_json_path = DATA_DIR / f"{base}_paired.json"
    pairs_json_payload = {
        "metadata": payload["metadata"],
        "pairedMatchups": payload["pairedMatchups"],
    }
    pairs_json_path.write_text(
        json.dumps(pairs_json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    outputs.append(pairs_json_path)

    stamp = datetime.now().strftime("%Y%m%d")
    txt_path = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상세라인킬_TOP3.txt"
    lines = [
        f"source: {payload['metadata']['source']}",
        f"patch: {payload['metadata']['patch']}",
        f"region: {REGION}",
        f"tier: {TIER}",
        f"position: {POSITION}",
        "",
    ]
    for champion in payload["champions"]:
        parts = [
            f"{row['targetChampionName']}({row['targetChampionId']}) {row['laneKillRate']}%"
            for row in champion["topLaneKillMatchups"]
        ]
        lines.append(f"{champion['championName']}({champion['championId']}): " + " / ".join(parts))
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    outputs.append(txt_path)

    desktop_json = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상세라인킬_TOP3.json"
    desktop_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(desktop_json)

    return outputs


def write_outputs(payload: dict) -> list[Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_HELPER.mkdir(parents=True, exist_ok=True)
    base = output_base(payload["metadata"])
    stamp = datetime.now().strftime("%Y%m%d")
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
            for index, row in enumerate(champion["topLaneKillMatchups"], start=1):
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
    pairs_json_path.write_text(
        json.dumps(pairs_json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
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

    top3_txt = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상세라인킬_TOP3.txt"
    top3_lines = [
        f"source: {payload['metadata']['source']}",
        f"patch: {payload['metadata']['patch']}",
        f"region: {REGION}",
        f"tier: {TIER}",
        f"position: {POSITION}",
        "",
    ]
    for champion in payload["champions"]:
        parts = [
            f"{row['targetChampionName']}({row['targetChampionId']}) {row['laneKillRate']}%"
            for row in champion["topLaneKillMatchups"]
        ]
        top3_lines.append(f"{champion['championName']}({champion['championId']}): " + " / ".join(parts))
    top3_txt.write_text("\n".join(top3_lines) + "\n", encoding="utf-8")
    outputs.append(top3_txt)

    top3_json = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상세라인킬_TOP3.json"
    top3_json_payload = {
        "metadata": payload["metadata"],
        "champions": payload["champions"],
    }
    top3_json.write_text(json.dumps(top3_json_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(top3_json)

    desktop_all_json = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상세라인킬_전체.json"
    desktop_all_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(desktop_all_json)

    desktop_all_csv = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상세라인킬_전체.csv"
    desktop_all_csv.write_bytes(all_csv_path.read_bytes())
    outputs.append(desktop_all_csv)

    desktop_pairs_csv = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상세라인킬_상호매치업.csv"
    desktop_pairs_csv.write_bytes(pairs_csv_path.read_bytes())
    outputs.append(desktop_pairs_csv)

    desktop_pairs_json = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상세라인킬_상호매치업.json"
    desktop_pairs_json.write_text(
        json.dumps(pairs_json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    outputs.append(desktop_pairs_json)

    desktop_pairs_txt = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상세라인킬_상호매치업.txt"
    pair_lines = [
        f"source: {payload['metadata']['source']}",
        f"patch: {payload['metadata']['patch']}",
        f"region: {REGION}",
        f"tier: {TIER}",
        f"position: {POSITION}",
        "",
    ]
    for row in sorted(payload["pairedMatchups"], key=lambda item: item["laneKillDiff"], reverse=True):
        if row["favoredChampionName"]:
            summary = (
                f"{row['championAName']}({row['championAId']}) {row['championALaneKillRate']}% "
                f"vs {row['championBName']}({row['championBId']}) {row['championBLaneKillRate']}% "
                f"=> {row['favoredChampionName']} +{row['laneKillDiff']}%"
            )
        else:
            summary = (
                f"{row['championAName']}({row['championAId']}) {row['championALaneKillRate']}% "
                f"vs {row['championBName']}({row['championBId']}) {row['championBLaneKillRate']}% "
                "=> even"
            )
        pair_lines.append(summary)
    desktop_pairs_txt.write_text("\n".join(pair_lines) + "\n", encoding="utf-8")
    outputs.append(desktop_pairs_txt)

    return outputs


def main() -> None:
    metadata, champions = load_seed()
    path = cache_path(metadata)
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
    print(f"champions={len(champions)} total_pairs={total_pairs} cached={len(cache)} remaining={len(tasks)}")

    completed = 0
    if tasks:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(scrape_pair, champion, target): (key, champion, target)
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
                        "url": matchup_url(champion["opggId"], target["opggId"]),
                    }
                with lock:
                    cache[key] = row
                    completed += 1
                    done = len(cache)
                    if completed % 50 == 0 or completed == len(tasks):
                        save_cache(path, cache)
                        print(f"progress={done}/{total_pairs} latest={champion['championId']} vs {target['championId']}")

    save_cache(path, cache)
    payload = build_outputs(metadata, champions, cache)
    outputs = write_outputs(payload)

    error_count = sum(1 for row in cache.values() if row.get("error"))
    print(f"done_pairs={len(cache)} errors={error_count}")
    for champion in payload["champions"][:5]:
        print(json.dumps(champion, ensure_ascii=False))
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
