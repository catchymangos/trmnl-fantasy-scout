# TRMNL Fantasy Scout

One fantasy hockey move a day, on your TRMNL, about an hour before the first puck drop.

The scout reads the NHL's own stats feeds, MoneyPuck expected-goals data and NHL EDGE
tracking, scores every skater in your league's points format, and puts **one** player on
the screen with a label, a heat rating out of 100, the reasons, who to drop, and the
advanced stats behind it. If nothing clears the bar, it says **Hold**.

## Labels

| Label | Meaning |
|---|---|
| STREAM | Free agent who helps this week, mostly through games into empty lineup slots |
| BREAKOUT | Free agent whose role just changed (PP time, total TOI, recent ice time, shot rate) |
| STASH | Injured free agent worth an IR slot |
| BUY LOW | On another roster; shots and xG are ahead of his points |
| SELL HIGH | On your roster; scoring well above his expected goals |

## How the pick is made

- **Projection:** per-game rates in your scoring (G 2, A 1, PPP/SHP +0.5, hit 0.1, block 0.5).
  Goals blend actual and expected goals. Early-season samples are shrunk toward last season,
  scaled for this season's ice time and power-play time.
- **Lineup fit:** for each remaining day this week, it rebuilds your best daily lineup
  (9F / 5D / 1 UTIL) with and without the add, so value comes from games that actually make
  your lineup, minus the player you'd drop.
- **Opponent:** scoring is scaled by the opponent's goals against per game.
- **Heat:** expected fantasy points gained, where 6 points = 100. Below 40, it holds.

Tune any of this in `scout/config.py`.

## Data

- NHL stats API (`api.nhle.com`, `api-web.nhle.com`): skater stats, TOI and PP TOI,
  hits, blocks, schedule, team goals against, NHL EDGE tracking.
- MoneyPuck season skater data: individual xG, high-danger shots, on-ice xGF%.
  Data courtesy of [MoneyPuck.com](https://moneypuck.com).
- ESPN fantasy API (optional): your roster, other rosters, free agents and waivers.

## Setup

Add these as repository secrets (Settings > Secrets and variables > Actions):

| Secret | Where to find it |
|---|---|
| `TRMNL_WEBHOOK_URL` | TRMNL > Plugins > Fantasy Scout > Webhook URL |
| `ESPN_LEAGUE_ID` | The `leagueId=` number in your ESPN league URL |
| `ESPN_TEAM_ID` | The `teamId=` number on your team page |
| `ESPN_S2`, `ESPN_SWID` | Cookies from fantasy.espn.com while signed in (browser dev tools > Application > Cookies) |

Without the ESPN secrets it still runs, but compares against a generic replacement level
and can't check who's free or build your lineup.

## Running

The workflow runs every 30 minutes during the day and sends once, inside the 75 minutes
before the first game. Run it by hand from Actions > Fantasy scout > Run workflow; by
default a manual run is a dry run that prints the pick in the log.

`python tests/test_offline.py` runs the whole pipeline on fake data with no network.
