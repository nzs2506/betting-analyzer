"""
Betting Analyzer -- ESPN API + API-Football + the-odds-api.com
Находит матчи где коэффициент противоречит положению в таблице.

Ключи читаются из переменных окружения:
  ODDS_API_KEY
  API_FOOTBALL_KEY

Запуск: python -X utf8 "betting_analyzer — for codex.py"
"""

import requests
import json
import os
import re
from difflib import SequenceMatcher
from datetime import datetime, timedelta

# ─── КЛЮЧ ─────────────────────────────────────────────────────────────────────
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")

# ─── НАСТРОЙКИ ────────────────────────────────────────────────────────────────
MIN_POSITION_DIFF = 4
DAYS_AHEAD        = 3   # смотрим на 3 дня вперёд (можно увеличить до 7)

ESPN_HDR  = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
ESPN_S    = "https://site.api.espn.com/apis/site/v2/sports/soccer"
ESPN_ST   = "https://site.api.espn.com/apis/v2/sports/soccer"
ODDS_BASE = "https://api.the-odds-api.com/v4"
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
API_FOOTBALL_CACHE = "api_football_leagues_cache.json"
RESULTS_DIR = os.getenv("RESULTS_DIR", ".")
WRITE_ARCHIVE = os.getenv("WRITE_ARCHIVE", "0") == "1"

# ─── ЛИГИ: (espn_slug, название, odds_sport_key или None) ─────────────────────
# Фокус: низшие дивизионы + экзотика (Африка, Азия, Ю.Америка, Скандинавия)
LEAGUES = [
    # Южная Америка
    ("bra.1",  "Бразилия Серия А",          "soccer_brazil_campeonato"),
    ("bra.2",  "Бразилия Серия Б",          "soccer_brazil_serie_b"),
    ("bra.3",  "Бразилия Серия С",          None),
    ("arg.1",  "Аргентина Примера",         "soccer_argentina_primera_division"),
    ("arg.2",  "Аргентина Насьональ Б",     None),
    ("chi.1",  "Чили Примера",              "soccer_chile_campeonato"),
    ("col.1",  "Колумбия Примера А",        None),
    ("uru.1",  "Уругвай Лига",              None),
    ("ecu.1",  "Эквадор ЛигаПро",           None),
    ("bol.1",  "Боливия Лига",              None),
    ("par.1",  "Парагвай Примера",          None),
    ("per.1",  "Перу Лига 1",               None),
    ("ven.1",  "Венесуэла Примера",         None),
    # Северная Америка
    ("mex.1",  "Мексика Лига MX",           "soccer_mexico_ligamx"),
    ("mex.2",  "Мексика Лига Экспансьон",   None),
    ("usa.1",  "США MLS",                   "soccer_usa_mls"),
    ("usa.2",  "США USL Championship",      None),
    # Азия
    ("jpn.1",  "Япония J-League",           "soccer_japan_j_league"),
    ("jpn.2",  "Япония J2 League",          None),
    ("chn.1",  "Китай Суперлига",           "soccer_china_superleague"),
    ("ind.1",  "Индия Суперлига",           None),
    ("idn.1",  "Индонезия Суперлига",       None),
    ("tha.1",  "Таиланд Лига 1",            None),
    ("mys.1",  "Малайзия Суперлига",        None),
    ("aus.1",  "Австралия А-Лига",          "soccer_australia_aleague"),
    # Африка
    ("nga.1",  "Нигерия Профлига",          None),
    ("gha.1",  "Гана Премьер-лига",         None),
    ("ken.1",  "Кения Премьер-лига",        None),
    ("uga.1",  "Уганда Премьер-лига",       None),
    ("zam.1",  "Замбия Суперлига",          None),
    # Скандинавия
    ("nor.1",  "Норвегия Элитесерен",       "soccer_norway_eliteserien"),
    ("nor.2",  "Норвегия 1-й дивизион",     None),
    ("swe.1",  "Швеция Алльсвенскан",       "soccer_sweden_allsvenskan"),
    ("swe.2",  "Швеция СуперЭттан",         "soccer_sweden_superettan"),
    ("den.1",  "Дания Суперлига",            "soccer_denmark_superliga"),
    ("den.2",  "Дания 1-й дивизион",         None),
    ("fin.1",  "Финляндия Вейккаусл.",       "soccer_finland_veikkausliiga"),
    # Другая Европа (низшие/экзотика)
    ("sco.1",  "Шотландия Премьершип",      "soccer_scotland_premiership"),
    ("sco.2",  "Шотландия Чемпионшип",      None),
    ("irl.1",  "Ирландия Лига",             "soccer_league_of_ireland"),
    ("wal.1",  "Уэльс Премьер",             None),
    ("tur.1",  "Турция Суперлига",           "soccer_turkey_super_league"),
    ("tur.2",  "Турция 1-й лига",            None),
    ("gre.1",  "Греция Суперлига",           "soccer_greece_super_league"),
    ("rou.1",  "Румыния Лига 1",             None),
    ("aut.1",  "Австрия Бундеслига",         "soccer_austria_bundesliga"),
    ("bel.1",  "Бельгия Про Лига",           "soccer_belgium_first_div_a"),
]

