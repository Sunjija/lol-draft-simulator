from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from probe_public_meta_sources import (  # noqa: E402
    parse_gol_weekly_tournaments,
    select_latest_tournaments,
    tournament_matches_patterns,
)


class PublicMetaProbeTest(unittest.TestCase):
    def test_parse_gol_weekly_tournaments(self):
        html = """
        <table>
          <tr>
            <th style="width:40%">Tournament</th>
            <th style="width:30%" class="text-center">Nb games</th>
            <th style="width:30%" class="text-center">Game version</th>
          </tr>
          <tr><td><a class='white_link' href='../tournament/tournament-stats/MSI%202026/'>MSI 2026</a></td><td class='text-center'>30</td><td class='text-center'>16.13</td></tr>
          <tr><td><a class='white_link' href='../tournament/tournament-stats/LCK%202026%20Rounds%201-2/'>LCK 2026 Rounds 1-2</a></td><td class='text-center'>12</td><td class='text-center'>16.13</td></tr>
        </table>
        """
        rows = parse_gol_weekly_tournaments(html)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "MSI 2026")
        self.assertEqual(rows[0]["games"], 30)
        self.assertEqual(rows[0]["patch"], "16.13")
        self.assertIn("/tournament-stats/MSI%202026/", rows[0]["statsUrl"])
        self.assertIn("/tournament-picksandbans/MSI%202026/", rows[0]["picksBansUrl"])
        self.assertNotIn("/champion/tournament/", rows[0]["picksBansUrl"])

    def test_select_latest_tournaments_filters_patterns_and_min_games(self):
        tournaments = [
            {"name": "MSI 2026", "games": 30},
            {"name": "LCK 2026 Rounds 1-2", "games": 12},
            {"name": "Prime League 2026 Summer", "games": 40},
            {"name": "First Stand 2026", "games": 5},
        ]
        selected = select_latest_tournaments(
            tournaments,
            patterns=["MSI", "LCK", "First Stand"],
            min_games=10,
            limit=4,
        )

        self.assertEqual([row["name"] for row in selected], ["MSI 2026", "LCK 2026 Rounds 1-2"])

    def test_tournament_pattern_matching_is_case_insensitive(self):
        self.assertTrue(tournament_matches_patterns("2026 Season World Championship", ["world championship"]))
        self.assertTrue(tournament_matches_patterns("LCK 2026 Road to MSI", ["road to msi"]))
        self.assertFalse(tournament_matches_patterns("Prime League 2026 Summer", ["LCK"]))


if __name__ == "__main__":
    unittest.main()
