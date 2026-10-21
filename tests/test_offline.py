"""Offline smoke test: fake NHL / MoneyPuck / ESPN data, run the full pick."""
import io
import json
import os
import random
import sys
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scout import espn, main, moneypuck, nhl  # noqa: E402

random.seed(7)
TEAMS = ["TOR", "MTL", "BUF", "PHI", "EDM", "UTA", "VAN", "DET", "BOS", "NYR", "CAR", "SEA"]


def fake_players():
    cur, prev, mp = {}, {}, {}
    pid = 8470000
    for t in TEAMS:
        for i in range(18):
            pid += 1
            pos = "D" if i < 6 else random.choice("CLR")
            gp = 9
            sh = random.uniform(1, 3.5)
            row = {"playerId": pid, "skaterFullName": "Player " + "".join(chr(97 + int(ch)) for ch in str(pid)), "positionCode": pos,
                   "teamAbbrevs": t, "gamesPlayed": gp,
                   "goals": random.randint(0, 6), "assists": random.randint(0, 8),
                   "points": 0, "ppPoints": random.randint(0, 4), "shPoints": 0,
                   "shots": int(sh * gp), "hits": random.randint(2, 30),
                   "blockedShots": random.randint(1, 30 if pos == "D" else 8),
                   "timeOnIcePerGame": random.uniform(700, 1500),
                   "ppTimeOnIcePerGame": random.uniform(0, 200)}
            row["points"] = row["goals"] + row["assists"]
            cur[pid] = row
            p = dict(row, gamesPlayed=80, goals=row["goals"] * 7, assists=row["assists"] * 7,
                     ppPoints=row["ppPoints"] * 7, shots=row["shots"] * 8,
                     hits=row["hits"] * 8, blockedShots=row["blockedShots"] * 8,
                     ppTimeOnIcePerGame=random.uniform(0, 150))
            prev[pid] = p
            mp[pid] = {"all": {"icetime": row["timeOnIcePerGame"] * gp, "ixg": random.uniform(0.5, 5),
                               "goals": row["goals"], "sog": row["shots"], "attempts": 0,
                               "hd_shots": random.randint(2, 20), "hd_xg": 1, "a1": 1,
                               "xgf_pct": random.uniform(.4, .6), "cf_pct": .5,
                               "oz_starts": 1, "dz_starts": 1, "game_score": 1},
                       "5on5": {"xgf_pct": random.uniform(.4, .6)}}
    return cur, prev, mp


CUR, PREV, MP = fake_players()
NOW = datetime.now(timezone.utc)


def fake_week(date_str):
    d0 = datetime.fromisoformat(date_str).date()
    out = []
    for k in range(7):
        d = d0 + timedelta(days=k)
        teams = TEAMS[:]
        random.shuffle(teams)
        games = []
        for j in range(0, random.choice([4, 6, 10, 12]), 2):
            start = (NOW + timedelta(minutes=60 + j)).isoformat().replace("+00:00", "Z")
            games.append({"gameType": 2, "season": 20262027, "startTimeUTC": start,
                          "homeTeam": {"abbrev": teams[j]}, "awayTeam": {"abbrev": teams[j + 1]}})
        out.append({"date": d.isoformat(), "games": games})
    return out


def fake_skaters(season_id=None, date_from=None, date_to=None):
    if date_from:
        return {pid: dict(r, gamesPlayed=3) for pid, r in list(CUR.items())[::3]}
    return CUR if season_id == 20262027 else PREV


def fake_espn(year, league, team_id, s2, swid):
    players = {}
    ids = list(CUR)
    for n, pid in enumerate(ids):
        r = CUR[pid]
        status = "MINE" if n % 12 == 0 else ("ROSTERED" if n % 3 == 0 else ("WAIVERS" if n % 17 == 0 else "FREEAGENT"))
        on = 1 if status == "MINE" else (2 if status == "ROSTERED" else None)
        players.setdefault(espn.norm(r["skaterFullName"]), []).append(
            {"name": r["skaterFullName"], "key": espn.norm(r["skaterFullName"]),
             "pos": "D" if r["positionCode"] == "D" else "C", "injury": "ACTIVE",
             "owned_pct": 1, "on_team": on, "status": status, "ir": False})
    return players, {1: "STY", 2: "RIV"}


nhl.schedule_week = fake_week
nhl.skaters = fake_skaters
nhl.team_abbrevs = lambda: {t: t for t in TEAMS}
nhl.team_defence = lambda s: {t: {"gamesPlayed": 9, "goalsAgainstPerGame": random.uniform(2.4, 3.8)} for t in TEAMS}
nhl.edge = lambda pid, s: {"zoneTimeDetails": {"offensiveZonePctg": .45, "offensiveZonePercentile": .8},
                           "skatingSpeed": {"speedMax": {"imperial": 22.4, "percentile": .82}},
                           "topShotSpeed": {"imperial": 88, "percentile": .7}}
moneypuck.load = lambda y: MP
nhl.headshot = lambda pid: "https://assets.nhle.com/mugs/nhl/20262027/EDM/8481617.png"
espn.load = fake_espn


def run_case(with_espn):
    env = {"FORCE": "1", "DRY_RUN": "1"}
    if with_espn:
        env.update(ESPN_LEAGUE_ID="1", ESPN_TEAM_ID="1", ESPN_S2="x", ESPN_SWID="{x}")
    else:
        for k in ("ESPN_LEAGUE_ID", "ESPN_TEAM_ID", "ESPN_S2", "ESPN_SWID"):
            os.environ.pop(k, None)
    os.environ.update(env)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main.run()
    payload = json.loads(buf.getvalue())
    size = len(json.dumps(payload, separators=(",", ":")).encode())
    assert size < 2000, size
    mv = payload["merge_variables"]
    assert mv["mode"] in ("pick", "hold")
    return payload, size


if __name__ == "__main__":
    for flag in (True, False):
        payload, size = run_case(flag)
        print(f"--- ESPN={flag}  {size} bytes")
        print(json.dumps(payload, indent=1))
