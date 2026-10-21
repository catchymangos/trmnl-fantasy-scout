"""Projection, lineup simulation, labelling and the single daily pick.

All values are in YOUR league's fantasy points:
G 2, A 1, PP/SH point +0.5, hit 0.1, block 0.5 (see config.py).
"""
from . import config as C

F_POS = {"C", "L", "R"}

# League-typical per-game rates used as a prior when a player has no last season.
DEFAULT_PRIOR = {
    "F": {"g": 0.14, "a": 0.20, "ppp": 0.07, "shp": 0.0, "hits": 1.0, "blocks": 0.4},
    "D": {"g": 0.05, "a": 0.20, "ppp": 0.05, "shp": 0.0, "hits": 1.1, "blocks": 1.4},
}


def group(pos):
    return "D" if pos == "D" else "F"


def per_game(row):
    gp = row.get("gamesPlayed") or 0
    if not gp:
        return None
    return {
        "gp": gp,
        "g": (row.get("goals") or 0) / gp,
        "a": (row.get("assists") or 0) / gp,
        "ppp": (row.get("ppPoints") or 0) / gp,
        "shp": (row.get("shPoints") or 0) / gp,
        "hits": (row.get("hits") or 0) / gp,
        "blocks": (row.get("blockedShots") or 0) / gp,
        "shots": (row.get("shots") or 0) / gp,
        "toi": row.get("timeOnIcePerGame") or 0,
        "pp_toi": row.get("ppTimeOnIcePerGame") or 0,
    }


def fp(r):
    s = C.SCORING
    scoring = s["g"] * r["g"] + s["a"] * r["a"] + s["ppp"] * (r["ppp"] + r["shp"])
    periph = s["hit"] * r["hits"] + s["block"] * r["blocks"]
    return scoring, periph


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def project(pid, cur, prev, mp):
    """Shrunk per-game projection that leans on xG and on role (TOI, PP TOI)."""
    row = cur[pid]
    c = per_game(row)
    if not c:
        return None
    grp = group(row.get("positionCode"))
    p = per_game(prev.get(pid, {})) if prev.get(pid) else None
    if p and p["gp"] >= 15:
        prior = dict(p)
        # Scale last season by this season's role.
        if p["toi"] > 0:
            r = _clamp(c["toi"] / p["toi"], 0.8, 1.25)
            prior["g"] *= r
            prior["a"] *= r
        if p["pp_toi"] > 30:
            prior["ppp"] *= _clamp(c["pp_toi"] / p["pp_toi"], 0.5, 2.0)
        elif c["pp_toi"] > 90:
            prior["ppp"] = max(prior["ppp"], DEFAULT_PRIOR[grp]["ppp"] * 2)
    else:
        prior = DEFAULT_PRIOR[grp]
    # Goals: blend actual finishing with expected goals when MoneyPuck has it.
    g_cur = c["g"]
    m = (mp.get(pid) or {}).get("all")
    if m and c["gp"]:
        g_cur = 0.4 * c["g"] + 0.6 * (m["ixg"] / c["gp"])
    gp = c["gp"]
    ks, kp = C.SHRINK["scoring"], C.SHRINK["peripheral"]
    proj = {
        "g": (gp * g_cur + ks * prior["g"]) / (gp + ks),
        "a": (gp * c["a"] + ks * prior["a"]) / (gp + ks),
        "ppp": (gp * c["ppp"] + ks * prior["ppp"]) / (gp + ks),
        "shp": (gp * c["shp"] + ks * prior.get("shp", 0)) / (gp + ks),
        "hits": (gp * c["hits"] + kp * prior["hits"]) / (gp + kp),
        "blocks": (gp * c["blocks"] + kp * prior["blocks"]) / (gp + kp),
    }
    scoring, periph = fp(proj)
    return {"scoring": scoring, "periph": periph, "fpg": scoring + periph, "cur": c, "prev": p}


