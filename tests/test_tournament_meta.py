import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
META_PATH = ROOT / "data" / "tournament_meta_2026_20260710.json"


class TournamentMetaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        cls.by_id = {row[0]: row for row in cls.meta["champions"]}

    def test_tournament_coverage(self):
        self.assertGreaterEqual(self.meta["metadata"]["games"], 60)
        self.assertGreaterEqual(len(self.meta["champions"]), 100)
        self.assertEqual(self.meta["metadata"]["errors"], [])

    def test_high_priority_champions_are_present(self):
        self.assertGreaterEqual(self.by_id["orianna"][1] + self.by_id["orianna"][2], 40)
        self.assertGreaterEqual(self.by_id["vi"][1] + self.by_id["vi"][2], 40)

    def test_real_tournament_flex_roles_are_preserved(self):
        cassiopeia_roles = self.by_id["cassiopeia"][7]
        self.assertGreaterEqual(cassiopeia_roles["MID"], 2)
        self.assertGreaterEqual(cassiopeia_roles["ADC"], 2)


if __name__ == "__main__":
    unittest.main()

