# PRS Pro Series Ratings

Elo ratings for the PRS Pro Series, rebuilt automatically from Impact Scoring results and shown as a
leaderboard page (in `docs/`) that is embedded on the website.

## What happens automatically

GitHub checks **every hour**. The script knows every match's scheduled end time, so:

- **Within an hour of a match's scheduled end**, its results are downloaded and the whole season is
  recomputed. For the next 48 hours it re-checks hourly to pick up score corrections.
- **Once a day** (03:00 UTC = 10pm Central) it does a full check: finds new or rescheduled Pro Series
  matches and re-downloads anything from the last 14 days.
- Hours with nothing due finish in seconds, and nothing is saved unless a result actually changed.

Each update recomputes the whole season from the starting ratings in `data/seed.json`, in date
order, and the website shows the new numbers within a few minutes.

If a run fails, GitHub emails you. To run it right away: **Actions** tab → **Update ratings** →
**Run workflow**.

## Rating rules

- Spread 133, 2 points per head-to-head comparison, +50 / −25 cap per match, new shooters start at 500.
- Finishing order = Impact Scoring rank (tiebreakers already applied).
- Left out of a match: fewer than 50 impacts (5000 points). Disqualified shooters with 50+ impacts
  still count (set `drop_disqualified` to `true` to leave them out).
- Shooters are tracked by their **Impact Scoring shooter ID**, so name changes and typos don't split
  anyone into two people.

These live in `data/config.json` (`min_points`, `drop_disqualified`).

**Mulligan tab:** each shooter's season replayed without the one match that cost them the most
points, against the same opponents at their real ratings (nobody else's rating changes). Needs 2+
matches this season, and a mulligan never lowers a rating.

The leaderboard also shows each shooter's **last match +/−** next to their season change.

## Checking names (the only regular chore)

When a shooter shows up for the first time, their name is compared to everyone with an existing
rating. Anything that looks like the same person goes to **`data/name_review.csv`**:

- **"linked automatically - please confirm"**: a nickname or suffix difference (Andy / Andrew Slade).
  Their old rating was carried over.
- **"NOT linked - rated as new shooter"**: a similar spelling (Trey Fleming / Trey flemming). They
  were started at 500 until you confirm.

To fix one, edit `data/config.json` on GitHub (open the file → pencil icon → **Commit changes**):

| You want to… | Add a line to |
|---|---|
| Say an Impact Scoring name is the same person as a spreadsheet name | `"aliases"`: `"Trey Fleming": "Trey flemming"` |
| Link by shooter ID instead (safest) | `"id_links"`: `"503": "Trey flemming"` |
| Say two flagged names are **different** people (stop flagging) | `"not_same_person"`: `[503, "Trey flemming"]` |
| Skip a match entirely | `"exclude_matches"`: `"9999": "reason"` |

The next run (or **Run workflow**) recalculates everything with the fix.

## Files

| Path | What it is |
|---|---|
| `pipeline.py` | The update script |
| `prs_rating_engine.py` | The rating math (matches the Excel workbook exactly) |
| `names.py` | Name matching: nicknames, suffixes, similar spellings |
| `data/seed.json` | Ratings going into the season (from the workbook's 2025 Finale column) |
| `data/config.json` | Rules, name fixes, excluded matches |
| `data/matches.json` | Every Pro Series match found this season |
| `data/scores/` | Saved results for each match |
| `data/roster.json` | Shooter ID → name, with every spelling seen |
| `data/name_review.csv` | Names to double-check |
| `docs/` | The leaderboard page and its data (served by GitHub Pages) |
| `tools/seed_from_workbook.py` | Rebuilds `data/seed.json` from the workbook (for a new season) |

## New season

1. Run `python tools/seed_from_workbook.py "<workbook>.xlsx" "<column name>"`, or copy the final
   ratings from `docs/leaderboard.csv` into a new seed.
2. Update `season_label`, `season_start` and `season_end` in `data/config.json`.
