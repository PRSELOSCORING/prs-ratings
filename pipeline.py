"""
Update the PRS Pro Series ratings.

    python pipeline.py            # discover matches, download new results, recompute, write the site
    python pipeline.py --offline  # recompute from the saved results only (no internet)

1. Discover Pro Series matches (series page + profiles of top-rated shooters).
2. Download results for every finished match (re-download recent ones to catch corrections).
3. Recompute the whole season from data/seed.json, in date order, keyed by Impact Scoring shooter id.
4. Write docs/leaderboard.json + docs/leaderboard.csv (the website) and data/roster.json + data/name_review.csv.
"""
import csv, json, os, sys, time, urllib.request
from datetime import datetime, timedelta, timezone

from prs_rating_engine import compute_match_ratings, rate_one, NEW_GUY_RATING
from names import Matcher, key

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA, SITE = os.path.join(ROOT, "data"), os.path.join(ROOT, "docs")
SCORES = os.path.join(DATA, "scores")
API = "https://app-api.impactscoring.net/rest/website/"
PROFILES_TO_SCAN = 40
SCORE_FIELDS = ("id", "name", "rank", "points", "stagesProgressCount", "stagesCount",
                "matchDisqualified", "matchHardDisqualified", "divisionName")


def load(name, default=None):
    p = os.path.join(DATA, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)


def api(path):
    for attempt in range(3):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "prs-ratings (weekly leaderboard update)"})
            with urllib.request.urlopen(req, timeout=90) as r:
                body = json.load(r)
            if body.get("errorCode") not in (0, None):
                raise RuntimeError(f"Impact Scoring error {body.get('errorCode')} for {path}")
            time.sleep(0.3)
            return body["payload"]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 1. discovery
# ---------------------------------------------------------------------------

def discover(cfg, known):
    series, checked = known["series"], set(known["not_series"])

    def add(m):
        mid = str(m["id"])
        if not (cfg["season_start"] <= (m.get("endDate") or "")[:10] <= cfg["season_end"]):
            return
        if mid not in series:
            print(f"  new match: {m['name'].strip()} ({m['endDate'][:10]})")
        series.setdefault(mid, {})
        series[mid].update({"id": m["id"], "name": m["name"].strip(), "start": m.get("startDate"),
                            "end": m.get("endDate"), "canceled": bool(m.get("canceled") or m.get("deleted"))})

    for m in api(f"getSeriesPageDataV2?id={cfg['series_id']}").get("upcomingMatches") or []:
        add(m)

    board = json.load(open(os.path.join(SITE, "leaderboard.json"), encoding="utf-8")) \
        if os.path.exists(os.path.join(SITE, "leaderboard.json")) else {"shooters": []}
    for s in board["shooters"][:PROFILES_TO_SCAN]:
        prof = api(f"getShooterProfile?id={s['id']}")
        for m in (prof.get("matches") or []) + (prof.get("recentMatches") or []):
            mid = str(m["id"])
            if mid in series or mid in checked:
                continue
            if not (cfg["season_start"] <= (m.get("endDate") or "")[:10] <= cfg["season_end"]):
                continue
            info = api(f"getMatch?id={mid}&withRegistrationInfo=false&includeLiveStreamingInfo=false")
            if info.get("seriesName") == "PRS Pro Series":
                add(m)
            else:
                checked.add(mid)
    known["not_series"] = sorted(checked, key=int)


# ---------------------------------------------------------------------------
# 2. results
# ---------------------------------------------------------------------------

def download_results(cfg, known):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for mid, m in sorted(known["series"].items(), key=lambda kv: kv[1]["end"] or ""):
        if m.get("canceled") or mid in cfg["exclude_matches"] or not m.get("end"):
            continue
        end = datetime.strptime(m["end"], "%Y-%m-%d %H:%M:%S")
        path = os.path.join(SCORES, f"{mid}.json")
        if end > now or (os.path.exists(path) and now - end > timedelta(days=cfg["refresh_days"])):
            continue
        info = api(f"getMatch?id={mid}&withRegistrationInfo=false&includeLiveStreamingInfo=false")
        if (info.get("match") or {}).get("canceled"):
            m["canceled"] = True
            print(f"  canceled: {m['name']}")
            continue
        shooters = api(f"getLiveScores?matchId={mid}&dividePoints=false").get("shooters") or []
        if not any((s.get("points") or 0) > 0 for s in shooters):
            print(f"  no results yet: {m['name']}")
            continue
        slim = sorted(({f: s.get(f) for f in SCORE_FIELDS} for s in shooters), key=lambda s: s["rank"] or 10**9)
        old = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None
        if slim != old:
            print(f"  {'updated' if old else 'downloaded'} results: {m['name']} ({len(slim)} shooters)")
            save(path, slim)


