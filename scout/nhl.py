"""NHL official APIs: schedule, skater reports, team defence, NHL EDGE tracking."""
from .http import get_json

STATS = "https://api.nhle.com/stats/rest/en"
WEB = "https://api-web.nhle.com/v1"


def schedule_week(date_str):
    """Seven days of games starting at date_str (YYYY-MM-DD)."""
    data = get_json(f"{WEB}/schedule/{date_str}")
    days = []
    for d in data.get("gameWeek", []):
        games = [g for g in d.get("games", []) if g.get("gameType") in (2, 3)]
        days.append({"date": d["date"], "games": games})
    return days


def _report(report, cayenne, extra=None):
    """Page through a skater report and return rows keyed by playerId."""
    rows, start = {}, 0
    while True:
        params = {"limit": 100, "start": start, "cayenneExp": cayenne}
        params.update(extra or {})
        data = get_json(f"{STATS}/skater/{report}", params=params)
        batch = data.get("data", [])
        for r in batch:
            rows[r["playerId"]] = r
        start += len(batch)
        if not batch or start >= data.get("total", 0):
            break
    return rows


def skaters(season_id=None, date_from=None, date_to=None):
    """Merge summary + realtime + timeonice reports into one dict per player."""
    if date_from:
        cay = f'gameDate<="{date_to}" and gameDate>="{date_from}" and gameTypeId=2'
        extra = {"isAggregate": "false", "isGame": "false"}
    else:
        cay = f"seasonId={season_id} and gameTypeId=2"
        extra = None
    merged = {}
    for rep in ("summary", "realtime", "timeonice"):
        for pid, r in _report(rep, cay, extra).items():
            merged.setdefault(pid, {}).update(r)
    return merged


def team_defence(season_id):
    """Goals against and shots against per game by team abbreviation."""
    data = get_json(f"{STATS}/team/summary",
                    params={"limit": 50, "cayenneExp": f"seasonId={season_id} and gameTypeId=2"})
    out = {}
    for t in data.get("data", []):
        out[t.get("teamFullName")] = t
    return out


def team_abbrevs():
    data = get_json(f"{STATS}/team")
    return {t["fullName"]: t["triCode"] for t in data.get("data", [])}


def edge(player_id, season_id):
    """NHL EDGE puck/player tracking for one skater (None if unavailable)."""
    try:
        return get_json(f"{WEB}/edge/skater-detail/{player_id}/{season_id}/2")
    except Exception:
        return None
