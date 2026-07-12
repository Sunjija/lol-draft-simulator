from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from update_gol_tournament_meta import (  # noqa: E402
    build_champion_id_lookup,
    build_compact_meta,
    champion_id_for_gol_name,
    infer_roles,
)


class UpdateGolTournamentMetaTest(unittest.TestCase):
    def test_champion_id_mapping_handles_common_gol_names(self):
        roles = {
            "leeSin": ["JUNGLE"],
            "jarvaniv": ["JUNGLE"],
            "monkeyking": ["JUNGLE"],
            "ksante": ["TOP"],
            "renata": ["SUPPORT"],
        }
        lookup = build_champion_id_lookup(roles)

        self.assertEqual(champion_id_for_gol_name("LeeSin", lookup), "leeSin")
        self.assertEqual(champion_id_for_gol_name("JarvanIV", lookup), "jarvaniv")
        self.assertEqual(champion_id_for_gol_name("Wukong", lookup), "monkeyking")
        self.assertEqual(champion_id_for_gol_name("KSante", lookup), "ksante")
        self.assertEqual(champion_id_for_gol_name("RenataGlasc", lookup), "renata")

    def test_infer_roles_uses_existing_tournament_priors(self):
        roles = {"varus": ["ADC"]}
        priors = {"varus": {"TOP": 2, "JUNGLE": 0, "MID": 0, "ADC": 10, "SUPPORT": 0}}

        inferred = infer_roles("varus", 12, roles, priors)

        self.assertEqual(sum(inferred.values()), 12)
        self.assertGreaterEqual(inferred["ADC"], 9)
        self.assertGreaterEqual(inferred["TOP"], 2)

    def test_build_compact_meta_outputs_frontend_row_shape(self):
        tournaments = [
            {
                "name": "MSI 2026",
                "patch": "16.13",
                "stats": {"games": 10},
                "rows": [
                    {"champion": "Vi", "bans": 8, "picks": 2, "winRate": 50.0, "presence": 10},
                    {"champion": "LeeSin", "bans": 1, "picks": 5, "winRate": 60.0, "presence": 6},
                ],
            }
        ]
        roles = {"vi": ["JUNGLE"], "leeSin": ["JUNGLE"]}
        meta = build_compact_meta(tournaments, roles_by_id=roles, role_priors={})

        self.assertEqual(meta["metadata"]["games"], 10)
        self.assertEqual(meta["metadata"]["errors"], [])
        self.assertEqual(meta["champions"][0][0], "vi")
        self.assertEqual(len(meta["champions"][0]), 8)
        self.assertEqual(meta["champions"][0][7]["JUNGLE"], 2)


if __name__ == "__main__":
    unittest.main()