# ─── API-FOOTBALL: редкие лиги, которых часто нет в ESPN ──────────────────────
# season=None означает "взять текущий сезон из ответа /leagues".
# Если discovery нашёл не ту лигу, лучше заменить country/name на явный league_id.
API_FOOTBALL_LEAGUES = [
    {"country": "Morocco", "name": "Botola 2", "season": None},
    {"country": "Estonia", "name": "U19", "season": None},
]

SEP = "=" * 58


# ─── ESPN API ─────────────────────────────────────────────────────────────────

def get_standings(slug):
    """Возвращает {team_id: {pos, pts, name}}."""
    r = requests.get(f"{ESPN_ST}/{slug}/standings", headers=ESPN_HDR, timeout=15)
    if r.status_code != 200:
        return {}
    result = {}
    for child in r.json().get("children", []):
        for entry in child.get("standings", {}).get("entries", []):
            team  = entry["team"]
            stats = {s["name"]: s.get("value", 0) for s in entry.get("stats", [])}
            tid   = team["id"]
            result[tid] = {
                "pos":  int(stats.get("rank",   0)),
                "pts":  int(stats.get("points", 0)),
                "name": team["displayName"],
            }
    return result


def get_fixtures(slug):
    """Возвращает список матчей STATUS_SCHEDULED на DAYS_AHEAD вперёд."""
    matches = []
    seen_ids = set()
    now = datetime.now()

    for i in range(DAYS_AHEAD + 1):
        d = (now + timedelta(days=i)).strftime("%Y%m%d")
        r = requests.get(
            f"{ESPN_S}/{slug}/scoreboard?dates={d}",
            headers=ESPN_HDR, timeout=10
        )
        if r.status_code != 200:
            continue
        for event in r.json().get("events", []):
            eid  = event["id"]
            if eid in seen_ids:
                continue
            comp   = event["competitions"][0]
            status = comp["status"]["type"]["name"]
            if status != "STATUS_SCHEDULED":
                continue
            seen_ids.add(eid)
            comps  = comp["competitors"]
            home   = next((c for c in comps if c["homeAway"] == "home"), None)
            away   = next((c for c in comps if c["homeAway"] == "away"), None)
            if not home or not away:
                continue
            matches.append({
                "home_id":   home["team"]["id"],
                "away_id":   away["team"]["id"],
                "home_name": home["team"]["displayName"],
                "away_name": away["team"]["displayName"],
                "home_form": home.get("form", ""),
                "away_form": away.get("form", ""),
                "date":      event["date"],
            })
    return matches


# ─── API-FOOTBALL ─────────────────────────────────────────────────────────────

