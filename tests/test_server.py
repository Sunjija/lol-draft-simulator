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


if __name__ == "__main__":
    unittest.main()
