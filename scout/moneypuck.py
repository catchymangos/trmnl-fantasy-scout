"""MoneyPuck season skater CSV (expected goals, danger, on-ice share).

Data courtesy of MoneyPuck.com. Keyed by NHL playerId. Returns {} if the
download fails, so the scout still runs on NHL data alone.
"""
import csv
import io

from .http import get

URL = "https://moneypuck.com/moneypuck/playerData/seasonSummary/{year}/regular/skaters.csv"


def _f(row, key):
    try:
        return float(row.get(key, "") or 0)
    except ValueError:
        return 0.0


def load(start_year):
    try:
        text = get(URL.format(year=start_year), timeout=60)
    except Exception as e:  # noqa: BLE001
        print(f"MoneyPuck unavailable: {e}")
        return {}
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        sit = row.get("situation")
        if sit not in ("all", "5on5", "5on4"):
            continue
        pid = int(row["playerId"])
        rec = out.setdefault(pid, {})
        rec[sit] = {
            "icetime": _f(row, "icetime"),
            "ixg": _f(row, "I_F_xGoals"),
            "goals": _f(row, "I_F_goals"),
            "sog": _f(row, "I_F_shotsOnGoal"),
            "attempts": _f(row, "I_F_shotAttempts"),
            "hd_shots": _f(row, "I_F_highDangerShots"),
            "hd_xg": _f(row, "I_F_highDangerxGoals"),
            "a1": _f(row, "I_F_primaryAssists"),
            "xgf_pct": _f(row, "onIce_xGoalsPercentage"),
            "cf_pct": _f(row, "onIce_corsiPercentage"),
            "oz_starts": _f(row, "I_F_oZoneShiftStarts"),
            "dz_starts": _f(row, "I_F_dZoneShiftStarts"),
            "game_score": _f(row, "gameScore"),
        }
    return out
