import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from update_opgg_league_context import (  # noqa: E402
    build_role_stats,
    filter_role_rows,
    patch_from_opgg_rows,
)


class UpdateOpggLeagueContextTest(unittest.TestCase):
    def test_filter_role_rows_requires_pick_rate_and_play_count(self):
        rows = [
            {"key": "locke", "name": "Locke", "play": 100000, "winRate": 46.0, "pickRate": 0.2, "banRate": 80.0},
            {"key": "yone", "name": "Yone", "play": 200000, "winRate": 50.5, "pickRate": 9.0, "banRate": 12.0},
        ]
        lookup = {"locke": "locke", "yone": "yone"}

        filtered = filter_role_rows(rows, lookup=lookup, min_pick_rate=0.45, min_play=3000, max_rows=10)

        self.assertEqual([row["championId"] for row in filtered], ["yone"])

    def test_build_role_stats_preserves_existing_counters(self):
        opgg_by_position = {
            "top": [{"key": "yone", "name": "Yone", "play": 200000, "winRate": 50.5, "pickRate": 9.0, "banRate": 12.0}],
            "jungle": [],
            "mid": [],
            "adc": [],
            "support": [],
        }
        context = {"roleStats": {"TOP": [["yone", 1, 1, 50.0, 8.0, 10.0, ["vex"], "yone"]]}}
        lookup = {"yone": "yone"}

        role_stats = build_role_stats(
            opgg_by_position,
            context=context,
            lookup=lookup,
            min_pick_rate=0.45,
            min_play=3000,
            max_rows=10,
        )

        self.assertEqual(role_stats["TOP"][0][0], "yone")
        self.assertEqual(role_stats["TOP"][0][6], ["vex"])

    def test_patch_from_opgg_rows_reads_image_version(self):
        rows = [{"image": "https://opgg-static.akamaized.net/meta/images/lol/16.13.1/champion/Yone.png"}]

        self.assertEqual(patch_from_opgg_rows(rows), "16.13")


if __name__ == "__main__":
    unittest.main()
