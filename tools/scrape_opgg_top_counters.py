from __future__ import annotations

import csv
import html
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data"
DESKTOP_HELPER = Path.home() / "Desktop" / "opgg-copy-helper"

REGION = "kr"
TIER = "emerald_plus"
POSITION = "top"
URL = f"https://op.gg/lol/champions?region={REGION}&tier={TIER}&position={POSITION}"

ID_ALIASES = {
    "chogath": "chogath",
    "drmundo": "drmundo",
    "monkeyking": "monkeyking",
    "tahmkench": "tahmkench",
    "xinzhao": "xinZhao",
    "masteryi": "masteryi",
    "jarvaniv": "jarvaniv",
    "ksante": "ksante",
}


def fetch(url: str) -> str:
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
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def clean_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", "", value or ""))
    return re.sub(r"\s+", " ", value).strip()


def app_id(opgg_id: str) -> str:
    return ID_ALIASES.get(opgg_id, opgg_id)


def extract_patch(text: str) -> str:
    match = re.search(r"Patch\s+([0-9.]+)", text)
    return match.group(1) if match else ""


def extract_rows(text: str) -> list[dict]:
    tbody_match = re.search(r"<tbody>(.*?)</tbody>", text, re.S)
    if not tbody_match:
        raise RuntimeError("Could not find OP.GG champion table body.")

    rows = []
    for row_html in re.findall(r"<tr>(.*?)</tr>", tbody_match.group(1), re.S):
        champion_match = re.search(
            r'href="/lol/champions/([^/]+)/build/top[^"]*".*?<strong[^>]*>(.*?)</strong>',
            row_html,
            re.S,
        )
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


def write_outputs(payload: dict) -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DESKTOP_HELPER.mkdir(parents=True, exist_ok=True)

    patch = payload["metadata"].get("patch") or "unknown"
    stamp = datetime.now().strftime("%Y%m%d")
    base_name = f"opgg_top_counters_{REGION}_{TIER}_{patch}_{stamp}"
    outputs = []

    json_path = OUT_DIR / f"{base_name}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(json_path)

    csv_path = OUT_DIR / f"{base_name}.csv"
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

    txt_path = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상성_카운터.txt"
    lines = [
        f"source: {URL}",
        f"patch: {patch}",
        f"region: {REGION}",
        f"tier: {TIER}",
        f"position: {POSITION}",
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

    desktop_json = DESKTOP_HELPER / f"{stamp}_OPGG_탑_상성_카운터.json"
    desktop_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs.append(desktop_json)

    return outputs


def main() -> None:
    text = fetch(URL)
    rows = extract_rows(text)
    if not rows:
        raise RuntimeError("No champion rows parsed from OP.GG.")

    payload = {
        "metadata": {
            "source": URL,
            "site": "OP.GG",
            "region": REGION,
            "tier": TIER,
            "position": POSITION.upper(),
            "patch": extract_patch(text),
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "note": "Each row's counters are champions OP.GG displays as difficult matchups for that row champion.",
        },
        "champions": rows,
    }

    outputs = write_outputs(payload)
    print(f"parsed_champions={len(rows)}")
    print("sample=" + json.dumps(rows[:3], ensure_ascii=False))
    for path in outputs:
        print(path)


if __name__ == "__main__":
    main()
