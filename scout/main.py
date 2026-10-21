"""Daily fantasy scout: pick ONE move for today and push it to a TRMNL screen.

Env:
  TRMNL_WEBHOOK_URL   TRMNL private plugin webhook (required to send)
  ESPN_LEAGUE_ID, ESPN_TEAM_ID, ESPN_S2, ESPN_SWID   (optional, recommended)
  FORCE=1     ignore the "75 min before first puck drop" window
  DRY_RUN=1   print the payload instead of sending it
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config as C
from . import espn, moneypuck, nhl, story
from .http import post_json
from .model import (finishing, group, mmss, percentile, project,
                    role_signals, week_gain, per_game)

TZ = ZoneInfo(C.TIMEZONE)


def log(*a):
    print(*a, file=sys.stderr)


def set_output(key, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{key}={value}\n")


# ---------------------------------------------------------------- schedule

def build_schedule(today):
    days = nhl.schedule_week(today.isoformat()) + nhl.schedule_week((today + timedelta(days=7)).isoformat())
    team_games, season = {}, None
    for d in days:
        for g in d["games"]:
            season = season or g.get("season")
            h, a = g["homeTeam"]["abbrev"], g["awayTeam"]["abbrev"]
            start = datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00"))
            team_games.setdefault(d["date"], {})[h] = (a, True, start)
            team_games.setdefault(d["date"], {})[a] = (h, False, start)
    return team_games, season


def first_puck(team_games, today):
    starts = [v[2] for v in team_games.get(today.isoformat(), {}).values()]
    return min(starts) if starts else None


# ---------------------------------------------------------------- main

def run():
    now = datetime.now(timezone.utc)
    today = now.astimezone(TZ).date()
    force = os.environ.get("FORCE") == "1"
    dry = os.environ.get("DRY_RUN") == "1"

    team_games, season = build_schedule(today)
    first = first_puck(team_games, today)
    if not first:
        log("No NHL games today; nothing to send.")
        return
    lead = (first - now).total_seconds() / 60
    if not force and not (0 < lead <= C.LEAD_MINUTES):
        log(f"First puck drop in {lead:.0f} min; outside the {C.LEAD_MINUTES}-min window.")
        return
    season = season or 20262027
    prev_season = int(f"{season // 10000 - 1}{season // 10000}")
    start_year = season // 10000

    sunday = today + timedelta(days=(6 - today.weekday()))
    this_week = [d for d in sorted(team_games) if d <= sunday.isoformat()]
    next_week = [d for d in sorted(team_games) if d > sunday.isoformat()]

    log("Loading NHL stats ...")
    cur = nhl.skaters(season_id=season)
    prev = nhl.skaters(season_id=prev_season)
    yday = today - timedelta(days=1)
    recent_rows = nhl.skaters(date_from=(today - timedelta(days=C.RECENT_DAYS)).isoformat(),
                              date_to=yday.isoformat())
    mp = moneypuck.load(start_year)
    log(f"  {len(cur)} skaters this season, {len(prev)} last season, MoneyPuck rows {len(mp)}")

    # Opponent strength: goals against per game relative to league average.
    abbrev = nhl.team_abbrevs()
    ga = {}
    for name, t in nhl.team_defence(season).items():
        if name in abbrev and t.get("gamesPlayed"):
            ga[abbrev[name]] = t.get("goalsAgainstPerGame") or 0
    ga_avg = (sum(ga.values()) / len(ga)) if ga else 3.0

    def opp_factor(team, day):
        g = team_games.get(day, {}).get(team)
        if not g or g[0] not in ga or not ga_avg:
            return 1.0
        return max(0.85, min(1.2, ga[g[0]] / ga_avg))

    # Projections.
    proj = {}
    for pid, row in cur.items():
        if (row.get("gamesPlayed") or 0) >= 2:
            pr = project(pid, cur, prev, mp)
            if pr:
                proj[pid] = pr

    # ESPN league (optional).
    league, teams = None, {}
    if all(os.environ.get(k) for k in ("ESPN_LEAGUE_ID", "ESPN_TEAM_ID", "ESPN_S2", "ESPN_SWID")):
        try:
            league, teams = espn.load(start_year + 1, os.environ["ESPN_LEAGUE_ID"],
                                      int(os.environ["ESPN_TEAM_ID"]),
                                      os.environ["ESPN_S2"], os.environ["ESPN_SWID"])
            log(f"  ESPN league loaded ({len(league)} names)")
        except Exception as e:  # noqa: BLE001
            log(f"ESPN unavailable, running without league context: {e}")
    else:
        log("  No ESPN secrets: scouting against a generic 6-team replacement level.")

    def rec(pid):
        row = cur[pid]
        pos = row.get("positionCode")
        return {
            "pid": pid, "name": row.get("skaterFullName"), "pos": pos, "grp": group(pos),
            "team": (row.get("teamAbbrevs") or "").split(",")[-1], "proj": proj[pid],
            "espn": espn.match(league, row.get("skaterFullName", ""), pos == "D") if league else None,
        }

    players = [rec(pid) for pid in proj]
    by_status = lambda s: [p for p in players if p["espn"] and p["espn"]["status"] in s]
    mine = [p for p in by_status({"MINE"}) if not p["espn"]["ir"]] if league else []

    # Generic replacement level when we can't see your roster:
    # 6 teams x (9F + 5D) starters plus a few on benches.
    repl = {}
    for grp, n in (("F", 6 * 10), ("D", 6 * 6)):
        vals = sorted((p["proj"]["fpg"] for p in players if p["grp"] == grp), reverse=True)
        repl[grp] = vals[min(n, len(vals) - 1)] if vals else 0

    games_in = lambda team, days: sum(1 for d in days if team in team_games.get(d, {}))

    # Percentile pools for advanced stats (players with a real sample).
    def mp_pool(grp, fn):
        out = []
        for p in players:
            m = (mp.get(p["pid"]) or {})
            if p["grp"] == grp and p["proj"]["cur"]["gp"] >= 3 and m.get("all"):
                v = fn(m)
                if v is not None:
                    out.append(v)
        return out

    ixg60 = lambda m: m["all"]["ixg"] / (m["all"]["icetime"] / 3600) if m["all"]["icetime"] > 600 else None
    ixg_pool = {g: mp_pool(g, ixg60) for g in ("F", "D")}

    candidates = []

    def consider(p, label, action, value, reasons, extra=None):
        heat = max(0, min(100, round(100 * value / C.HEAT_FULL)))
        candidates.append({"p": p, "label": label, "action": action, "value": value,
                           "heat": heat, "reasons": reasons, **(extra or {})})

    def reasons_for(p, days):
        rs = [txt for _, txt in role_signals(p["proj"], per_game(recent_rows.get(p["pid"], {})) if recent_rows.get(p["pid"]) else None)]
        fin = finishing(p["pid"], cur, mp)
        if fin["ixg"] is not None and fin["diff"] is not None:
            if fin["diff"] <= -1.5:
                rs.append(f"{fin['g']} G on {fin['ixg']:.1f} xG: goals are coming")
            elif fin["diff"] >= 2:
                rs.append(f"{fin['g']} G on {fin['ixg']:.1f} xG: running hot")
        m = mp.get(p["pid"]) or {}
        if m.get("all"):
            v = ixg60(m)
            pct = percentile(ixg_pool[p["grp"]], v) if v is not None else None
            if pct is not None and pct >= 80:
                rs.append(f"ixG/60 in {pct}th pct of {p['grp']}")
        c = p["proj"]["cur"]
        if p["grp"] == "D" and c["blocks"] >= 2.0:
            rs.append(f"{c['blocks']:.1f} blk + {c['hits']:.1f} hits/g")
        return rs, fin

    # ---- free agents and waivers: STREAM / BREAKOUT / STASH
    if league:
        pool = by_status({"FREEAGENT", "WAIVERS"})
    else:
        pool = players
    pool = sorted(pool, key=lambda p: p["proj"]["fpg"], reverse=True)[:80]

    for p in pool:
        waivers = bool(p["espn"] and p["espn"]["status"] == "WAIVERS")
        days = [d for d in this_week if not (waivers and d == today.isoformat())]
        injured = bool(p["espn"] and p["espn"]["injury"] in ("OUT", "INJURY_RESERVE"))
        recent = per_game(recent_rows.get(p["pid"], {})) if recent_rows.get(p["pid"]) else None
        sig = role_signals(p["proj"], recent)
        rs, fin = reasons_for(p, days)
        if league and mine:
            drops = sorted(mine, key=lambda r: r["proj"]["fpg"])[:3]
            best = None
            for d in drops:
                wk, gms, empty = week_gain(p, d, mine, days, team_games, opp_factor)
                ros = p["proj"]["fpg"] - d["proj"]["fpg"]
                v = wk + max(0, ros) * games_in(p["team"], next_week) * 0.8
                if best is None or v > best[0]:
                    best = (v, wk, gms, empty, ros, d)
            v, wk, gms, empty, ros, drop = best
        else:
            gms = games_in(p["team"], days)
            ros = p["proj"]["fpg"] - repl[p["grp"]]
            wk, empty, drop = max(0, ros) * gms, 0, None
            v = wk + max(0, ros) * games_in(p["team"], next_week) * 0.8
        if injured:
            prior = p["proj"]["prev"]
            if not prior:
                continue
            v = max(0, ros) * C.HORIZON_GAMES * 0.3
            label, action = "STASH", "Stash on IR"
            rs = [f"out now; {p['proj']['fpg']:.1f} pts/g once back"] + rs
        elif len(sig) >= 2 and ros > 0:
            label, action = "BREAKOUT", "Claim" if waivers else "Add"
        else:
            label, action = "STREAM", "Claim" if waivers else "Add"
            if gms:
                rs.insert(0, f"{gms} games left this week" + (f", {empty} into empty slots" if empty else ""))
        if v <= 0:
            continue
        consider(p, label, action, v, rs, {"drop": drop, "week_games": gms, "waivers": waivers,
                                             "days": days, "empty": empty})

    # ---- rostered elsewhere: BUY LOW (trade target)
    if league and mine:
        worst = min(r["proj"]["fpg"] for r in mine)
        for p in by_status({"ROSTERED"}):
            fin = finishing(p["pid"], cur, mp)
            c = p["proj"]["cur"]
            unlucky = (fin["diff"] is not None and fin["diff"] <= -1.5) or (fin["shots"] >= 15 and fin["shp"] < 0.06)
            volume = c["shots"] >= 2.3 or c["pp_toi"] >= 150
            gain = p["proj"]["fpg"] - worst
            if unlucky and volume and gain >= 0.4:
                actual = (cur[p["pid"]].get("points") or 0) / c["gp"]
                rs, _ = reasons_for(p, this_week)
                rs.insert(0, f"scoring {actual:.2f} pts/g, projects {p['proj']['fpg']:.1f} fpts/g")
                owner = teams.get(p["espn"]["on_team"], "another team")
                consider(p, "BUY LOW", f"Trade for (from {owner})",
                         gain * C.HORIZON_GAMES * C.TRADE_DISCOUNT, rs)

    # ---- on your roster: SELL HIGH
    for p in mine:
        fin = finishing(p["pid"], cur, mp)
        if fin["diff"] is not None and fin["diff"] >= 2 and fin["shp"] >= 0.2 and fin["g"] >= 4:
            rs, _ = reasons_for(p, this_week)
            rs.insert(0, f"shooting {fin['shp']*100:.0f}% on {fin['shots']} shots")
            consider(p, "SELL HIGH", "Shop in a trade", min(4.0, fin["diff"] * 0.9), rs)

    candidates.sort(key=lambda c: c["value"], reverse=True)
    pick = candidates[0] if candidates else None
    ga_rank = {t: i + 1 for i, t in enumerate(sorted(ga, key=lambda t: -ga[t]))}
    pools = {}
    for name, fn in (("pool_ixg", lambda p, m: story.ixg60(m)),
                     ("pool_hd", lambda p, m: m["all"]["hd_shots"] / p["proj"]["cur"]["gp"] if m.get("all") else None),
                     ("pool_blk", lambda p, m: p["proj"]["cur"]["blocks"]),
                     ("pool_hit", lambda p, m: p["proj"]["cur"]["hits"])):
        pools[name] = {g: story._pool(players, mp, g, fn) for g in ("F", "D")}
    ctx = {"mp": mp, "recent": recent_rows, "players": players, "cur": cur,
           "team_games": team_games, "this_week": this_week, "ga": ga, "ga_avg": ga_avg,
           "ga_rank": ga_rank, "season": season, **pools}
    payload = build_payload(pick, now, today, ctx)
    body = json.dumps(payload, separators=(",", ":"))
    log(f"Payload {len(body.encode())} bytes")
    if candidates:
        log("Top 5 considered:")
        for c in candidates[:5]:
            log(f"  {c['heat']:>3}  {c['label']:<9} {c['p']['name']} ({c['p']['team']})  value {c['value']:.2f}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # Surface the result as a run annotation so it is readable without the raw logs.
        top = "\n".join(f"{c['heat']:>3} {c['label']:<9} {c['p']['name']} ({c['p']['team']}) "
                        f"value {c['value']:.2f}" for c in candidates[:8])
        diag = (f"skaters {len(cur)} | last season {len(prev)} | recent {len(recent_rows)} | "
                f"moneypuck {len(mp)} | teams GA {len(ga)} | espn {'yes' if league else 'no'} | "
                f"first puck in {lead:.0f} min")
        note = f"{diag}\n\nTop considered:\n{top}\n\nPayload:\n{json.dumps(payload, indent=1)}"
        print("::notice title=Scout pick::" + note.replace("%", "%25").replace("\r", "").replace("\n", "%0A"))
    if dry:
        print(json.dumps(payload, indent=2))
        return
    url = os.environ.get("TRMNL_WEBHOOK_URL")
    if not url:
        raise SystemExit("TRMNL_WEBHOOK_URL is not set")
    status, text = post_json(url, payload)
    log(f"TRMNL responded {status}: {text[:200]}")
    if 200 <= status < 300:
        set_output("sent", "true")


# ---------------------------------------------------------------- screen payload

def short(name):
    parts = name.split()
    return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else name


def build_payload(pick, now, today, ctx):
    stamp = now.astimezone(TZ).strftime("%a %b %-d \u00b7 %-I:%M %p").upper()
    if not pick or pick["heat"] < C.HEAT_MIN:
        near = f"Closest: {pick['p']['name']} ({pick['label'].lower()}, heat {pick['heat']})" if pick else ""
        return {"merge_variables": {"mode": "hold", "updated": stamp, "near": near}}
    p = pick["p"]
    c = p["proj"]["cur"]
    g = ctx["team_games"].get(today.isoformat(), {}).get(p["team"])
    tonight = ""
    if g:
        tonight = f"{'vs' if g[1] else '@'} {g[0]} {g[2].astimezone(TZ).strftime('%-I:%M')}"
    ctx = dict(ctx, edge=nhl.edge(p["pid"], ctx["season"]))
    claims = story.build(pick, ctx)
    drop = pick.get("drop")
    goals = int(round(c["g"] * c["gp"]))
    assists = int(round(c["a"] * c["gp"]))
    mv = {
        "mode": "pick", "updated": stamp,
        "label": pick["label"], "action": pick["action"], "heat": pick["heat"],
        "name": p["name"], "team": p["team"], "pos": p["pos"], "tonight": tonight,
        "fpg": f"{p['proj']['fpg']:.2f}",
        "line": f"{c['gp']} GP \u00b7 {goals}G {assists}A \u00b7 {c['shots']:.1f} shots/g \u00b7 {mmss(c['toi'])} TOI",
        "claims": claims,
        "drop": f"Drop {short(drop['name'])} ({drop['proj']['fpg']:.2f} fpts/g)" if drop else "",
        "img": nhl.headshot(p["pid"]) or "",
    }
    if pick.get("waivers"):
        mv["action"] += " (waivers, clears tomorrow)"
    if not p.get("espn") and pick["label"] in ("STREAM", "BREAKOUT", "STASH"):
        mv["action"] += " (check he's free)"
    return {"merge_variables": mv}


if __name__ == "__main__":
    run()