# ---------------------------------------------------------------------------
# 3. ratings
# ---------------------------------------------------------------------------

def counts(s, cfg):
    """Removed from a match: fewer than 50 impacts, or disqualified."""
    if (s.get("points") or 0) < cfg["min_points"]:
        return False
    if cfg["drop_disqualified"] and (s.get("matchDisqualified") or s.get("matchHardDisqualified")):
        return False
    return True


def recompute(cfg, known):
    seed = {k: v for k, v in load("seed.json")["shooters"].items()}
    aliases = {key(a): key(b) for a, b in cfg["aliases"].items()}
    id_links = {int(i): key(n) for i, n in cfg["id_links"].items()}
    not_same = {(int(i), key(n)) for i, n in cfg["not_same_person"]}
    matcher = Matcher(v["name"] for v in seed.values())

    rating, name_of, start_of, played, last, spellings, history = {}, {}, {}, {}, {}, {}, {}
    last_delta, appearances, fields = {}, {}, []
    claimed, review, rated = {}, [], []

    def link(sid, raw, match_name):
        k = id_links.get(sid) or aliases.get(key(raw), key(raw))
        if k in seed and k not in claimed:
            claimed[k] = sid
            return seed[k]["rating"], seed[k]["name"]
        hit = matcher.suggest(raw, exclude=claimed)
        if hit and (sid, key(hit[0])) not in not_same:
            other, reason, auto = hit
            ok = key(other)
            row = {"shooter_id": sid, "impact_name": raw, "possible_match": other,
                   "their_rating": round(seed[ok]["rating"], 1), "why": reason, "first_seen": match_name}
            if auto and ok not in claimed:
                claimed[ok] = sid
                review.append({**row, "action": "linked automatically - please confirm"})
                return seed[ok]["rating"], seed[ok]["name"]
            review.append({**row, "action": "NOT linked - rated as new shooter"})
        return NEW_GUY_RATING, raw

    matches = [m for mid, m in known["series"].items()
               if os.path.exists(os.path.join(SCORES, f"{mid}.json")) and mid not in cfg["exclude_matches"]
               and not m.get("canceled")]
    for m in sorted(matches, key=lambda m: (m["end"], m["id"])):
        shooters = json.load(open(os.path.join(SCORES, f"{m['id']}.json"), encoding="utf-8"))
        # Impact Scoring's rank already includes the tiebreaker, so finishing order is final order
        field_rows = sorted((s for s in shooters if counts(s, cfg)), key=lambda s: s["rank"])
        if not field_rows:
            continue
        field = []
        for place, s in enumerate(field_rows, 1):
            sid, raw = s["id"], " ".join((s["name"] or "").split())
            if sid not in rating:
                rating[sid], name_of[sid] = link(sid, raw, m["name"])
                start_of[sid] = rating[sid]
            spellings.setdefault(sid, set()).add(raw)
            field.append((place, sid, rating[sid]))
        new = compute_match_ratings(field)
        fields.append(field)
        for place, sid, before in field:
            played[sid] = played.get(sid, 0) + 1
            last[sid], last_delta[sid] = m["name"], new[sid] - before
            appearances.setdefault(sid, []).append((len(fields) - 1, place, new[sid] - before))
            history.setdefault(sid, []).append([m["id"], place, len(field), round(before, 2), round(new[sid], 2)])
        rating.update(new)
        rated.append({"id": m["id"], "name": m["name"], "end": m["end"][:10], "shooters": len(field)})

    mulligan = {sid: mulligan_rating(start_of[sid], apps, fields, sid) for sid, apps in appearances.items()}

    by_name = {}
    for sid in played:
        by_name.setdefault(key(name_of[sid]), []).append(sid)
    for ids in (v for v in by_name.values() if len(v) > 1):
        for sid in ids:
            review.append({"shooter_id": sid, "impact_name": name_of[sid], "possible_match": "(same name, different id)",
                           "their_rating": round(rating[sid], 1), "why": "shared name", "first_seen": "",
                           "action": "kept separate"})

    board = sorted(played, key=lambda s: rating[s], reverse=True)
    mull_rank = {s: i for i, s in enumerate(sorted(played, key=lambda s: mulligan[s][0], reverse=True), 1)}
    shooters = [{"rank": i, "id": s, "name": name_of[s], "rating": round(rating[s], 1),
                 "start": round(start_of[s], 1), "change": round(rating[s] - start_of[s], 1),
                 "matches": played[s], "last": last[s], "last_change": round(last_delta[s], 1),
                 "mulligan": round(mulligan[s][0], 1), "mulligan_rank": mull_rank[s],
                 "mulligan_drop": None if mulligan[s][1] is None else rated[mulligan[s][1]]["id"]}
                for i, s in enumerate(board, 1)]
    return shooters, rated, review, spellings, history, name_of


