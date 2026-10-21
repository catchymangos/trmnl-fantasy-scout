"""Turn a pick into up to three claims, each backed by the stats that prove it.

A claim is {"k": KIND, "h": headline, "ev": [{"l": label, "v": value, "p": pct|None}]}.
The label decides which claim leads: schedule for a stream, deployment for a
breakout, chance creation for a buy low, finishing luck for a sell high.
"""
from .model import mmss, per_game, percentile

LEAD = {
    "STREAM": ["SCHEDULE", "DEPLOYMENT", "CHANCES", "FLOOR"],
    "BREAKOUT": ["DEPLOYMENT", "CHANCES", "SCHEDULE", "FLOOR"],
    "BUY LOW": ["CHANCES", "DEPLOYMENT", "FLOOR", "SCHEDULE"],
    "SELL HIGH": ["LUCK", "CHANCES", "DEPLOYMENT"],
    "STASH": ["RETURN", "DEPLOYMENT", "CHANCES"],
}

# One icon family: 24px grid, 2.25 stroke, square caps, no fills except dots.
ICONS = {
    "SCHEDULE": '<rect x="3.5" y="5.5" width="17" height="15"/><path d="M3.5 10.5h17M8 3v5M16 3v5"/><path d="M7.5 14.5h2M11 14.5h2M14.5 14.5h2M7.5 17.5h2"/>',
    "DEPLOYMENT": '<circle cx="12" cy="14" r="7"/><path d="M12 14V10M9.5 3h5M12 3v4M18 7.5l1.5-1.5"/>',
    "CHANCES": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 11v2M11 12h2"/>',
    "FLOOR": '<path d="M12 3l8 3v6c0 4.5-3.5 7.8-8 9-4.5-1.2-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
    "LUCK": '<rect x="4" y="4" width="16" height="16"/><path d="M8.5 8.5h.01M15.5 8.5h.01M12 12h.01M8.5 15.5h.01M15.5 15.5h.01" stroke-width="3"/>',
    "RETURN": '<path d="M9.5 3.5h5v6h6v5h-6v6h-5v-6h-6v-5h6z"/>',
}
SHORT = {"SCHEDULE": "SCHED", "DEPLOYMENT": "ROLE", "CHANCES": "CHANCES",
         "FLOOR": "FLOOR", "LUCK": "LUCK", "RETURN": "RETURN"}


def _pool(players, mp, grp, fn):
    out = []
    for p in players:
        if p["grp"] != grp or p["proj"]["cur"]["gp"] < 3:
            continue
        v = fn(p, mp.get(p["pid"]) or {})
        if v is not None:
            out.append(v)
    return out


def ixg60(m):
    a = m.get("all")
    if not a or a["icetime"] < 600:
        return None
    return a["ixg"] / (a["icetime"] / 3600)


