# DraftLab

내전, 격전, 팀게임 연습용 밴픽 보조 도구입니다. 팀원의 챔피언 폭, 라인 정보, 조합 태그, 대회 메타 데이터, 상성 데이터를 바탕으로 픽과 밴 후보를 추천합니다.

공개 베타 버전은 Riot API 없이도 수기 챔피언 풀 입력만으로 사용할 수 있도록 구성되어 있습니다.

## 사용 방법

정적 서버로 바로 실행할 수 있습니다.

```powershell
python -m http.server 8792
```

브라우저에서 아래 주소로 접속합니다.

```text
http://127.0.0.1:8792/
```

GitHub Pages, Cloudflare Pages, Netlify, Vercel 같은 정적 호스팅에서는 `index.html`, `assets/`, `data/` 폴더를 배포하면 기본 기능이 동작합니다.

## 공개 URL

```text
https://draftlab-henna.vercel.app/
```

검색 노출을 빠르게 요청하려면 Google Search Console에서 위 URL을 URL prefix 속성으로 추가하고, 아래 sitemap을 제출합니다.

```text
https://draftlab-henna.vercel.app/sitemap.xml
```

기본 검색 노출 파일:

- `robots.txt`
- `sitemap.xml`
- `site.webmanifest`
- `assets/brand/draftlab-icon.svg`
- `assets/brand/draftlab-icon-192.png`
- `assets/brand/draftlab-icon-512.png`

## 주요 기능

- 블루/레드 사이드 밴픽 보드
- 하드 피어리스 ON/OFF
- 수기 챔피언 풀 입력 및 편집
- 챔피언 숙련도: 장인, 잘함, 보통, 가능
- 팀게임 기본 챔피언 풀 프리셋
- 상대 라인 정보: 확정, 추정, 불명
- 라인전, 조합, 선픽 안정성, 스왑 가치, 피어리스 리스크 반영
- 바텀 듀오, 정글-미드, 돌진/받아치기 태그 기반 시너지 반영
- 창 공유 기반 라이브 캡처 Beta

## 개발자 모드

로컬에서만 Riot API 자동 분석과 로컬 BGM 설정을 테스트할 수 있습니다.

```powershell
python server.py
```

브라우저에서 아래 주소로 접속하면 개발자용 패널이 표시됩니다.

```text
http://127.0.0.1:8792/?dev=1
```

공개 베타 기본 화면에서는 API key 입력과 로컬 BGM 기능을 숨깁니다. 공개 서비스에서 Riot API를 사용하려면 Riot Developer Portal 정책에 맞는 키, HTTPS, 서버 측 rate limit, 개인정보 안내가 필요합니다.

## 한국어 패치노트 알림

GitHub Actions가 공식 한국어 리그 오브 레전드 패치노트 페이지를 6시간마다 확인하고, 새 패치노트가 있으면 Discord 웹후크로 전송합니다.

필요한 저장소 Secret:

```text
DISCORD_PATCH_NOTES_WEBHOOK_URL
```

워크플로우 파일:

```text
.github/workflows/korean-patch-notes.yml
```

수동 실행은 GitHub 저장소의 Actions 탭에서 `Korean Patch Notes` 워크플로우를 선택해 실행하면 됩니다.

## 패치 후 메타 갱신

패치 직후에는 챔피언 통계 표본이 흔들릴 수 있으므로, `Meta Refresh After Patch` 워크플로우는 최신 패치노트 공개 시각 기준 72시간이 지난 뒤 메타 상태 파일과 대회 메타 데이터를 갱신합니다.

워크플로우 파일:

```text
.github/workflows/meta-refresh-after-patch.yml
```

현재 공개 화면에는 아래 기준으로 출처를 안내합니다.

```text
OP.GG 등 공개 LoL 통계 데이터, 대회 메타 데이터 참고
```

현재는 GOL.GG 최신 주차 대회 목록에서 MSI, LCK, First Stand, Worlds 계열 대회를 우선 필터링하고, 선택된 대회의 picks/bans 데이터를 `data/tournament_meta_2026_compact.js`로 정규화합니다.

OP.GG 라인별 챔피언 통계는 pick rate와 play count 기준을 통과한 챔피언만 `data/league_draft_context_compact.js`의 role stats에 반영합니다. 기존 카운터/시너지 데이터는 보존하고, ban rate는 보조 신호로만 사용합니다.

실제 추천 점수는 외부 통계를 그대로 노출하지 않고, 앱 내부 계산식에 맞게 정규화합니다.

## 데이터

공개 저장소에는 실행에 필요한 압축 데이터만 포함합니다.

- `data/league_draft_context_compact.js`: 챔피언 태그, 라인별 경향, 조합 태그
- `data/league_top_lane_matchups_compact.js`: 탑 라인 상성 데이터
- `data/league_mid_lane_matchups_compact.js`: 미드 라인 상성 데이터
- `data/tournament_meta_2026_compact.js`: 2026 대회 메타 요약 데이터
- `data/meta_refresh_status.js`: 패치 후 메타 갱신 상태와 출처 안내

## 테스트

```powershell
python -m unittest discover -s tests
```

브라우저에서는 URL에 `?selftest=1`을 붙여 주요 추천 시나리오를 점검할 수 있습니다.

## 고지

이 프로젝트는 Riot Games와 공식 제휴 또는 승인을 받은 제품이 아닙니다. League of Legends 및 Riot Games 관련 명칭과 자산의 권리는 각 소유자에게 있습니다.
