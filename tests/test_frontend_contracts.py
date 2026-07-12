from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "index.html").read_text(encoding="utf-8")
ROBOTS = (ROOT / "robots.txt").read_text(encoding="utf-8")
SITEMAP = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
LOGO_PATH = ROOT / "assets" / "brand" / "draft-logo.png"


class FrontendContractsTest(unittest.TestCase):
    def test_public_seo_metadata_is_present(self):
        public_url = "https://sunjija.github.io/lol-draft-simulator/"
        self.assertIn("<title>LoL 밴픽 시뮬레이터 - 팀게임 픽밴 추천 도구</title>", INDEX)
        self.assertIn('name="description"', INDEX)
        self.assertIn(f'<link rel="canonical" href="{public_url}" />', INDEX)
        self.assertIn('"@type": "WebApplication"', INDEX)
        self.assertIn("Sitemap: https://sunjija.github.io/lol-draft-simulator/sitemap.xml", ROBOTS)
        self.assertIn(f"<loc>{public_url}</loc>", SITEMAP)

    def test_public_beta_loads_champion_icons_without_local_api(self):
        self.assertIn("function loadPublicChampionIcons", INDEX)
        self.assertIn("https://ddragon.leagueoflegends.com/api/versions.json", INDEX)
        self.assertIn("loadChampionCatalog();", INDEX)
        self.assertIn("await loadPublicChampionIcons();", INDEX)

    def test_landing_page_and_brand_asset_are_present(self):
        self.assertTrue(LOGO_PATH.exists())
        self.assertGreater(LOGO_PATH.stat().st_size, 100_000)
        self.assertIn('class="landing-active"', INDEX)
        self.assertIn('id="landingView"', INDEX)
        self.assertIn('id="enterSimulator"', INDEX)
        self.assertIn('assets/brand/draft-logo.png', INDEX)
        self.assertIn("감으로만 하던 밴픽", INDEX)
        self.assertIn("Discord 준비중", INDEX)

    def test_primary_ui_order_matches_draft_workflow(self):
        draft_tab = INDEX.index('data-view="draftView"')
        pool_tab = INDEX.index('data-view="poolsView"')
        setup_tab = INDEX.index('data-view="setupView"')
        self.assertLess(draft_tab, pool_tab)
        self.assertLess(pool_tab, setup_tab)

        setup_start = INDEX.index('<section id="setupView"')
        our_team = INDEX.index('<div class="panel-title">우리 팀</div>', setup_start)
        bulk_names = INDEX.index('<div class="panel-title">Riot ID/이름 붙여넣기</div>', setup_start)
        global_settings = INDEX.index('<div class="panel-title">전체 설정</div>', setup_start)
        api_settings = INDEX.index('<div class="panel-title">선택 기능: Riot API 자동 채우기</div>', setup_start)
        self.assertLess(our_team, bulk_names)
        self.assertLess(bulk_names, global_settings)
        self.assertLess(global_settings, api_settings)
        self.assertIn('id="autoPickCurrent"', INDEX[INDEX.index('<section id="draftView"'):INDEX.index('<section id="setupView"')])

    def test_riot_api_analysis_is_split_and_fixed_to_solo_20(self):
        self.assertIn("솔로 랭크 최근 20경기", INDEX)
        self.assertIn("우리 팀 순차 분석", INDEX)
        self.assertIn("상대 팀 순차 분석", INDEX)
        self.assertIn("양 팀 순차 분석", INDEX)
        self.assertIn('const RIOT_ANALYSIS_MATCH_COUNT = 20', INDEX)
        self.assertIn('const RIOT_ANALYSIS_QUEUE = "420"', INDEX)
        self.assertIn("function analyzeSingleRiotPlayer", INDEX)
        self.assertIn('fetch("/api/analyze-player"', INDEX)
        self.assertIn("RIOT_API_PLAYERS_PER_WINDOW", INDEX)
        self.assertNotIn('id="riotMatchCount"', INDEX)
        self.assertNotIn('id="riotQueue"', INDEX)

    def test_2026_msi_sample_rosters_are_current(self):
        for riot_id in ("Peyz#T1", "Kanavi#HLE", "Gumayusi#HLE"):
            self.assertIn(riot_id, INDEX)
        for stale_id in ('"Peanut#HLE", "JUNGLE"', '"Viper#HLE", "ADC"'):
            self.assertNotIn(stale_id, INDEX)

    def test_displayed_pool_score_uses_real_comfort(self):
        self.assertIn("poolChampionRow", INDEX)
        self.assertIn("player.poolScores?.[championId] ?? comfortScore(player, championId)", INDEX)
        self.assertIn("숙련도 ${Math.round(score)}", INDEX)
        self.assertNotIn("100 - i * 10", INDEX)

    def test_manual_pool_mastery_editor_is_present(self):
        self.assertIn("MANUAL_MASTERY_LEVELS", INDEX)
        self.assertIn('expert: { label: "장인", score: 100 }', INDEX)
        self.assertIn('strong: { label: "잘함", score: 84 }', INDEX)
        self.assertIn('normal: { label: "보통", score: 70 }', INDEX)
        self.assertIn('playable: { label: "가능", score: 55 }', INDEX)
        self.assertIn("function setManualPoolMastery", INDEX)
        self.assertIn("function applyManualPoolText", INDEX)
        self.assertIn("pool-edit-details", INDEX)
        self.assertIn("poolUiState.openEditors", INDEX)
        self.assertIn("data-editor-key", INDEX)

    def test_pool_presets_and_clear_are_manual_pool_defaults(self):
        self.assertIn("POOL_PRESETS", INDEX)
        self.assertIn('label: "상위권 팀게임 기본"', INDEX)
        self.assertIn('label: "라인전 주도권"', INDEX)
        self.assertIn('label: "대회 메타형"', INDEX)
        self.assertIn('label: "피어리스 넓은 풀"', INDEX)
        self.assertIn('mastery: "normal"', INDEX)
        self.assertIn("function applySelectedPoolPreset", INDEX)
        self.assertIn("function clearSelectedPoolTarget", INDEX)
        self.assertIn("여러 챔프폭 프리셋 보통 숙련도", INDEX)
        self.assertIn("챔프폭 비우기", INDEX)
        self.assertIn("poolInputStatusHtml", INDEX)
        high_tier_start = INDEX.index('highTierTeam: {')
        high_tier_end = INDEX.index('lanePriority: {', high_tier_start)
        high_tier_body = INDEX[high_tier_start:high_tier_end]
        self.assertIn('TOP: ["ksante", "jax", "renekton", "gnar", "rumble", "jayce", "ambessa", "ornn", "camille"]', high_tier_body)
        self.assertNotIn('"poppy"', high_tier_body[high_tier_body.index("TOP:"):high_tier_body.index("JUNGLE:")])

    def test_user_facing_noise_is_removed_from_pool_cards(self):
        self.assertNotIn("프로 표본", INDEX)
        self.assertNotIn("해당 라인 기록 없음", INDEX)
        self.assertNotIn("경기 반영", INDEX)
        self.assertNotIn("샘플/수동", INDEX)
        self.assertNotIn("검증 샘플", INDEX)
        self.assertNotIn("샘플 팀/메타", INDEX)
        self.assertIn("기본 데이터 다시 채우기", INDEX)
        self.assertIn("function analysisSummary", INDEX)

    def test_enemy_line_certainty_is_connected(self):
        self.assertIn("ENEMY_LINE_CERTAINTY", INDEX)
        self.assertIn('enemyLineCertainty: "estimated"', INDEX)
        self.assertIn("function lineCertaintyForSide", INDEX)
        self.assertIn('state.enemyLineCertainty = btn.dataset.certainty', INDEX)
        self.assertIn("상대 라인 확실도 반영", INDEX)

    def test_optional_api_and_fearless_copy_are_connected(self):
        self.assertIn("공개 베타 · 수기 챔프폭 노트 기반 팀게임 밴픽 보조", INDEX)
        self.assertIn("const LOCAL_DEV_FEATURES", INDEX)
        self.assertIn('class="panel dev-only" id="apiSettingsPanel" hidden', INDEX)
        self.assertIn('class="bgm-controls local-only"', INDEX)
        self.assertIn("공개 베타에서는 API 자동 채우기를 숨기고", INDEX)
        self.assertIn("function parsePlayerNames", INDEX)
        self.assertIn("Riot ID 또는 이름", INDEX)
        self.assertIn("Riot ID/이름 붙여넣기 파싱", INDEX)
        self.assertIn("우리 팀 명단 적용", INDEX)
        self.assertIn("weights.fearless = Math.max(weights.fearless, 4)", INDEX)
        self.assertIn("피어리스 ON/OFF 가중치", INDEX)
        self.assertIn("피어리스 ON/OFF 후보 제외", INDEX)

    def test_rank_input_does_not_use_lp(self):
        self.assertNotIn("rankLp", INDEX)
        self.assertNotIn("leaguePoints", INDEX)
        self.assertNotIn("placeholder=\"LP\"", INDEX)

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
        self.assertIn('data/tournament_meta_2026_compact.js', INDEX)
        self.assertIn("tournamentMetaMap", INDEX)
        self.assertIn("tournamentBlindScore", INDEX)

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