def mulligan_rating(start, apps, fields, sid):
    """
    The shooter's rating with their worst match of the season (biggest rating loss) thrown out.

    Their season is replayed without that match, against the opponents' actual incoming ratings,
    so nobody else's numbers change. Needs 2+ matches and at least one loss, and a mulligan never
    lowers a rating (a higher rating going into later matches can occasionally cost points).
    Returns (rating, index into fields of the dropped match or None).
    """
    def replay(skip):
        r = start
        for i, (fi, place, _d) in enumerate(apps):
            if i != skip:
                r = rate_one(place, r, [(p, rin) for p, s, rin in fields[fi] if s != sid])
        return r

    actual = replay(None)
    worst = min(range(len(apps)), key=lambda i: apps[i][2])
    if len(apps) < 2 or apps[worst][2] >= 0:
        return actual, None
    r = replay(worst)
    return (r, apps[worst][0]) if r > actual else (actual, None)


# ---------------------------------------------------------------------------
# 4. outputs
# ---------------------------------------------------------------------------

def write_outputs(cfg, shooters, rated, review, spellings, history, name_of):
    os.makedirs(SITE, exist_ok=True)
    board = {"updated": now_str(), "season": cfg["season_label"],
             "through": rated[-1] if rated else None, "match_count": len(rated),
             "matches": rated, "shooters": shooters}
    save(os.path.join(SITE, "leaderboard.json"), board)
    save(os.path.join(SITE, "history.json"), {str(k): v for k, v in history.items()})
    with open(os.path.join(SITE, "leaderboard.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        match_name = {m["id"]: m["name"] for m in rated}
        w.writerow(["Rank", "Shooter ID", "Name", "Rating", "Start of Season", "Season Change", "Matches",
                    "Last Match", "Last Match Change", "Mulligan Rank", "Mulligan Rating", "Mulligan Match Dropped"])
        for s in shooters:
            w.writerow([s["rank"], s["id"], s["name"], s["rating"], s["start"], s["change"], s["matches"],
                        s["last"], s["last_change"], s["mulligan_rank"], s["mulligan"],
                        match_name.get(s["mulligan_drop"], "")])
    save(os.path.join(DATA, "roster.json"),
         {str(s): {"name": name_of[s], "spellings": sorted(v)} for s, v in sorted(spellings.items())})
    with open(os.path.join(DATA, "name_review.csv"), "w", newline="", encoding="utf-8") as f:
        cols = ["shooter_id", "impact_name", "possible_match", "their_rating", "why", "action", "first_seen"]
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(review, key=lambda r: -r["their_rating"]):
            w.writerow(r)


def main():
    cfg, known = load("config.json"), load("matches.json", {"series": {}, "not_series": []})
    os.makedirs(SCORES, exist_ok=True)
    if "--offline" not in sys.argv:
        print("Discovering matches...")
        discover(cfg, known)
        print("Downloading results...")
        download_results(cfg, known)
        save(os.path.join(DATA, "matches.json"), known)
    shooters, rated, review, spellings, history, name_of = recompute(cfg, known)
    write_outputs(cfg, shooters, rated, review, spellings, history, name_of)
    flagged = sum(1 for r in review if r["action"].startswith("NOT linked"))
    print(f"\nRated {len(rated)} matches, {len(shooters)} shooters. Through: {rated[-1]['name'] if rated else '-'}")
    print(f"Name review: {len(review)} rows ({flagged} possible matches not linked) -> data/name_review.csv")
    for s in shooters[:10]:
        print(f"  {s['rank']:>2}. {s['name']:<24} {s['rating']:7.1f}")


if __name__ == "__main__":
    main()