def build(pick, ctx):
    p, label = pick["p"], pick["label"]
    pid, grp, team = p["pid"], p["grp"], p["team"]
    c, prev = p["proj"]["cur"], p["proj"]["prev"]
    mp = ctx["mp"].get(pid) or {}
    recent = per_game(ctx["recent"][pid]) if ctx["recent"].get(pid) else None
    claims = {}

    # ---- SCHEDULE: games left and how soft the opposition is
    days = pick.get("days") or ctx["this_week"]
    opps = [ctx["team_games"][d][team][0] for d in days if team in ctx["team_games"].get(d, {})]
    if opps:
        ranks = ctx["ga_rank"]
        soft = [o for o in opps if ranks.get(o, 99) <= 10 and ctx["ga"].get(o, 0) > ctx["ga_avg"]]
        ga = [ctx["ga"][o] for o in opps if o in ctx["ga"]]
        head = f"{len(opps)} game{'s' if len(opps) != 1 else ''} left this week"
        if soft:
            head += f", {len(soft)} vs bottom-10 defences ({', '.join(soft[:3])})"
        if ga and sum(ga) / len(ga) < ctx["ga_avg"] * 0.95 and not soft:
            head += ", against tighter defences"
        ev = []
        if ga:
            ev.append({"l": "Opp GA/g", "v": f"{sum(ga) / len(ga):.2f}", "p": None,
                       "n": f"league {ctx['ga_avg']:.2f}"})
        if pick.get("empty"):
            ev.append({"l": "Into empty slots", "v": f"{pick['empty']} of {len(opps)}", "p": None})
        strength = len(opps) / 4 + len(soft) * 0.25 + (pick.get("empty") or 0) * 0.2
        claims["SCHEDULE"] = (strength, {"k": "SCHEDULE", "h": head, "ev": ev})

    # ---- DEPLOYMENT: ice time and PP time, recent vs season vs last season
    ev, parts, strength = [], [], 0.0
    if recent and recent["gp"] >= 2:
        d_toi = recent["toi"] - c["toi"]
        d_pp = recent["pp_toi"] - c["pp_toi"]
        if d_toi >= 45:
            parts.append(f"ice time up the last {recent['gp']} games")
            ev.append({"l": f"TOI last {recent['gp']}", "v": mmss(recent["toi"]), "p": None,
                       "n": f"season {mmss(c['toi'])}"})
            strength += d_toi / 120
        if d_pp >= 30:
            parts.append("more power-play time")
            ev.append({"l": f"PP TOI last {recent['gp']}", "v": mmss(recent["pp_toi"]), "p": None,
                       "n": f"season {mmss(c['pp_toi'])}"})
            strength += d_pp / 60
    if prev and prev["gp"] >= 15:
        if c["pp_toi"] - prev["pp_toi"] >= 60 and not any("PP" in e["l"] for e in ev):
            parts.append("a real power-play role this year")
            ev.append({"l": "PP TOI/g", "v": mmss(c["pp_toi"]), "p": None,
                       "n": f"last year {mmss(prev['pp_toi'])}"})
            strength += (c["pp_toi"] - prev["pp_toi"]) / 90
        if c["toi"] - prev["toi"] >= 90 and len(ev) < 2:
            parts.append("bigger minutes than last year")
            ev.append({"l": "TOI/g", "v": mmss(c["toi"]), "p": None,
                       "n": f"last year {mmss(prev['toi'])}"})
            strength += (c["toi"] - prev["toi"]) / 180
    edge = ctx["edge"]
    if edge and parts:
        z = edge.get("zoneTimeDetails") or {}
        if z.get("offensiveZonePercentile") and z["offensiveZonePercentile"] >= 0.75 and len(ev) < 3:
            ev.append({"l": "O-zone time", "v": f"{z['offensiveZonePctg'] * 100:.0f}%",
                       "p": round(100 * z["offensiveZonePercentile"])})
    if parts:
        head = parts[0][0].upper() + parts[0][1:] + (", " + " and ".join(parts[1:]) if parts[1:] else "")
        claims["DEPLOYMENT"] = (strength, {"k": "DEPLOYMENT", "h": head, "ev": ev[:3]})

    # ---- CHANCES: is he generating real offence (and is it showing up yet)?
    v = ixg60(mp)
    if v is not None:
        pct = percentile(ctx["pool_ixg"][grp], v)
        diff = mp["all"]["goals"] - mp["all"]["ixg"]
        hd = mp["all"]["hd_shots"] / c["gp"] if c["gp"] else 0
        hd_pct = percentile(ctx["pool_hd"][grp], hd)
        if diff <= -1.0:
            head = f"Creating chances; {abs(diff):.1f} goals short of his xG, so goals are due"
        elif diff >= 1.5:
            head = "Chances are real, but he is finishing above them"
        else:
            head = "Chance creation backs up the production"
        ev = [{"l": "ixG/60", "v": f"{v:.2f}", "p": pct},
              {"l": "Goals vs xG", "v": f"{diff:+.1f}", "p": None}]
        if grp == "F":
            ev.insert(1, {"l": "HD shots/g", "v": f"{hd:.1f}", "p": hd_pct})
        f5 = (mp.get("5on5") or {}).get("xgf_pct")
        if f5 and len(ev) < 3:
            ev.append({"l": "On-ice xGF% 5v5", "v": f"{f5 * 100:.0f}%", "p": None})
        strength = (pct or 0) / 100 + max(0, -diff) * 0.3
        claims["CHANCES"] = (strength, {"k": "CHANCES", "h": head, "ev": ev[:3]})

    # ---- FLOOR: hits and blocks pay in this league
    if c["blocks"] * 0.5 + c["hits"] * 0.1 >= 0.6:
        bp = percentile(ctx["pool_blk"][grp], c["blocks"])
        hp = percentile(ctx["pool_hit"][grp], c["hits"])
        val = c["blocks"] * 0.5 + c["hits"] * 0.1
        claims["FLOOR"] = (val, {"k": "FLOOR",
                                 "h": f"{val:.1f} fpts/g from hits and blocks alone, even on quiet nights",
                                 "ev": [{"l": "Blocks/g", "v": f"{c['blocks']:.1f}", "p": bp},
                                        {"l": "Hits/g", "v": f"{c['hits']:.1f}", "p": hp}]})

    # ---- LUCK (sell high)
    if label == "SELL HIGH" and mp.get("all"):
        g, x = mp["all"]["goals"], mp["all"]["ixg"]
        shots = ctx["cur"][pid].get("shots") or 0
        claims["LUCK"] = (9, {"k": "LUCK", "h": f"{int(g)} goals on {x:.1f} expected; this rate won't hold",
                              "ev": [{"l": "Shooting %", "v": f"{100 * g / shots:.0f}%" if shots else "-", "p": None,
                                      "n": "league ~10%"},
                                     {"l": "Goals vs xG", "v": f"{g - x:+.1f}", "p": None}]})

    # ---- RETURN (stash)
    if label == "STASH" and prev:
        claims["RETURN"] = (9, {"k": "RETURN", "h": "Injured now; worth an IR slot for when he's back",
                                "ev": [{"l": "Proj fpts/g", "v": f"{p['proj']['fpg']:.2f}", "p": None},
                                       {"l": "Last year GP", "v": str(prev["gp"]), "p": None}]})

    order = LEAD.get(label, list(claims))
    lead = [claims[k][1] for k in order[:1] if k in claims]
    rest = sorted((v for k, v in claims.items() if k not in order[:1]), key=lambda x: -x[0])
    out = (lead + [v[1] for v in rest])[:3]
    for c in out:
        c["i"] = ICONS.get(c["k"], "")
        c["s"] = SHORT.get(c["k"], c["k"])
    return out
