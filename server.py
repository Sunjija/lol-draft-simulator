from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import quote, unquote, urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from collections import OrderedDict
import json
import math
import mimetypes
import os
import time
import unicodedata


HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8792"))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(ROOT_DIR, "work", "lol-draft-simulator")
KEY_FILE = os.path.join(CONFIG_DIR, "riot_api_key.txt")
BGM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "bgm")
AUDIO_EXTENSIONS = {".mp3", ".ogg", ".wav", ".m4a", ".flac", ".aac", ".webm"}


def load_saved_api_key():
    env_key = os.environ.get("RIOT_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        with open(KEY_FILE, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        return ""


API_KEY = load_saved_api_key()
MATCH_CACHE_LIMIT = 1000
MATCH_CACHE = OrderedDict()
DD_CACHE = {"loaded_at": 0, "by_key": {}, "by_num": {}, "version": ""}


APP_CHAMPION_IDS = {
    "aatrox": "aatrox",
    "ambessa": "ambessa",
    "aurora": "aurora",
    "ornn": "ornn",
    "ksante": "ksante",
    "rumble": "rumble",
    "jax": "jax",
    "gnar": "gnar",
    "renekton": "renekton",
    "camille": "camille",
    "vi": "vi",
    "sejuani": "sejuani",
    "maokai": "maokai",
    "xinzhao": "xinZhao",
    "leesin": "leeSin",
    "viego": "viego",
    "brand": "brand",
    "nidalee": "nidalee",
    "ivern": "ivern",
    "poppy": "poppy",
    "azir": "azir",
    "orianna": "orianna",
    "taliyah": "taliyah",
    "syndra": "syndra",
    "ahri": "ahri",
    "yone": "yone",
    "akali": "akali",
    "tristana": "tristana",
    "hwei": "hwei",
    "lissandra": "lissandra",
    "zeri": "zeri",
    "kaisa": "kaisa",
    "varus": "varus",
    "ashe": "ashe",
    "kalista": "kalista",
    "ezreal": "ezreal",
    "jinx": "jinx",
    "aphelios": "aphelios",
    "caitlyn": "caitlyn",
    "draven": "draven",
    "rell": "rell",
    "rakan": "rakan",
    "nautilus": "nautilus",
    "leona": "leona",
    "milio": "milio",
    "lulu": "lulu",
    "janna": "janna",
    "blitzcrank": "blitzcrank",
    "pyke": "pyke",
    "bard": "bard",
}

STATIC_NUMERIC_TO_APP = {
    266: "aatrox",
    799: "ambessa",
    893: "aurora",
    516: "ornn",
    897: "ksante",
    68: "rumble",
    24: "jax",
    150: "gnar",
    58: "renekton",
    164: "camille",
    254: "vi",
    113: "sejuani",
    57: "maokai",
    5: "xinZhao",
    64: "leeSin",
    234: "viego",
    63: "brand",
    76: "nidalee",
    427: "ivern",
    78: "poppy",
    268: "azir",
    61: "orianna",
    163: "taliyah",
    134: "syndra",
    103: "ahri",
    777: "yone",
    84: "akali",
    18: "tristana",
    910: "hwei",
    127: "lissandra",
    221: "zeri",
    145: "kaisa",
    110: "varus",
    22: "ashe",
    429: "kalista",
    81: "ezreal",
    222: "jinx",
    523: "aphelios",
    51: "caitlyn",
    119: "draven",
    526: "rell",
    497: "rakan",
    111: "nautilus",
    89: "leona",
    902: "milio",
    117: "lulu",
    40: "janna",
    53: "blitzcrank",
    555: "pyke",
    432: "bard",
}

QUEUE_LABELS = {
    400: "일반 교차 선택",
    420: "솔로 랭크",
    430: "일반 비공개 선택",
    440: "자유 랭크",
    450: "무작위 총력전",
    490: "빠른 대전",
}


def normalize(value):
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def app_id_from_riot(champion_name=None, champion_num=None):
    if champion_name:
        direct = APP_CHAMPION_IDS.get(normalize(champion_name))
        if direct:
            return direct
    data = get_ddragon_data()
    if champion_num is not None:
        key = data["by_num"].get(str(champion_num))
        if key:
            return APP_CHAMPION_IDS.get(normalize(key)) or normalize(key)
        return STATIC_NUMERIC_TO_APP.get(int(champion_num)) if str(champion_num).isdigit() else None
    return normalize(champion_name) if champion_name else None


def champion_display_name(app_id, champion_num=None, champion_name=None):
    data = get_ddragon_data()
    key = data["by_num"].get(str(champion_num)) if champion_num is not None else None
    if key and data["by_key"].get(key, {}).get("name"):
        return data["by_key"][key]["name"]
    if champion_name:
        by_name = data["by_key"].get(champion_name, {})
        if by_name.get("name"):
            return by_name["name"]
    for champ in data["by_key"].values():
        if normalize(champ.get("id")) == app_id:
            return champ.get("name") or champ.get("id") or app_id
    return champion_name or app_id


def get_ddragon_data():
    now = time.time()
    if DD_CACHE["by_key"] and now - DD_CACHE["loaded_at"] < 60 * 60 * 12:
        return DD_CACHE
    try:
        versions = http_json("https://ddragon.leagueoflegends.com/api/versions.json", api_key_required=False)
        version = versions[0]
        payload = http_json(
            f"https://ddragon.leagueoflegends.com/cdn/{version}/data/ko_KR/champion.json",
            api_key_required=False,
        )
        by_key = {}
        by_num = {}
        for champ in payload.get("data", {}).values():
            by_key[champ.get("id")] = champ
            by_num[str(champ.get("key"))] = champ.get("id")
        DD_CACHE.update({"loaded_at": now, "by_key": by_key, "by_num": by_num, "version": version})
    except Exception:
        if not DD_CACHE["by_num"]:
            DD_CACHE["by_num"] = {str(key): value for key, value in STATIC_NUMERIC_TO_APP.items()}
    return DD_CACHE


def http_json(url, api_key_required=True):
    headers = {"User-Agent": "local-lol-draft-simulator/0.1"}
    if api_key_required:
        if not API_KEY:
            raise RuntimeError("Riot API key가 설정되지 않았습니다.")
        headers["X-Riot-Token"] = API_KEY
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            detail = payload.get("status", {}).get("message") or body
        except Exception:
            detail = body or error.reason
        raise RuntimeError(f"Riot API 오류 {error.code}: {detail}")
    except URLError as error:
        raise RuntimeError(f"네트워크 오류: {error.reason}")


def parse_riot_id(riot_id):
    text = str(riot_id or "").strip()
    if "#" not in text:
        raise ValueError(f"Riot ID 형식이 아닙니다: {text}")
    game_name, tag_line = text.rsplit("#", 1)
    game_name = game_name.strip()
    tag_line = tag_line.strip()
    if not game_name or not tag_line:
        raise ValueError(f"Riot ID 형식이 아닙니다: {text}")
    return game_name, tag_line


def routing_for_platform(platform):
    platform = (platform or "kr").lower()
    if platform in {"kr", "jp"}:
        return "asia"
    if platform in {"na1", "br1", "la1", "la2", "oc1"}:
        return "americas"
    if platform in {"euw1", "eun1", "tr1", "ru"}:
        return "europe"
    if platform in {"sg2", "ph2", "tw2", "th2", "vn2"}:
        return "sea"
    return "asia"


def clamp(value, low, high):
    return max(low, min(high, value))


def game_confidence(games, full_at=12):
    if games <= 0:
        return 0.0
    return clamp(games / full_at, 0.0, 1.0)


def comfort_from_record(games, wins, recent_weight, mastery_score, role_games=0, role_recent_weight=0.0):
    if games <= 0:
        return 1

    win_rate = wins / games * 100
    effective_games = role_games or games
    effective_recent_weight = role_recent_weight if role_games else recent_weight
    sample_confidence = game_confidence(effective_games, 14)

    play_score = min(36, math.log1p(effective_games) * 11.5)
    recent_score = min(10, effective_recent_weight * 1.0)
    role_bonus = (6 + sample_confidence * 6) if role_games else 0
    offrole_backup = min(5, max(0, games - effective_games) * 1.0) if role_games else 0
    mastery_part = mastery_score * (0.25 + sample_confidence * 0.40)

    # 승률은 표본이 쌓일수록 더 믿는다. 1~2판 고승률은 거의 보너스를 못 받고,
    # 10판 이상부터 실제 숙련도 보정으로 강하게 반영된다.
    win_score = (win_rate - 50) * 0.45 * sample_confidence
    if effective_games < 3:
        win_score = min(win_score, 3)

    base = 28 + play_score + recent_score + role_bonus + offrole_backup + mastery_part + win_score
    return round(clamp(base, 1, 100), 1)


def is_pool_candidate(item):
    role_games = int(item.get("assignedRoleGames") or 0)
    if role_games >= 2:
        return True
    if role_games == 1 and item.get("roleComfortScore", 0) >= 58 and item.get("masteryPoints", 0) >= 100000:
        return True
    return False


def analyze_player(player, platform, match_count, queue):
    riot_id = player.get("riotId", "")
    assigned_role = player.get("role", "")
    routing = routing_for_platform(platform)
    game_name, tag_line = parse_riot_id(riot_id)
    account_url = (
        f"https://{routing}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/"
        f"{quote(game_name)}/{quote(tag_line)}"
    )
    account = http_json(account_url)
    puuid = account["puuid"]

    params = {"start": 0, "count": max(1, min(int(match_count or 20), 50))}
    if queue:
        params["queue"] = int(queue)
    match_ids = http_json(
        f"https://{routing}.api.riotgames.com/lol/match/v5/matches/by-puuid/{quote(puuid)}/ids?{urlencode(params)}"
    )

    mastery_by_app = get_mastery(platform, puuid)
    rank = get_rank(platform, puuid)
    stats = {}
    matches_used = 0
    for index, match_id in enumerate(match_ids):
        match = get_match(routing, match_id)
        participant = next(
            (p for p in match.get("info", {}).get("participants", []) if p.get("puuid") == puuid),
            None,
        )
        if not participant:
            continue
        app_id = app_id_from_riot(participant.get("championName"), participant.get("championId"))
        if not app_id:
            continue
        display_name = champion_display_name(app_id, participant.get("championId"), participant.get("championName"))
        matches_used += 1
        role = normalize_role(participant.get("teamPosition") or participant.get("individualPosition"))
        recency = max(0.35, 1.0 - index * 0.03)
        item = stats.setdefault(
            app_id,
            {
                "championId": app_id,
                "championName": display_name,
                "games": 0,
                "wins": 0,
                "recentWeight": 0.0,
                "assignedRoleGames": 0,
                "assignedRoleRecentWeight": 0.0,
                "roles": {},
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "masteryPoints": mastery_by_app.get(app_id, {}).get("points", 0),
                "masteryLevel": mastery_by_app.get(app_id, {}).get("level", 0),
            },
        )
        item["games"] += 1
        item["wins"] += 1 if participant.get("win") else 0
        item["recentWeight"] += recency
        item["kills"] += int(participant.get("kills") or 0)
        item["deaths"] += int(participant.get("deaths") or 0)
        item["assists"] += int(participant.get("assists") or 0)
        item["roles"][role] = item["roles"].get(role, 0) + 1
        if assigned_role and role == assigned_role:
            item["assignedRoleGames"] += 1
            item["assignedRoleRecentWeight"] += recency

    for app_id, mastery in mastery_by_app.items():
        stats.setdefault(
            app_id,
            {
                "championId": app_id,
                "championName": mastery.get("name") or champion_display_name(app_id, mastery.get("championId")),
                "games": 0,
                "wins": 0,
                "recentWeight": 0.0,
                "assignedRoleGames": 0,
                "assignedRoleRecentWeight": 0.0,
                "roles": {},
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "masteryPoints": mastery.get("points", 0),
                "masteryLevel": mastery.get("level", 0),
            },
        )

    items = list(stats.values())
    for item in items:
        games = item["games"]
        assigned_role_games = item.get("assignedRoleGames", 0)
        win_rate = (item["wins"] / games * 100) if games else 0
        mastery_score = min(24, (item["masteryPoints"] or 0) / 12000)
        item["winRate"] = round(win_rate, 1) if games else None
        item["sampleConfidence"] = round(game_confidence(games, 14), 2)
        item["roleSampleConfidence"] = round(game_confidence(assigned_role_games, 8), 2)
        item["comfortScore"] = comfort_from_record(
            games,
            item["wins"],
            item["recentWeight"],
            mastery_score,
            0,
            0.0,
        )
        if assigned_role_games:
            item["roleComfortScore"] = comfort_from_record(
                games,
                item["wins"],
                item["recentWeight"],
                mastery_score,
                assigned_role_games,
                item.get("assignedRoleRecentWeight", 0),
            )
            item["roleFit"] = "MATCH"
        else:
            item["roleComfortScore"] = round(clamp(item["comfortScore"] * 0.42, 1, 45), 1)
            item["roleFit"] = "OFFROLE"
        item["kda"] = round((item["kills"] + item["assists"]) / max(1, item["deaths"]), 2) if games else None
        item["mainRole"] = max(item["roles"].items(), key=lambda pair: pair[1])[0] if item["roles"] else assigned_role

    role_seen_items = [
        item
        for item in items
        if assigned_role and item.get("assignedRoleGames", 0) > 0
    ]
    role_items = [item for item in role_seen_items if is_pool_candidate(item)]
    pool_source = role_items if assigned_role else items
    pool = [
        item["championId"]
        for item in sorted(pool_source, key=lambda row: row["roleComfortScore"], reverse=True)
    ][:8]
    role_matched_games = sum(item.get("assignedRoleGames", 0) for item in items)
    role_warning = ""
    if assigned_role and role_seen_items and not role_items:
        role_warning = (
            f"최근 {len(match_ids)}경기에서 {assigned_role} 기록은 있지만, "
            "추천 pool 기준(해당 라인 2판 이상 또는 높은 숙련 근거)을 넘긴 챔피언이 없습니다."
        )
    elif assigned_role and not role_seen_items:
        role_warning = f"최근 {len(match_ids)}경기에서 {assigned_role} 포지션 기록을 찾지 못해 이 라인 주챔폭을 비워뒀습니다."

    if assigned_role and not role_seen_items:
        role_warning = f"최근 {len(match_ids)}경기에서 {assigned_role} 사용 기록을 찾지 못해 해당 라인 챔프폭을 비워뒀습니다."

    return {
        "riotId": riot_id,
        "gameName": account.get("gameName", game_name),
        "tagLine": account.get("tagLine", tag_line),
        "puuid": puuid,
        "matchCount": len(match_ids),
        "matchesUsed": matches_used,
        "queue": int(queue) if queue else None,
        "queueLabel": QUEUE_LABELS.get(int(queue), "전체 큐") if queue else "전체 큐",
        "pool": pool,
        "stats": sorted(role_items if assigned_role else items, key=lambda row: row["roleComfortScore"], reverse=True)[:16],
        "roleMatchedGames": role_matched_games,
        "rolePoolMode": "assignedRole" if role_items else "fallback",
        "roleWarning": role_warning,
        "confidence": confidence_label(role_matched_games if assigned_role else matches_used, pool),
        "rank": rank,
    }


def get_mastery(platform, puuid):
    try:
        rows = http_json(
            f"https://{platform}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{quote(puuid)}"
        )
    except Exception:
        return {}
    result = {}
    for row in rows[:40]:
        app_id = app_id_from_riot(champion_num=row.get("championId"))
        if not app_id:
            continue
        result[app_id] = {
            "championId": row.get("championId"),
            "name": champion_display_name(app_id, row.get("championId")),
            "points": int(row.get("championPoints") or 0),
            "level": int(row.get("championLevel") or 0),
        }
    return result


# LEAGUE-V4의 by-summoner 엔드포인트는 2025-06-20에 제거되었고, PUUID 기반 엔드포인트로
# 대체되었다. summonerId를 별도로 조회할 필요 없이 puuid로 바로 조회 가능하다.
def get_rank(platform, puuid):
    try:
        entries = http_json(
            f"https://{platform}.api.riotgames.com/lol/league/v4/entries/by-puuid/{quote(puuid)}"
        )
    except Exception:
        return None
    if not entries:
        return None
    # 솔로랭크를 우선하고, 없으면 자유랭크로 대체한다.
    by_queue = {entry.get("queueType"): entry for entry in entries}
    entry = by_queue.get("RANKED_SOLO_5x5") or by_queue.get("RANKED_FLEX_SR")
    if not entry:
        return None
    return {
        "queueType": entry.get("queueType"),
        "tier": entry.get("tier"),
        "division": entry.get("rank"),
        "leaguePoints": entry.get("leaguePoints"),
        "wins": entry.get("wins"),
        "losses": entry.get("losses"),
    }


def get_match(routing, match_id):
    if match_id not in MATCH_CACHE:
        MATCH_CACHE[match_id] = http_json(
            f"https://{routing}.api.riotgames.com/lol/match/v5/matches/{quote(match_id)}"
        )
        if len(MATCH_CACHE) > MATCH_CACHE_LIMIT:
            MATCH_CACHE.popitem(last=False)
    else:
        MATCH_CACHE.move_to_end(match_id)
    return MATCH_CACHE[match_id]


def normalize_role(role):
    value = str(role or "").upper()
    return {
        "MIDDLE": "MID",
        "BOTTOM": "ADC",
        "UTILITY": "SUPPORT",
    }.get(value, value or "UNKNOWN")


def confidence_label(matches_used, pool):
    if matches_used >= 20 and len(pool) >= 5:
        return "높음"
    if matches_used >= 8 and len(pool) >= 3:
        return "보통"
    return "낮음"


def list_bgm_tracks():
    os.makedirs(BGM_DIR, exist_ok=True)
    tracks = []
    for name in sorted(os.listdir(BGM_DIR), key=str.lower):
        path = os.path.join(BGM_DIR, name)
        if not os.path.isfile(path):
            continue
        stem, ext = os.path.splitext(name)
        if ext.lower() not in AUDIO_EXTENSIONS:
            continue
        tracks.append({
            "id": name,
            "name": stem,
            "fileName": name,
            "url": "/assets/bgm/" + quote(name),
        })
    return tracks


def analyze_team(payload):
    platform = str(payload.get("platform") or "kr").lower()
    players = payload.get("players") or []
    match_count = int(payload.get("matchCount") or 20)
    queue = payload.get("queue") or None
    results = []
    errors = []
    for index, player in enumerate(players[:5]):
        try:
            results.append({"index": index, "ok": True, "data": analyze_player(player, platform, match_count, queue)})
        except Exception as error:
            errors.append({"index": index, "riotId": player.get("riotId", ""), "message": str(error)})
            results.append({"index": index, "ok": False, "error": str(error)})
    return {"ok": len(errors) == 0, "players": results, "errors": errors}


def save_api_key(api_key):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if api_key:
        with open(KEY_FILE, "w", encoding="utf-8") as file:
            file.write(api_key)
    else:
        clear_saved_api_key()


def clear_saved_api_key():
    try:
        os.remove(KEY_FILE)
    except FileNotFoundError:
        pass


def is_key_saved():
    return os.path.exists(KEY_FILE)


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:%s" % PORT)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def serve_bgm_file(self, encoded_name):
        # SimpleHTTPRequestHandler의 기본 정적 서빙은 한글 파일명에서 유니코드 정규화 형태
        # (NFC/NFD) 차이로 실제 존재하는 파일인데도 404를 내는 경우가 있다(윈도우에서 특히
        # 자주 발생). BGM_DIR 안의 실제 파일 목록과 정규화해서 비교해 직접 찾아서 서빙한다.
        requested = unquote(encoded_name)
        requested_norm = unicodedata.normalize("NFC", requested)
        try:
            entries = os.listdir(BGM_DIR)
        except FileNotFoundError:
            entries = []

        match = None
        for name in entries:
            if unicodedata.normalize("NFC", name) == requested_norm:
                match = name
                break

        if not match:
            self.send_error(404, "BGM file not found")
            return

        file_path = os.path.join(BGM_DIR, match)
        if not os.path.isfile(file_path):
            self.send_error(404, "BGM file not found")
            return

        content_type, _ = mimetypes.guess_type(file_path)
        content_type = content_type or "application/octet-stream"
        try:
            with open(file_path, "rb") as file:
                data = file.read()
        except OSError:
            self.send_error(500, "Could not read BGM file")
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            self.write_json({
                "ok": True,
                "hasKey": bool(API_KEY),
                "remembered": is_key_saved(),
                "matchCacheSize": len(MATCH_CACHE),
            })
            return
        if path == "/api/bgm":
            self.write_json({"ok": True, "tracks": list_bgm_tracks()})
            return
        if path.startswith("/assets/bgm/"):
            self.serve_bgm_file(path[len("/assets/bgm/"):])
            return
        if path == "/api/champions":
            data = get_ddragon_data()
            version = data.get("version") or ""
            champions = [
                {
                    "id": app_id_from_riot(champion_name=champ.get("id")) or normalize(champ.get("id")),
                    "key": champ.get("key"),
                    "name": champ.get("name") or champ.get("id"),
                    "iconUrl": (
                        f"https://ddragon.leagueoflegends.com/cdn/{version}/img/champion/{champ['image']['full']}"
                        if version and champ.get("image", {}).get("full")
                        else None
                    ),
                }
                for champ in data.get("by_key", {}).values()
            ]
            champions.sort(key=lambda item: item.get("name") or item.get("id") or "")
            self.write_json({"ok": True, "champions": champions, "ddragonVersion": version})
            return
        super().do_GET()

    def do_POST(self):
        global API_KEY
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/api/key":
                API_KEY = str(payload.get("apiKey") or "").strip()
                if payload.get("remember"):
                    save_api_key(API_KEY)
                self.write_json({"ok": bool(API_KEY), "hasKey": bool(API_KEY), "remembered": is_key_saved()})
                return
            if path == "/api/key/clear":
                API_KEY = ""
                clear_saved_api_key()
                self.write_json({"ok": True, "hasKey": False, "remembered": False})
                return
            if path == "/api/analyze-team":
                self.write_json(analyze_team(payload))
                return
            self.write_json({"ok": False, "error": "Unknown API route"}, status=404)
        except Exception as error:
            self.write_json({"ok": False, "error": str(error)}, status=500)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def write_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"LoL draft simulator server: http://{HOST}:{PORT}/")
    source = "loaded" if API_KEY else "not set; enter it in the Setup tab"
    if API_KEY and os.environ.get("RIOT_API_KEY", "").strip():
        source = "loaded from RIOT_API_KEY"
    elif API_KEY:
        source = "loaded from local saved key"
    print("Riot API key: " + source)

    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
