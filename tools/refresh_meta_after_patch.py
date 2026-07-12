#!/usr/bin/env python3
"""Refresh draft meta data after a patch has had time to settle.

This workflow gate intentionally waits a few days after the official Korean
patch note timestamp before refreshing public meta status. Source-specific
collectors can be added behind this script without changing the GitHub Actions
schedule or app integration.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from post_korean_patch_notes import latest_patch_note


DEFAULT_STATE_PATH = Path(".cache/meta_refresh_state.json")
DEFAULT_STATUS_PATH = Path("data/meta_refresh_status.js")
SOURCE_LABEL = "OP.GG 등 공개 LoL 통계 데이터, 대회 메타 데이터 참고"
NORMALIZED_BY = "LoL Draft Simulator scoring model"


class MetaRefreshError(RuntimeError):
    pass


def parse_riot_timestamp(value: str) -> datetime:
    if not value:
        raise MetaRefreshError("Patch note does not include a published timestamp.")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MetaRefreshError(f"Could not parse patch note timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_existing_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.META_REFRESH_STATUS = "
    if not text.startswith(prefix):
        return {}
    payload = text[len(prefix) :]
    if payload.endswith(";"):
        payload = payload[:-1]
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {}


def verify_current_data_files() -> dict[str, Any]:
    required = {
        "leagueDraftContext": (Path("data/league_draft_context_compact.js"), "window.LEAGUE_DRAFT_CONTEXT"),
        "tournamentMeta": (Path("data/tournament_meta_2026_compact.js"), "window.TOURNAMENT_2026_META"),
    }
    result: dict[str, Any] = {}
    missing: list[str] = []

    for key, (path, marker) in required.items():
        if not path.exists():
            missing.append(str(path))
            continue
        text = path.read_text(encoding="utf-8")
        if marker not in text:
            raise MetaRefreshError(f"{path} does not expose {marker}.")
        result[key] = {"path": str(path).replace("\\", "/"), "bytes": len(text)}

    if missing:
        raise MetaRefreshError(f"Required data file(s) missing: {', '.join(missing)}")
    return result


def build_status(
    *,
    note: dict[str, str],
    due_at: datetime,
    delay_days: int,
    refreshed_at: datetime,
    data_files: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": 1,
        "status": "refreshed",
        "sourceLabel": SOURCE_LABEL,
        "normalizedBy": NORMALIZED_BY,
        "patchNote": {
            "title": note["title"],
            "url": note["url"],
            "publishedAt": note["published_at"],
            "dueAt": due_at.isoformat().replace("+00:00", "Z"),
        },
        "delayDays": delay_days,
        "refreshedAt": refreshed_at.isoformat().replace("+00:00", "Z"),
        "dataFiles": data_files,
        "notes": [
            "패치 직후 표본 흔들림을 줄이기 위해 패치노트 공개 후 72시간 뒤 메타 갱신을 시도합니다.",
            "추천 점수는 외부 통계를 그대로 노출하지 않고 내부 기준으로 정규화합니다.",
            "OP.GG 등 공개 LoL 통계 데이터와 대회 메타 데이터 기반 수집기를 이 단계에 연결할 수 있습니다.",
        ],
    }


def write_status_js(path: Path, status: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(status, ensure_ascii=False, indent=2)
    path.write_text(f"window.META_REFRESH_STATUS = {payload};\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay-days", type=int, default=3)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--status-path", type=Path, default=DEFAULT_STATUS_PATH)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.delay_days < 0:
        raise MetaRefreshError("--delay-days must be zero or greater.")

    note = latest_patch_note()
    published_at = parse_riot_timestamp(note["published_at"])
    due_at = published_at + timedelta(days=args.delay_days)
    now = datetime.now(timezone.utc)
    state = read_state(args.state)

    if now < due_at and not args.force:
        write_state(
            args.state,
            {
                **state,
                "lastSeenPatchUrl": note["url"],
                "lastSeenPatchTitle": note["title"],
                "nextEligibleAt": due_at.isoformat().replace("+00:00", "Z"),
            },
        )
        print(f"Meta refresh is not due yet: {note['title']} eligible at {due_at.isoformat()}")
        return 0

    if state.get("lastRefreshedPatchUrl") == note["url"] and not args.force:
        print(f"Meta refresh already completed for: {note['title']} ({note['url']})")
        return 0

    existing_status = read_existing_status(args.status_path)
    existing_patch_url = existing_status.get("patchNote", {}).get("url")
    if existing_patch_url == note["url"] and not args.force:
        write_state(
            args.state,
            {
                **state,
                "lastRefreshedPatchUrl": note["url"],
                "lastRefreshedPatchTitle": note["title"],
                "lastRefreshedAt": existing_status.get("refreshedAt"),
                "nextEligibleAt": due_at.isoformat().replace("+00:00", "Z"),
            },
        )
        print(f"Meta refresh already reflected in status file: {note['title']} ({note['url']})")
        return 0

    data_files = verify_current_data_files()
    status = build_status(
        note=note,
        due_at=due_at,
        delay_days=args.delay_days,
        refreshed_at=now,
        data_files=data_files,
    )

    if args.dry_run:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0

    write_status_js(args.status_path, status)
    write_state(
        args.state,
        {
            **state,
            "lastRefreshedPatchUrl": note["url"],
            "lastRefreshedPatchTitle": note["title"],
            "lastRefreshedAt": now.isoformat().replace("+00:00", "Z"),
            "nextEligibleAt": due_at.isoformat().replace("+00:00", "Z"),
        },
    )
    print(f"Updated meta refresh status for: {note['title']} ({note['url']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MetaRefreshError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
