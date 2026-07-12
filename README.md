# LoL Draft Simulator

팀게임, 내전, 격전 연습용 밴픽 보조 도구입니다. 공개 베타 버전은 Riot API 없이 수기 챔프폭, 숙련도, 라인 정보, 대회/팀게임 메타 데이터, 조합 규칙을 바탕으로 픽과 밴 후보를 추천합니다.

## 공개 베타 사용법

정적 웹으로 바로 배포할 수 있습니다.

```powershell
python -m http.server 8792
```

브라우저에서 `http://127.0.0.1:8792/`로 접속합니다.

GitHub Pages, Cloudflare Pages, Netlify, Vercel 같은 정적 호스팅에도 `index.html`, `assets/`, `data/` 폴더만 올리면 기본 기능이 동작합니다.

## 검색 노출

기본 공개 URL은 아래 주소를 기준으로 SEO 메타태그, canonical URL, sitemap을 설정했습니다.

```text
https://sunjija.github.io/lol-draft-simulator/
```

Google 검색 노출을 빠르게 요청하려면 Google Search Console에서 이 URL을 속성으로 추가하고, `sitemap.xml`을 제출합니다.

```text
https://sunjija.github.io/lol-draft-simulator/sitemap.xml
```

커스텀 도메인을 연결하면 `index.html`, `robots.txt`, `sitemap.xml`의 URL을 새 도메인으로 바꾸면 됩니다.

## 주요 기능

- 블루/레드 사이드 밴픽 보드
- 하드 피어리스 ON/OFF
- 선수별 챔프폭 수기 입력
- 챔프 숙련도: 장인, 잘함, 보통, 가능
- 팀게임용 챔프폭 프리셋
- 상대 라인 정보: 확정, 추정, 불명
- 라인전, 조합, 선픽 안정성, 스왑 가치, 피어리스 리스크 반영
- 바텀 듀오, 정글-미드, 돌진/받아치기 태그 기반 시너지 반영
- 창 공유 기반 라이브 캡쳐 Beta

## 개발자 모드

로컬에서만 Riot API 자동 채우기와 로컬 BGM 스캔을 테스트할 수 있습니다.

```powershell
python server.py
```

브라우저에서 `http://127.0.0.1:8792/?dev=1`로 접속하면 개발자 전용 패널이 표시됩니다.

공개 베타 기본 화면에서는 API key 입력과 로컬 BGM 기능을 숨깁니다. 공개 서비스에서 Riot API를 사용하려면 Riot Developer Portal의 정책에 맞는 production key, HTTPS, 서버 측 rate limit, 개인정보 안내가 필요합니다.

## 데이터

앱 실행에 필요한 정적 데이터만 포함합니다.

- `data/league_draft_context_compact.js`: 챔피언 티어, 라인별 경향, 조합 태그
- `data/league_top_lane_matchups_compact.js`: 탑 라인 상성 데이터
- `data/league_mid_lane_matchups_compact.js`: 미드 라인 상성 데이터
- `data/tournament_meta_2026_compact.js`: 2026 대회 메타 요약 데이터

## 테스트

```powershell
python -m unittest discover -s tests
```

브라우저에서는 `?selftest=1`을 붙여 주요 추천 시나리오를 점검할 수 있습니다.

## 고지

이 프로젝트는 Riot Games와 공식 제휴 또는 승인을 받은 제품이 아닙니다. League of Legends 및 Riot Games 관련 명칭과 자산의 권리는 각 소유자에게 있습니다.
