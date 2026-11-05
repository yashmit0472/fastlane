"""Shared, leakage-safe feature construction from historical result/qualifying rows."""
import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
FEATURE_VERSION = "qualifying-history-v2"
NUMERIC = ["qualifying_position", "qualifying_gap_s", "circuit_grid_prior", "recent_finish", "recent_win_rate", "team_recent_finish", "prior_starts"]
CATEGORICAL = ["driver_id", "constructor_id", "circuit_id"]


def lap_ms(value):
    if value is None or value == "":
        return None
    try:
        bits = str(value).split(":")
        seconds = float(bits[-1]) + (60 * float(bits[-2]) if len(bits) > 1 else 0)
        if not math.isfinite(seconds) or seconds <= 0:
            return None
        return int(round(seconds * 1000))
    except (ValueError, TypeError):
        return None


def race_start(race):
    return datetime.fromisoformat((race["date"] + "T" + race.get("time", "00:00:00Z")).replace("Z", "+00:00"))


def comparable_qualifying(qualifying, driver_id, teammate_id=None):
    by_driver={q['Driver']['driverId']:q for q in qualifying}
    row=by_driver.get(driver_id,{})
    phase=next((p for p in ('Q3','Q2','Q1') if lap_ms(row.get(p)) is not None),None)
    times=[lap_ms(q.get(phase)) for q in qualifying if phase and lap_ms(q.get(phase)) is not None]
    common=next((p for p in ('Q3','Q2','Q1') if lap_ms(row.get(p)) is not None and lap_ms(by_driver.get(teammate_id,{}).get(p)) is not None),None)
    return {'phase':phase,'gap_s':(lap_ms(row[phase])-min(times))/1000 if times else None,
        'teammate_phase':common,'teammate_gap_s':(lap_ms(row[common])-lap_ms(by_driver[teammate_id][common]))/1000 if common else None}


def historical_prior(history, circuit_id, position, cutoff, alpha=8):
    eligible = [r for r in history if race_start(r) < cutoff]
    local_w = local_n = global_w = global_n = 0
    for race in eligible:
        for result in race.get("Results", []):
            if int(result.get("grid", 0)) != position:
                continue
            winner = int(result["position"]) == 1
            global_n += 1
            global_w += winner
            if race["Circuit"]["circuitId"] == circuit_id:
                local_n += 1
                local_w += winner
    global_rate = (global_w + 1) / (global_n + 20)
    return (local_w + alpha * global_rate) / (local_n + alpha), local_n


def features_for_race(race, history, cutoff, include_target=False):
    start = race_start(race)
    if cutoff >= start:
        raise ValueError("Feature cutoff must be before target race start")
    # Sprint-format qualifying timing needs a separate availability policy; skip for v1.
    if race.get("Sprint") or race.get("SprintResults"):
        return []
    past = sorted([r for r in history if race_start(r) < cutoff and race_start(r) < start], key=race_start)
    qualifying = race.get("QualifyingResults", [])
    if not qualifying:
        return []
    qtimes = {q["Driver"]["driverId"]: next((lap_ms(q.get(phase)) for phase in ("Q3", "Q2", "Q1") if lap_ms(q.get(phase)) is not None), None) for q in qualifying}
    best = min((t for t in qtimes.values() if t is not None), default=None)
    rows = []
    outcomes = {r["Driver"]["driverId"]: int(r["position"]) for r in race.get("Results", [])}
    circuit_id = race["Circuit"]["circuitId"]
    for q in qualifying:
        driver = q["Driver"]["driverId"]
        constructor = q["Constructor"]["constructorId"]
        pos = int(q["position"])
        prior, n = historical_prior(past, circuit_id, pos, cutoff)
        recent = [r for p in past for r in p.get("Results", []) if r["Driver"]["driverId"] == driver][-5:]
        team = [r for p in past[-5:] for r in p.get("Results", []) if r["Constructor"]["constructorId"] == constructor]
        time = qtimes[driver]
        row = {"race_id": f"{race['season']}-{int(race['round']):02d}", "season": int(race["season"]),
               "race_date": start.isoformat(), "cutoff": cutoff.isoformat(), "feature_version": FEATURE_VERSION,
               "availability_policy": "estimated: race start minus 18h; non-sprint only; audit before live use",
               "driver_id": driver, "constructor_id": constructor, "circuit_id": circuit_id,
               "qualifying_position": pos, "qualifying_gap_s": comparable_qualifying(qualifying,driver)['gap_s'],
               "circuit_grid_prior": prior, "prior_starts": n,
               "recent_finish": sum(int(r["position"]) for r in recent) / len(recent) if recent else None,
               "recent_win_rate": sum(int(r["position"]) == 1 for r in recent) / len(recent) if recent else None,
               "team_recent_finish": sum(int(r["position"]) for r in team) / len(team) if team else None,
               "practice_available": False}
        if include_target:
            if driver not in outcomes:
                return []  # Do not evaluate an incomplete winner distribution.
            row["target"] = int(outcomes[driver] == 1)
        rows.append(row)
    if include_target and (sum(r["target"] for r in rows) != 1 or {r["driver_id"] for r in rows} != set(outcomes)):
        return []
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, default=ROOT / "data/processed/history.json")
    parser.add_argument("--first-season", type=int, default=None)
    parser.add_argument("--last-season", type=int, default=None)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/processed")
    args = parser.parse_args()
    source = json.loads(args.history.read_text())
    races = sorted(source["races"], key=race_start)
    rows = []
    coverage = []
    for race in races:
        if args.first_season is not None and int(race["season"]) < args.first_season:
            continue
        if args.last_season is not None and int(race["season"]) > args.last_season:
            continue
        cutoff = race_start(race) - timedelta(hours=18)
        features = features_for_race(race, races, cutoff, include_target=True)
        rows.extend(features)
        qualifying = race.get("QualifyingResults", [])
        coverage.append({"season": race["season"], "round": race["round"], "circuit": race["Circuit"]["circuitId"],
                         "result_drivers": len(race.get("Results", [])), "qualifying_drivers": len(qualifying),
                         "missing_times": sum(all(lap_ms(q.get(p)) is None for p in ("Q1", "Q2", "Q3")) for q in qualifying),
                         "feature_rows": len(features), "practice_coverage": "not yet imported",
                         "excluded_reason": "sprint or incomplete qualifying/winner" if not features else ""})
    if not rows:
        raise ValueError("No complete eligible races in the requested feature window")
    target = args.output_dir
    target.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(target / "features.csv", index=False)
    pd.DataFrame(coverage).to_csv(target / "coverage.csv", index=False)
    report = {"feature_version": FEATURE_VERSION, "races_seen": len(coverage), "history_races_available": len(races), "races_eligible": len({r['race_id'] for r in rows}),
              "driver_rows": len(rows), "source": source["source"], "fetched_at": source["fetched_at"],
              "limitations": ["Qualifying publication cutoffs are estimated, not archived.", "Sprint weekends are excluded.",
                              "Practice/long-run and weather are outside the qualifying feature set.", "Qualifying gaps compare drivers within their last completed phase."]}
    (target / "coverage.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
