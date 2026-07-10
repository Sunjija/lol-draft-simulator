from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
TOURNAMENT = "MSI 2026"
TOURNAMENT_SLUG = "MSI%202026"
PICKS_URL = f"https://gol.gg/tournament/tournament-picksandbans/{TOURNAMENT_SLUG}/"
STATS_URL = f"https://gol.gg/tournament/tournament-stats/{TOURNAMENT_SLUG}/"
ID_ALIASES = {
    "chogath": "chogath",
    "drmundo": "drmundo",
    "jarvaniv": "jarvaniv",
    "kaisa": "kaisa",
    "khazix": "khazix",
    "kogmaw": "kogmaw",
    "ksante": "ksante",
    "leblanc": "leblanc",
    "leesin": "leeSin",
    "masteryi": "masteryi",
    "missfortune": "missfortune",
    "nunu": "nunu",
    "reksai": "reksai",
    "renataglasc": "renata",
    "tahmkench": "tahmkench",
    "twistedfate": "twistedfate",
    "velkoz": "velkoz",
    "wukong": "monkeyking",
    "xinzhao": "xinZhao",
}
CHAMPION_ROW = re.compile(
    r"champion-stats/(?P<numeric>\d+)/season-ALL/split-ALL/tournament-MSI%202026/[^>]*>"
    r".*?champions_icon/(?P<image>[^./]+)\.png.*?"
    r"Bans\s*:\s*(?P<bans>\d+).*?Picks\s*:\s*(?P<picks>\d+).*?Winrate\s*:\s*(?P<win>[0-9.]+)%",
    re.S,
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
                    )
                },
            )
            with urlopen(request, timeout=25) as response:
                return response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            time.sleep(1 + attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def extract_number(text: str, label: str) -> float | None:
    match = re.search(
        rf"{re.escape(label)}:\s*</td><td[^>]*>\s*([0-9.]+)%?",
        text,
        re.S,
    )
    return float(match.group(1)) if match else None


def parse_detail(text: str) -> dict:
    roles = {}
    for role, count in re.findall(
        r"role/(TOP|JUNGLE|MID|ADC|SUPPORT)\.png[^<]*'.*?</td>"
        r"<td style='text-align:center'>(\d+|-)</td>",
        text,
        re.S,
    ):
        roles[role] = 0 if count == "-" else int(count)
    return {
        "priorityScore": extract_number(text, "Priority Score"),
        "seriesPresence": extract_number(text, "Presence by Series"),
        "avgRoundPicked": extract_number(text, "Avg Round Picked"),
        "roles": roles,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect tournament-wide MSI champion draft context from gol.gg.")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    picks_html = fetch(PICKS_URL)
    stats_html = fetch(STATS_URL)
    games_match = re.search(r"Number of games:</td><td[^>]*>(\d+)</td>", stats_html)
    games = int(games_match.group(1)) if games_match else 0

    champions = []
    seen = set()
    for match in CHAMPION_ROW.finditer(picks_html):
        champion_id = app_id(match.group("image"))
        if champion_id in seen:
            continue
        seen.add(champion_id)
        numeric_id = int(match.group("numeric"))
        champions.append({
            "championId": champion_id,
            "numericId": numeric_id,
            "bans": int(match.group("bans")),
            "picks": int(match.group("picks")),
            "winRate": float(match.group("win")),
            "detailUrl": (
                f"https://gol.gg/champion/champion-stats/{numeric_id}/"
                f"season-ALL/split-ALL/tournament-{TOURNAMENT_SLUG}/"
            ),
        })

    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(fetch, row["detailUrl"]): row for row in champions}
        for future in as_completed(futures):
            row = futures[future]
            try:
                row.update(parse_detail(future.result()))
            except Exception as error:
                errors.append(f"{row['championId']}: {error}")
                row.update({"priorityScore": None, "seriesPresence": None, "avgRoundPicked": None, "roles": {}})

    champions.sort(key=lambda row: (-(row["bans"] + row["picks"]), row["championId"]))
    compact_rows = [
        [
            row["championId"], row["bans"], row["picks"], row["winRate"],
            row.get("priorityScore"), row.get("seriesPresence"), row.get("avgRoundPicked"),
            row.get("roles") or {},
        ]
        for row in champions
    ]
    payload = {
        "metadata": {
            "source": PICKS_URL,
            "tournament": TOURNAMENT,
            "games": games,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "champions": len(champions),
            "errors": errors,
        },
        "champions": compact_rows,
    }

    stamp = datetime.now().strftime("%Y%m%d")
    json_path = DATA_DIR / f"gol_msi_2026_meta_{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    compact_path = DATA_DIR / "gol_msi_2026_meta_compact.js"
    compact_path.write_text(
        "window.GOL_MSI_2026_META = " + json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    print(json.dumps({
        "games": games,
        "champions": len(champions),
        "errors": len(errors),
        "top": champions[:10],
        "json": str(json_path),
        "compact": str(compact_path),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