def _load_api_football_cache():
    try:
        with open(API_FOOTBALL_CACHE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_api_football_cache(cache):
    try:
        with open(API_FOOTBALL_CACHE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def api_football_get(endpoint, params=None):
    if not API_FOOTBALL_KEY:
        return None
    r = requests.get(
        f"{API_FOOTBALL_BASE}/{endpoint.lstrip('/')}",
        headers={"x-apisports-key": API_FOOTBALL_KEY},
        params=params or {},
        timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(f"API-Football {endpoint}: HTTP {r.status_code} {r.text[:160]}")
    data = r.json()
    errors = data.get("errors")
    if errors:
        raise RuntimeError(f"API-Football {endpoint}: {errors}")
    return data


def _norm_name(value):
    value = value.lower()
    value = re.sub(r"[^a-z0-9а-яё]+", " ", value, flags=re.IGNORECASE)
    return " ".join(value.split())


def _name_score(needle, candidate):
    needle = _norm_name(needle)
    candidate = _norm_name(candidate)
    if not needle or not candidate:
        return 0
    if needle in candidate:
        return 100 + len(needle)
    return int(SequenceMatcher(None, needle, candidate).ratio() * 100)


def _pick_season(league_info, requested_season):
    if requested_season:
        return requested_season
    seasons = league_info.get("seasons", [])
    current = next((s["year"] for s in seasons if s.get("current")), None)
    if current:
        return current
    years = [s.get("year") for s in seasons if s.get("year")]
    return max(years) if years else datetime.now().year


def resolve_api_football_league(config):
    """Возвращает (league_id, season, league_name) для записи API_FOOTBALL_LEAGUES."""
    if config.get("league_id"):
        return config["league_id"], config.get("season") or datetime.now().year, config["name"]

    country = config["country"]
    name = config["name"]
    cache_key = f"{country}|{name}|{config.get('season') or 'current'}"
    cache = _load_api_football_cache()
    if cache_key in cache:
        item = cache[cache_key]
        return item["league_id"], item["season"], item["league_name"]

    data = api_football_get("leagues", {"country": country})
    candidates = data.get("response", []) if data else []
    if not candidates:
        return None, None, f"{country}: {name}"

    best = max(candidates, key=lambda item: _name_score(name, item["league"]["name"]))
    if _name_score(name, best["league"]["name"]) < 55:
        return None, None, f"{country}: {name}"

    league_id = best["league"]["id"]
    league_name = best["league"]["name"]
    season = _pick_season(best, config.get("season"))

    cache[cache_key] = {"league_id": league_id, "season": season, "league_name": league_name}
    _save_api_football_cache(cache)
    return league_id, season, league_name


def get_api_football_standings(league_id, season):
    data = api_football_get("standings", {"league": league_id, "season": season})
    result = {}
    response = data.get("response", []) if data else []
    if not response:
        return result
    for group in response[0].get("league", {}).get("standings", []):
        for row in group:
            team = row.get("team", {})
            tid = str(team.get("id"))
            result[tid] = {
                "pos": int(row.get("rank") or 0),
                "pts": int(row.get("points") or 0),
                "name": team.get("name", ""),
            }
    return result


def get_api_football_fixtures(league_id, season):
    end = (datetime.now() + timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%d")
    data = api_football_get(
        "fixtures",
        {"league": league_id, "season": season, "from": datetime.now().strftime("%Y-%m-%d"), "to": end},
    )
    matches = []
    for item in (data.get("response", []) if data else []):
        status = item.get("fixture", {}).get("status", {}).get("short")
        if status not in {"NS", "TBD"}:
            continue
        teams = item.get("teams", {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        matches.append({
            "fixture_id": item.get("fixture", {}).get("id"),
            "home_id": str(home.get("id")),
            "away_id": str(away.get("id")),
            "home_name": home.get("name", ""),
            "away_name": away.get("name", ""),
            "home_form": "",
            "away_form": "",
            "date": item.get("fixture", {}).get("date", ""),
        })
    return matches


def get_api_football_odds(league_id, season):
    data = api_football_get("odds", {"league": league_id, "season": season, "bet": 1})
    result = {}
    for item in (data.get("response", []) if data else []):
        fixture_id = item.get("fixture", {}).get("id")
        if not fixture_id:
            continue
        for bm in item.get("bookmakers", []):
            for bet in bm.get("bets", []):
                values = bet.get("values", [])
                odds = {v.get("value"): v.get("odd") for v in values}
                if {"Home", "Draw", "Away"} <= set(odds):
                    result[fixture_id] = {
                        "home": float(odds["Home"]),
                        "draw": float(odds["Draw"]),
                        "away": float(odds["Away"]),
                        "bm": bm.get("name", "API-Football"),
                        "time": item.get("fixture", {}).get("date", ""),
                    }
                    break
            if fixture_id in result:
                break
    return result


# ─── THE ODDS API ─────────────────────────────────────────────────────────────

def get_active_sports():
    if not ODDS_API_KEY:
        return set()
    r = requests.get(f"{ODDS_BASE}/sports",
                     params={"apiKey": ODDS_API_KEY}, timeout=15)
    if r.status_code != 200:
        return set()
    return {s["key"] for s in r.json() if s.get("group") == "Soccer" and s.get("active")}


def get_odds(sport_key):
    if not ODDS_API_KEY:
        return {}
    r = requests.get(
        f"{ODDS_BASE}/sports/{sport_key}/odds",
        params={"apiKey": ODDS_API_KEY, "regions": "eu",
                "markets": "h2h", "oddsFormat": "decimal"},
        timeout=15,
    )
    if r.status_code != 200:
        return {}
    result = {}
    for event in r.json():
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        for bm in event.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                if mkt["key"] == "h2h":
                    prices = {o["name"]: o["price"] for o in mkt["outcomes"]}
                    key = (_norm_name(home), _norm_name(away))
                    result[key] = {
                        "home": prices.get(home),
                        "draw": prices.get("Draw"),
                        "away": prices.get(away),
                        "bm":   bm["title"],
                        "time": event.get("commence_time", ""),
                    }
                    break
            if (_norm_name(home), _norm_name(away)) in result:
                break
    return result


def find_odds(od, home, away):
    h, a = _norm_name(home), _norm_name(away)
    if (h, a) in od:
        return od[(h, a)]
    for (oh, oa), data in od.items():
        ohn, oan = _norm_name(oh), _norm_name(oa)
        home_score = SequenceMatcher(None, h, ohn).ratio()
        away_score = SequenceMatcher(None, a, oan).ratio()
        if home_score >= 0.78 and away_score >= 0.78:
            return data
    return None


def find_api_football_odds(odds_by_fixture, fixture):
    return odds_by_fixture.get(fixture.get("fixture_id"))


# ─── АНАЛИЗ ───────────────────────────────────────────────────────────────────

def analyze(fix, hs, aws, odds):
    if not (hs and aws and odds):
        return None
    diff = abs(hs["pos"] - aws["pos"])
    if diff < MIN_POSITION_DIFF:
        return None
    ho, ao = odds.get("home"), odds.get("away")
    if not ho or not ao:
        return None
    table_fav = "home" if hs["pos"] < aws["pos"] else "away"
    odds_fav  = "home" if ho < ao else "away"
    if table_fav == odds_fav:
        return None

    if table_fav == "home":
        vt, vo, vp = fix["home_name"], ho, hs["pos"]
    else:
        vt, vo, vp = fix["away_name"], ao, aws["pos"]

    return {
        "home":       fix["home_name"],
        "away":       fix["away_name"],
        "home_pos":   hs["pos"],
        "away_pos":   aws["pos"],
        "home_pts":   hs["pts"],
        "away_pts":   aws["pts"],
        "home_form":  fix["home_form"],
        "away_form":  fix["away_form"],
        "home_odds":  ho,
        "draw_odds":  odds.get("draw"),
        "away_odds":  ao,
        "bookmaker":  odds["bm"],
        "time":       fix["date"],
        "value_team": vt,
        "value_odds": vo,
        "value_pos":  vp,
        "pos_diff":   diff,
    }


# ─── КОНСОЛЬНЫЙ ВЫВОД ─────────────────────────────────────────────────────────

def fmt_time(t):
    if not t:
        return "--"
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).strftime("%d.%m %H:%M UTC")
    except Exception:
        return t


def fmt_form(f):
    if not f:
        return "--"
    return " ".join(f.replace(",", ""))


def print_match(m, league):
    print()
    print(SEP)
    print(f"  {league}")
    print()
    print(f"  {m['home']}")
    print(f"    #{m['home_pos']}  {m['home_pts']} оч.  форма: {fmt_form(m['home_form'])}")
    print(f"  vs")
    print(f"  {m['away']}")
    print(f"    #{m['away_pos']}  {m['away_pts']} оч.  форма: {fmt_form(m['away_form'])}")
    print()
    print(f"  Разница мест: {m['pos_diff']}")
    print(f"  Коэфы ({m['bookmaker']}):")
    print(f"    1: {m['home_odds']}   X: {m['draw_odds']}   2: {m['away_odds']}")
    print()
    print(f"  >> {m['value_team']} (#{m['value_pos']}) --")
    print(f"     сильнее по таблице, но кэф {m['value_odds']} (аутсайдер у букмекера)")
    print(f"  Время: {fmt_time(m['time'])}")
    print(SEP)


# ─── HTML ЭКСПОРТ ─────────────────────────────────────────────────────────────

def _form_badges(form_str):
    if not form_str:
        return '<span style="color:#8b949e">--</span>'
    palette = {
        "W": ("#3fb950", "rgba(63,185,80,0.15)"),
        "L": ("#f85149", "rgba(248,81,73,0.15)"),
        "D": ("#d29922", "rgba(210,153,34,0.15)"),
    }
    out = []
    for ch in form_str.replace(",", ""):
        fg, bg = palette.get(ch, ("#8b949e", "rgba(139,148,158,0.15)"))
        out.append(
            f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:22px;height:22px;border-radius:4px;background:{bg};color:{fg};'
            f'font-size:11px;font-weight:700;margin:1px">{ch}</span>'
        )
    return "".join(out)


def _odd_cell(label, value, highlight=False):
    border = "#f78166" if highlight else "#30363d"
    bg     = "rgba(247,129,102,0.12)" if highlight else "rgba(139,148,158,0.07)"
    color  = "#f78166" if highlight else "#e6edf3"
    val    = str(value) if value else "--"
    return (
        f'<div style="background:{bg};border:1px solid {border};border-radius:6px;'
        f'padding:6px 14px;text-align:center;min-width:62px">'
        f'<div style="font-size:10px;color:#8b949e;text-transform:uppercase;'
        f'letter-spacing:.04em;margin-bottom:2px">{label}</div>'
        f'<div style="font-size:17px;font-weight:700;color:{color}">{val}</div>'
        f'</div>'
    )


def _match_card(league, m):
    home_hl = m["value_team"] == m["home"]
    away_hl = m["value_team"] == m["away"]

    o1 = _odd_cell("1", m["home_odds"], home_hl)
    ox = _odd_cell("X", m.get("draw_odds"))
    o2 = _odd_cell("2", m["away_odds"], away_hl)

    value_color = f'<span style="color:#f78166;font-weight:700">{m["value_odds"]}</span>'

    return f"""
    <div style="background:#161b22;border:1px solid #30363d;border-left:3px solid #f78166;
                border-radius:10px;overflow:hidden;margin-bottom:16px">
      <div style="padding:10px 20px;background:rgba(247,129,102,0.07);
                  border-bottom:1px solid #30363d;display:flex;
                  align-items:center;justify-content:space-between">
        <span style="font-size:11px;font-weight:700;text-transform:uppercase;
                     letter-spacing:.07em;color:#f78166">{league}</span>
        <span style="font-size:12px;color:#8b949e">{fmt_time(m['time'])}</span>
      </div>
      <div style="padding:20px 24px;display:grid;grid-template-columns:1fr 72px 1fr;
                  gap:12px;align-items:center">
        <div style="text-align:right">
          <div style="font-size:16px;font-weight:600;margin-bottom:4px">{m['home']}</div>
          <div style="font-size:12px;color:#8b949e;margin-bottom:6px">
            #{m['home_pos']} &bull; {m['home_pts']} оч.
          </div>
          <div style="display:flex;justify-content:flex-end;gap:2px;flex-wrap:wrap">
            {_form_badges(m['home_form'])}
          </div>
        </div>
        <div style="text-align:center">
          <div style="font-size:11px;color:#8b949e;font-weight:700;margin-bottom:6px">VS</div>
          <div style="font-size:11px;color:#8b949e;background:rgba(139,148,158,0.1);
                      border-radius:4px;padding:3px 8px;display:inline-block">
            &Delta;{m['pos_diff']}
          </div>
        </div>
        <div style="text-align:left">
          <div style="font-size:16px;font-weight:600;margin-bottom:4px">{m['away']}</div>
          <div style="font-size:12px;color:#8b949e;margin-bottom:6px">
            #{m['away_pos']} &bull; {m['away_pts']} оч.
          </div>
          <div style="display:flex;justify-content:flex-start;gap:2px;flex-wrap:wrap">
            {_form_badges(m['away_form'])}
          </div>
        </div>
      </div>
      <div style="padding:14px 24px;border-top:1px solid #30363d;
                  display:flex;align-items:center;justify-content:space-between;
                  flex-wrap:wrap;gap:12px">
        <div style="display:flex;gap:8px;align-items:center">
          {o1}{ox}{o2}
          <span style="font-size:11px;color:#6e7681;margin-left:4px">{m.get('bookmaker','')}</span>
        </div>
        <div style="font-size:13px;color:#e6edf3;max-width:340px">
          <strong>{m['value_team']}</strong> -- #{m['value_pos']} в таблице,
          но кэф {value_color} (аутсайдер у букмекера)
        </div>
      </div>
    </div>"""


def export_html(results, stats, generated_at):
    ts    = generated_at.strftime("%d.%m.%Y %H:%M")
    count = len(results)

    if results:
        cards = "\n".join(_match_card(lg, m) for lg, m in results)
    else:
        cards = f"""
        <div style="text-align:center;padding:64px 0;color:#8b949e">
          <div style="font-size:52px;margin-bottom:20px">&#128269;</div>
          <div style="font-size:18px;color:#e6edf3;font-weight:600;margin-bottom:8px">
            Аномалий не найдено
          </div>
          <div style="line-height:1.8">
            Проверено лиг: <strong style="color:#e6edf3">{stats['leagues_checked']}</strong><br>
            Матчей на {DAYS_AHEAD} дн.: <strong style="color:#e6edf3">{stats['fixtures_found']}</strong><br>
            Матчей с коэффициентами: <strong style="color:#e6edf3">{stats['with_odds']}</strong>
          </div>
        </div>"""

    leagues_html = ""
    for slug, name, status in stats.get("leagues_detail", []):
        color = "#3fb950" if status == "ok" else "#f85149" if status == "no_data" else "#8b949e"
        icon  = "&#10003;" if status == "ok" else "&#8722;" if status == "no_data" else "&#8726;"
        leagues_html += (
            f'<div style="display:flex;align-items:center;gap:8px;padding:6px 0;'
            f'border-bottom:1px solid #21262d;font-size:13px">'
            f'<span style="color:{color};font-size:14px">{icon}</span>'
            f'<span style="color:#8b949e;font-family:monospace;font-size:11px">{slug}</span>'
            f'<span>{name}</span>'
            f'</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Betting Analyzer -- {ts}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0d1117;
      color: #e6edf3;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      font-size: 14px;
      line-height: 1.6;
    }}
  </style>
</head>
<body>
  <div style="padding:20px 32px;border-bottom:1px solid #30363d;
              display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
    <div>
      <div style="font-size:20px;font-weight:700">Betting Analyzer</div>
      <div style="font-size:12px;color:#8b949e;margin-top:3px">
        ESPN API &bull; API-Football &bull; the-odds-api.com &bull;
        Горизонт: {DAYS_AHEAD}д &bull; Мин. разница мест: {MIN_POSITION_DIFF}
      </div>
    </div>
    <div style="font-size:12px;color:#8b949e">Обновлено: {ts}</div>
  </div>

  <div style="max-width:1100px;margin:32px auto;padding:0 24px;display:grid;
              grid-template-columns:1fr 280px;gap:24px;align-items:start">

    <div>
      <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;
                  padding:16px 24px;margin-bottom:24px;display:flex;gap:40px;flex-wrap:wrap">
        <div>
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;
                      color:#8b949e;margin-bottom:4px">Аномалий</div>
          <div style="font-size:32px;font-weight:700;color:#f78166">{count}</div>
        </div>
        <div>
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;
                      color:#8b949e;margin-bottom:4px">Лиг проверено</div>
          <div style="font-size:32px;font-weight:700">{stats['leagues_checked']}</div>
        </div>
        <div>
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;
                      color:#8b949e;margin-bottom:4px">Матчей найдено</div>
          <div style="font-size:32px;font-weight:700">{stats['fixtures_found']}</div>
        </div>
        <div>
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:.06em;
                      color:#8b949e;margin-bottom:4px">С коэффициентами</div>
          <div style="font-size:32px;font-weight:700">{stats['with_odds']}</div>
        </div>
      </div>
      {cards}
    </div>

    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px 20px">
      <div style="font-size:12px;font-weight:700;text-transform:uppercase;
                  letter-spacing:.06em;color:#8b949e;margin-bottom:12px">Лиги</div>
      {leagues_html}
    </div>

  </div>
</body>
</html>"""


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run():
    print()
    print(SEP)
    print(f"  Betting Analyzer  |  {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print(f"  Горизонт: {DAYS_AHEAD}д  |  Мин. разница мест: >={MIN_POSITION_DIFF}")
    print(SEP)

    # 1. Активные sport-ключи Odds API
    if not ODDS_API_KEY:
        print("\n  ODDS_API_KEY не задан: ESPN-лиги будут проверены без коэффициентов.")
        active_odds = set()
    else:
        print("\n  Загружаем активные лиги Odds API...")
        active_odds = get_active_sports()
        print(f"  Активных: {len(active_odds)}")

    if not API_FOOTBALL_KEY:
        print("  API_FOOTBALL_KEY не задан: редкие лиги API-Football пропущены.")
    else:
        print("  API_FOOTBALL_KEY найден: редкие лиги API-Football включены.")

    results        = []
    leagues_detail = []
    total_fixtures = 0
    total_with_odds = 0

    # 2. Обходим ESPN-лиги
    for slug, league_name, odds_key in LEAGUES:
        print(f"\n  [{slug}] {league_name}...")

        try:
            # Таблица
            standings = get_standings(slug)
            if not standings:
                print(f"    таблица недоступна")
                leagues_detail.append((slug, league_name, "no_data"))
                continue

            # Матчи
            fixtures = get_fixtures(slug)
            if not fixtures:
                print(f"    матчей на {DAYS_AHEAD}д нет")
                leagues_detail.append((slug, league_name, "no_matches"))
                continue

            total_fixtures += len(fixtures)
            print(f"    матчей: {len(fixtures)}, команд в таблице: {len(standings)}")

            # Коэффициенты
            odds_data = {}
            if odds_key and odds_key in active_odds:
                odds_data = get_odds(odds_key)
                print(f"    коэффициентов: {len(odds_data)}")
            elif odds_key:
                print(f"    {odds_key} не в сезоне")
            else:
                print(f"    odds_key не задан")

            # Анализ
            found = 0
            for fix in fixtures:
                hs  = standings.get(fix["home_id"])
                aws = standings.get(fix["away_id"])
                od  = find_odds(odds_data, fix["home_name"], fix["away_name"])

                if od:
                    total_with_odds += 1

                result = analyze(fix, hs, aws, od)
                if result:
                    results.append((league_name, result))
                    found += 1

            if found:
                print(f"    АНОМАЛИЙ: {found}")

            leagues_detail.append((slug, league_name, "ok"))

        except Exception as e:
            print(f"    ОШИБКА: {e}")
            leagues_detail.append((slug, league_name, "no_data"))

    # 3. Обходим редкие лиги API-Football
    if API_FOOTBALL_KEY:
        for config in API_FOOTBALL_LEAGUES:
            label = f"{config.get('country', '')}: {config.get('name', '')}"
            print(f"\n  [api-football] {label}...")

            try:
                league_id, season, league_name = resolve_api_football_league(config)
                if not league_id:
                    print("    лига не найдена")
                    leagues_detail.append(("api-football", label, "no_data"))
                    continue

                slug = f"af:{league_id}/{season}"
                print(f"    league_id={league_id}, season={season}, name={league_name}")

                standings = get_api_football_standings(league_id, season)
                if not standings:
                    print("    таблица недоступна")
                    leagues_detail.append((slug, league_name, "no_data"))
                    continue

                fixtures = get_api_football_fixtures(league_id, season)
                if not fixtures:
                    print(f"    матчей на {DAYS_AHEAD}д нет")
                    leagues_detail.append((slug, league_name, "no_matches"))
                    continue

                total_fixtures += len(fixtures)
                print(f"    матчей: {len(fixtures)}, команд в таблице: {len(standings)}")

                odds_data = get_api_football_odds(league_id, season)
                print(f"    коэффициентов API-Football: {len(odds_data)}")

                found = 0
                for fix in fixtures:
                    hs = standings.get(fix["home_id"])
                    aws = standings.get(fix["away_id"])
                    od = find_api_football_odds(odds_data, fix)

                    if od:
                        total_with_odds += 1

                    result = analyze(fix, hs, aws, od)
                    if result:
                        results.append((league_name, result))
                        found += 1

                if found:
                    print(f"    АНОМАЛИЙ: {found}")

                leagues_detail.append((slug, league_name, "ok"))

            except Exception as e:
                print(f"    ОШИБКА: {e}")
                leagues_detail.append(("api-football", label, "no_data"))

    # 4. Результат
    results.sort(key=lambda x: x[1]["pos_diff"], reverse=True)

    print(f"\n\n  Найдено аномалий: {len(results)}")
    for lg, m in results:
        print_match(m, lg)

    now   = datetime.now()
    stamp = now.strftime("%Y%m%d_%H%M")

    stats = {
        "leagues_checked": len([l for l in leagues_detail if l[2] == "ok"]),
        "fixtures_found":  total_fixtures,
        "with_odds":       total_with_odds,
        "leagues_detail":  leagues_detail,
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)

    latest_html = os.path.join(RESULTS_DIR, "index.html")
    html = export_html(results, stats, now)
    if WRITE_ARCHIVE:
        html_fname = os.path.join(RESULTS_DIR, f"results_{stamp}.html")
        with open(html_fname, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n  HTML: {html_fname}")
    with open(latest_html, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n  Latest: {latest_html}")

    latest_json = os.path.join(RESULTS_DIR, "results.json")
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": now.isoformat(),
            "settings": {
                "days_ahead": DAYS_AHEAD,
                "min_position_diff": MIN_POSITION_DIFF,
            },
            "stats": stats,
            "results": [{"league": l, "match": m} for l, m in results],
        }, f, ensure_ascii=False, indent=2)
    print(f"  Latest JSON: {latest_json}")

    if WRITE_ARCHIVE:
        json_fname = os.path.join(RESULTS_DIR, f"results_{stamp}.json")
        with open(json_fname, "w", encoding="utf-8") as f:
            json.dump([{"league": l, "match": m} for l, m in results],
                      f, ensure_ascii=False, indent=2)
        print(f"  JSON: {json_fname}\n")


if __name__ == "__main__":
    run()