# ---------- lineup simulation (daily lineups: 9F / 5D / 1 UTIL) ----------

def lineup_points(players):
    """players: list of (group, points). Best legal daily lineup total."""
    f = sorted((x for g, x in players if g == "F"), reverse=True)
    d = sorted((x for g, x in players if g == "D"), reverse=True)
    total = sum(f[:C.SLOTS["F"]]) + sum(d[:C.SLOTS["D"]])
    rest = sorted(f[C.SLOTS["F"]:] + d[C.SLOTS["D"]:], reverse=True)
    total += sum(rest[:C.SLOTS["UTIL"]])
    return total


def game_value(proj, opp_factor):
    return proj["scoring"] * opp_factor + proj["periph"]


def week_gain(cand, drop, roster, days, team_games, opp_factor):
    """Points the add (minus the drop) adds to your lineup over the given days.
    Returns (gain, games, empty_slot_games)."""
    gain, games, empty = 0.0, 0, 0
    for day in days:
        playing = team_games.get(day, {})
        on = [r for r in roster if r["team"] in playing]
        base = [(r["grp"], game_value(r["proj"], opp_factor(r["team"], day))) for r in on]
        after = [(r["grp"], game_value(r["proj"], opp_factor(r["team"], day)))
                 for r in on if drop is None or r["pid"] != drop["pid"]]
        if cand["team"] in playing:
            games += 1
            v = game_value(cand["proj"], opp_factor(cand["team"], day))
            with_c = lineup_points(after + [(cand["grp"], v)])
            if len([1 for g, _ in after if g == cand["grp"]]) < C.SLOTS[cand["grp"]]:
                empty += 1
        else:
            with_c = lineup_points(after)
        gain += with_c - lineup_points(base)
    return gain, games, empty


# ---------- signals ----------

def mmss(sec):
    sec = int(round(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def percentile(values, x):
    if not values:
        return None
    below = sum(1 for v in values if v < x)
    return round(100 * below / len(values))


def role_signals(proj, recent):
    """Role changes a blog won't have written about yet."""
    c, p = proj["cur"], proj["prev"]
    sig = []
    if p and p["gp"] >= 15:
        if c["pp_toi"] - p["pp_toi"] >= C.SIGNAL["pp_toi_up"]:
            sig.append(("pp", f"PP TOI {mmss(c['pp_toi'])}/g, was {mmss(p['pp_toi'])} last year"))
        if c["toi"] - p["toi"] >= C.SIGNAL["toi_up"]:
            sig.append(("toi", f"TOI {mmss(c['toi'])}/g, up {mmss(c['toi'] - p['toi'])} on last year"))
    if recent and recent["gp"] >= 2:
        if recent["toi"] - c["toi"] >= C.SIGNAL["recent_toi_up"]:
            sig.append(("trend", f"last {recent['gp']} GP at {mmss(recent['toi'])}/g, up {mmss(recent['toi'] - c['toi'])}"))
        if recent["pp_toi"] - c["pp_toi"] >= C.SIGNAL["recent_pp_up"]:
            sig.append(("pptrend", f"PP time up to {mmss(recent['pp_toi'])}/g in last {recent['gp']} GP"))
        if c["shots"] and recent["shots"] >= c["shots"] * 1.3 and recent["shots"] >= 2.5:
            sig.append(("shots", f"{recent['shots']:.1f} shots/g lately vs {c['shots']:.1f}"))
    return sig


def finishing(pid, cur, mp):
    row, m = cur[pid], (mp.get(pid) or {}).get("all")
    g = row.get("goals") or 0
    shots = row.get("shots") or 0
    shp = g / shots if shots else 0
    if not m:
        return {"g": g, "ixg": None, "diff": None, "shp": shp, "shots": shots}
    return {"g": g, "ixg": m["ixg"], "diff": g - m["ixg"], "shp": shp, "shots": shots}
