from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from refresh_meta_after_patch import build_status, parse_riot_timestamp, read_existing_status  # noqa: E402


class MetaRefreshAfterPatchTest(unittest.TestCase):
    def test_parse_riot_timestamp_normalizes_utc(self):
        parsed = parse_riot_timestamp("2026-06-23T18:00:00.000Z")
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.isoformat(), "2026-06-23T18:00:00+00:00")

    def test_build_status_keeps_source_label_and_delay(self):
        note = {
            "title": "리그 오브 레전드 26.13 패치 노트",
            "url": "https://www.leagueoflegends.com/ko-kr/news/game-updates/league-of-legends-patch-26-13-notes",
            "published_at": "2026-06-23T18:00:00.000Z",
        }
        due_at = datetime(2026, 6, 26, 18, 0, tzinfo=timezone.utc)
        refreshed_at = datetime(2026, 6, 27, 0, 0, tzinfo=timezone.utc)
        status = build_status(
            note=note,
            due_at=due_at,
            delay_days=3,
            refreshed_at=refreshed_at,
            data_files={"leagueDraftContext": {"path": "data/league_draft_context_compact.js", "bytes": 10}},
        )

        self.assertEqual(status["status"], "refreshed")
        self.assertEqual(status["delayDays"], 3)
        self.assertIn("OP.GG 등 공개 LoL 통계 데이터", status["sourceLabel"])
        self.assertEqual(status["patchNote"]["dueAt"], "2026-06-26T18:00:00Z")

    def test_read_existing_status_extracts_window_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "meta_refresh_status.js"
            path.write_text(
                'window.META_REFRESH_STATUS = {"patchNote":{"url":"https://example.test/patch"}};\n',
                encoding="utf-8",
            )
            status = read_existing_status(path)

        self.assertEqual(status["patchNote"]["url"], "https://example.test/patch")


if __name__ == "__main__":
    unittest.main()
