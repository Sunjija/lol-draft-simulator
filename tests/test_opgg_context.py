import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONTEXT_PATH = ROOT / "data" / "opgg_draft_context_kr_emerald_plus_20260710.json"


class OpggContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.context = json.loads(CONTEXT_PATH.read_text(encoding="utf-8"))

    def test_role_coverage(self):
        expected_minimums = {"TOP": 45, "JUNGLE": 45, "MID": 40, "ADC": 25, "SUPPORT": 40}
        for role, minimum in expected_minimums.items():
            self.assertGreaterEqual(len(self.context["roleStats"][role]), minimum)

    def test_synergy_coverage(self):
        self.assertGreaterEqual(len(self.context["synergies"]["jungleMid"]), 400)
        self.assertGreaterEqual(len(self.context["synergies"]["topJungle"]), 400)
        self.assertGreaterEqual(len(self.context["synergies"]["botDuo"]), 250)

    def test_synergy_scores_are_restrained(self):
        rows = sum(self.context["synergies"].values(), [])
        self.assertTrue(rows)
        self.assertTrue(all(38 <= row[2] <= 68 for row in rows))

    def test_aliases_match_app_ids(self):
        jungle_ids = {row[0] for row in self.context["roleStats"]["JUNGLE"]}
        self.assertIn("leeSin", jungle_ids)
        self.assertNotIn("leesin", jungle_ids)

    def test_collection_has_no_errors(self):
        self.assertEqual(self.context["metadata"]["errors"], [])


if __name__ == "__main__":
    unittest.main()
