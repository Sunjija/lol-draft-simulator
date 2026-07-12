import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class ServerScoringTest(unittest.TestCase):
    def test_more_games_raise_comfort_with_same_record(self):
        one_game = server.comfort_from_record(1, 1, 1.0, 8, 1, 1.0)
        ten_games = server.comfort_from_record(10, 10, 8.0, 8, 10, 8.0)
        self.assertGreater(ten_games, one_game)

    def test_small_sample_win_rate_is_capped(self):
        perfect = server.comfort_from_record(1, 1, 1.0, 0, 1, 1.0)
        loss = server.comfort_from_record(1, 0, 1.0, 0, 1, 1.0)
        self.assertLessEqual(perfect - loss, 5)

    def test_match_cache_is_bounded(self):
        self.assertEqual(server.MATCH_CACHE_LIMIT, 1000)

    def test_riot_analysis_uses_solo_ranked_20_games(self):
        calls = []
        original = server.analyze_player
        try:
            def fake_analyze_player(player, platform, match_count, queue):
                calls.append((player, platform, match_count, queue))
                return {"riotId": player["riotId"], "pool": [], "stats": []}

            server.analyze_player = fake_analyze_player
            team_result = server.analyze_team({
                "platform": "kr",
                "matchCount": 50,
                "queue": "",
                "players": [{"riotId": "name#KR1", "role": "TOP"}],
            })
            single_result = server.analyze_single_player({
                "platform": "kr",
                "matchCount": 10,
                "queue": "440",
                "player": {"riotId": "name#KR1", "role": "TOP"},
            })
        finally:
            server.analyze_player = original

        self.assertTrue(team_result["players"][0]["ok"])
        self.assertTrue(single_result["ok"])
        self.assertEqual(calls[0][2:], (20, "420"))
        self.assertEqual(calls[1][2:], (20, "420"))


if __name__ == "__main__":
    unittest.main()
