#!/usr/bin/env python3
"""Post the latest Korean League of Legends patch note to Discord.

The script is designed for GitHub Actions. It reads a Discord webhook URL from
DISCORD_WEBHOOK_URL and stores the last posted Riot article URL in a small state
file so scheduled runs do not repost the same patch note.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


PATCH_NOTES_URL = "https://www.leagueoflegends.com/ko-kr/news/tags/patch-notes/"
BASE_URL = "https://www.leagueoflegends.com"
DEFAULT_STATE_PATH = Path(".cache/korean_patch_notes_state.json")
USER_AGENT = "lol-draft-simulator/1.0 (+https://sunjija.github.io/lol-draft-simulator/)"


class PatchNoteError(RuntimeError):
    pass


def request_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def request_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", "replace")
            return {"status": response.status, "body": raw}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise PatchNoteError(f"Discord webhook failed: HTTP {exc.code} {raw}") from exc


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def absolute_url(value: str) -> str:
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/"):
        return f"{BASE_URL}{value}"
    return f"{BASE_URL}/{value}"


def load_next_data(page_html: str) -> dict[str, Any]:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        page_html,
        re.DOTALL,
    )
    if not match:
        raise PatchNoteError("Could not find Riot __NEXT_DATA__ payload.")
    return json.loads(html.unescape(match.group(1)))


def latest_patch_note() -> dict[str, str]:
    page_html = request_text(PATCH_NOTES_URL)
    data = load_next_data(page_html)
    blades = data["props"]["pageProps"]["page"]["blades"]
    grid = next((blade for blade in blades if blade.get("type") == "articleCardGrid"), None)
    if not grid:
        raise PatchNoteError("Could not find Riot patch note article grid.")

    for item in grid.get("items", []):
        action_url = item.get("action", {}).get("payload", {}).get("url", "")
        title = item.get("title", "")
        if not action_url:
            continue
        if "패치" not in title and "patch" not in title.lower() and "patch" not in action_url:
            continue

        description = item.get("description", {})
        if isinstance(description, dict):
            description = strip_html(str(description.get("body", "")))
        else:
            description = strip_html(str(description or ""))

        image = item.get("media", {}).get("url") or item.get("imageMedia", {}).get("url") or ""
        return {
            "title": title,
            "url": absolute_url(action_url),
            "description": description,
            "published_at": item.get("publishedAt", ""),
            "image": image,
        }

    raise PatchNoteError("Could not find a Korean League of Legends patch note.")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, note: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "last_url": note["url"],
                "last_title": note["title"],
                "last_published_at": note["published_at"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def build_payload(note: dict[str, str]) -> dict[str, Any]:
    embed: dict[str, Any] = {
        "title": note["title"],
        "url": note["url"],
        "description": note["description"] or "한국어 공식 패치노트가 공개되었습니다.",
        "color": 0xC89B3C,
        "fields": [
            {
                "name": "확인하기",
                "value": f"[공식 한국어 패치노트 바로가기]({note['url']})",
                "inline": False,
            }
        ],
        "footer": {"text": "League of Legends 공식 한국어 패치노트"},
    }
    if note.get("published_at"):
        embed["timestamp"] = note["published_at"]
    if note.get("image"):
        embed["thumbnail"] = {"url": note["image"]}

    return {
        "username": "롤 패치노트 알림",
        "content": "새 한국어 리그 오브 레전드 패치노트가 공개되었습니다.",
        "embeds": [embed],
        "allowed_mentions": {"parse": []},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Post even when the latest URL matches state.")
    args = parser.parse_args()

    note = latest_patch_note()
    state = load_state(args.state)
    already_posted = state.get("last_url") == note["url"]

    if already_posted and not args.force:
        print(f"No new Korean patch note: {note['title']} ({note['url']})")
        return 0

    payload = build_payload(note)
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        raise PatchNoteError("DISCORD_WEBHOOK_URL is required.")

    request_json(webhook_url, payload)
    save_state(args.state, note)
    print(f"Posted Korean patch note: {note['title']} ({note['url']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PatchNoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
