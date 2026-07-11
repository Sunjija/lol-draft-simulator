from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")


class FrontendContractsTest(unittest.TestCase):
    def test_ranked_solo_is_default_queue(self):
        self.assertIn('<option value="420" selected>솔로 랭크</option>', INDEX)

    def test_2026_msi_sample_rosters_are_current(self):
        for riot_id in ("Peyz#T1", "Kanavi#HLE", "Gumayusi#HLE"):
            self.assertIn(riot_id, INDEX)
        for stale_id in ('"Peanut#HLE", "JUNGLE"', '"Viper#HLE", "ADC"'):
            self.assertNotIn(stale_id, INDEX)

    def test_displayed_pool_score_uses_real_comfort(self):
        self.assertIn("Math.round(comfortScore(p, id))", INDEX)
        self.assertNotIn("100 - i * 10", INDEX)

    def test_pick_likelihood_is_not_rank_only_or_100(self):
        self.assertIn("sampleConfidence", INDEX)
        self.assertIn("92,", INDEX)
        self.assertNotIn("100 - index * 11", INDEX)

    def test_final_score_does_not_reapply_peak_bonus(self):
        start = INDEX.index("function calibratedPickScore")
        end = INDEX.index("function temperSynergyByComfort", start)
        body = INDEX[start:end]
        self.assertNotIn("const peak", body)
        self.assertNotIn("score +=", body)

    def test_emergency_candidate_discount_is_applied_once(self):
        start = INDEX.index("function recommendPicks")
        end = INDEX.index("function uniqueChampionCandidates", start)
        body = INDEX[start:end]
        self.assertNotIn("score = Math.min(score * 0.82, 72)", body)
        self.assertIn("score = calibratedPickScore(score, parts, p.role, hasPoolEvidence)", body)

    def test_browser_scenario_suite_is_present(self):
        self.assertIn("function runDraftSelfTests()", INDEX)
        self.assertIn("확정된 상대 서폿 라인 재밴 금지", INDEX)

    def test_league_role_and_synergy_context_is_connected(self):
        self.assertIn('data/league_draft_context_compact.js', INDEX)
        self.assertIn("leagueRoleStatsMaps", INDEX)
        self.assertIn("empiricalSynergyMaps", INDEX)

    def test_msi_tournament_meta_is_connected(self):
        self.assertIn('data/gol_msi_2026_meta_compact.js', INDEX)
        self.assertIn("golMsiMetaMap", INDEX)
        self.assertIn("golMsiBlindScore", INDEX)

    def test_shallow_draft_lookahead_is_connected(self):
        for function_name in (
            "teamFlexProfile",
            "pickOrderProtectionScore",
            "predictedEnemyResponses",
            "bestReplyScoreAfterResponse",
            "shallowDraftForesightScore",
        ):
            self.assertIn(f"function {function_name}", INDEX)
        self.assertIn("clamp((foresight - 50) * 0.10, -4, 4)", INDEX)

    def test_flex_requires_team_pool_evidence(self):
        start = INDEX.index("function teamFlexProfile")
        end = INDEX.index("function swapValueScore", start)
        body = INDEX[start:end]
        self.assertIn("hasPlayerChampionEvidence(candidate, champ.id)", body)
        self.assertIn("options.length < 2", body)

    def test_flex_matchup_keeps_role_uncertainty(self):
        self.assertIn("function plausibleRolesForPick", INDEX)
        self.assertIn("function roleAssignmentLikelihood", INDEX)
        self.assertIn("direct.score * enemySameRole.confidence", INDEX)

    def test_pool_depth_risk_protects_shallow_champion_pools(self):
        for function_name in (
            "availablePlayerPool",
            "playerPoolDepthProfile",
            "poolRiskScore",
        ):
            self.assertIn(f"function {function_name}", INDEX)
        start = INDEX.index("function pickOrderProtectionScore")
        end = INDEX.index("function predictedEnemyResponses", start)
        body = INDEX[start:end]
        self.assertIn("ownProfile.strongRemaining <= 1", body)
        self.assertIn("ownProfile.remaining <= futureBans + 1", body)

    def test_second_phase_bans_use_pool_depth_after_candidate_ban(self):
        start = INDEX.index("function phaseTargetBanScore")
        end = INDEX.index("function weightedBanIntentScore", start)
        body = INDEX[start:end]
        self.assertIn("bannedChampionId", body)
        self.assertIn("unavailable.add(bannedChampionId)", body)
        self.assertIn("poolRiskScore(targetPlayer", body)

    def test_side_specific_late_pick_strategies_are_distinct(self):
        for strategy_id in ("redFourthFlex", "blueCompletionDefense", "redFiveCounter"):
            self.assertIn(f'id: "{strategy_id}"', INDEX)
        self.assertNotIn('id: side === "RED" ? "redFiveCounter" : "lastPickCounter"', INDEX)
        self.assertIn('step.index === 16', INDEX)
        self.assertIn('[17, 18].includes(step.index)', INDEX)
        self.assertIn('step.index === 19', INDEX)


if __name__ == "__main__":
    unittest.main()
