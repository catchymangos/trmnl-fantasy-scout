"""ESPN fantasy hockey league reader (private league via espn_s2 + SWID cookies).

Returns who is on your roster, who is on other rosters, and who is a free
agent or on waivers. Everything is optional: with no credentials the scout
still runs, it just can't check availability or your lineup.
"""
import json
import unicodedata

from .http import get_json

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fhl/seasons/{year}/segments/0/leagues/{league}"
POS = {1: "C", 2: "L", 3: "R", 4: "D", 5: "G"}
IR_SLOTS = {8}  # ESPN hockey lineup slot for injured reserve
INFO = ""


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return "".join(c for c in s.lower() if c.isalpha() or c == " ").strip()


def _player(p, on_team, status, slot=None):
    return {
        "espn_id": p.get("id"),
        "name": p.get("fullName", ""),
        "key": norm(p.get("fullName", "")),
        "pos": POS.get(p.get("defaultPositionId"), "?"),
        "injury": p.get("injuryStatus") or ("INJURED" if p.get("injured") else "ACTIVE"),
        "owned_pct": (p.get("ownership") or {}).get("percentOwned"),
        "on_team": on_team,
        "status": status,
        "ir": slot in IR_SLOTS,
    }


def load(year, league_id, team_id, espn_s2, swid):
    url = BASE.format(year=year, league=league_id)
    cookies = {"Cookie": f"espn_s2={espn_s2}; SWID={swid}"}
    league = get_json(url, params=[("view", "mRoster"), ("view", "mTeam")], headers=cookies)
    players, teams = {}, {}
    if not team_id:
        # Find your team from your SWID: ESPN lists owners and co-managers on each team.
        want = swid.strip().upper()
        for t in league.get("teams", []):
            owners = [str(o).upper() for o in (t.get("owners") or [])]
            if t.get("primaryOwner"):
                owners.append(str(t["primaryOwner"]).upper())
            if want in owners:
                team_id = t.get("id")
                break
    global INFO
    INFO = ("ESPN teams " + ", ".join(
        f"{t.get('id')}={t.get('abbrev') or t.get('name')}" for t in league.get("teams", []))
        + f" | yours: {team_id or 'not found'}")
    for t in league.get("teams", []):
        tid = t.get("id")
        teams[tid] = t.get("abbrev") or t.get("name") or f"Team {tid}"
        for e in (t.get("roster") or {}).get("entries", []):
            p = (e.get("playerPoolEntry") or {}).get("player") or {}
            status = "MINE" if tid == team_id else "ROSTERED"
            players.setdefault(norm(p.get("fullName", "")), []).append(
                _player(p, tid, status, e.get("lineupSlotId")))
    flt = {"players": {
        "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
        "limit": 500,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
    }}
    fa = get_json(url, params={"view": "kona_player_info"},
                  headers={**cookies, "x-fantasy-filter": json.dumps(flt)})
    for row in fa.get("players", []):
        p = row.get("player") or {}
        status = "WAIVERS" if row.get("status") == "WAIVERS" else "FREEAGENT"
        players.setdefault(norm(p.get("fullName", "")), []).append(_player(p, None, status))
    return players, teams


def match(players, name, is_d):
    """Find the ESPN record for an NHL skater by name, split by D vs F."""
    for c in players.get(norm(name), []):
        if c["pos"] == "G":
            continue
        if (c["pos"] == "D") == is_d:
            return c
    return None
