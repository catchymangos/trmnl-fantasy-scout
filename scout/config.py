"""League settings and tuning knobs. Edit here, not in the model."""

# ESPN head-to-head points league scoring (skaters).
SCORING = {"g": 2.0, "a": 1.0, "ppp": 0.5, "hit": 0.1, "block": 0.5}

# Daily lineup slots for skaters.
SLOTS = {"F": 9, "D": 5, "UTIL": 1}

# Bigger = trust last season / league priors longer into the new season.
SHRINK = {"scoring": 12, "peripheral": 4}

# Role-change thresholds, in seconds per game.
SIGNAL = {
    "pp_toi_up": 60,       # PP time per game vs last season
    "toi_up": 90,          # total time per game vs last season
    "recent_toi_up": 75,   # last 7 days vs season
    "recent_pp_up": 45,
}

# How many days of "recent" form to look at.
RECENT_DAYS = 7

# Heat: fantasy points of expected gain that equal a 100 rating.
HEAT_FULL = 6.0
# Minimum heat to suggest anything. Below this, the screen says "Hold".
HEAT_MIN = 40

# Value of a trade (buy low) is discounted for the cost of making one.
TRADE_DISCOUNT = 0.35
# Games of rest-of-season value counted for buy-low / breakout adds.
HORIZON_GAMES = 10

# Send the screen once per day, this many minutes before the first puck drop.
LEAD_MINUTES = 75
TIMEZONE = "America/Toronto"
