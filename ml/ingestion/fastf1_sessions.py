"""Optional cached FastF1 practice/qualifying ingestion and coverage audit."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import fastf1
import numpy as np
import pandas as pd
from ml.features.build import lap_ms

ROOT = Path(__file__).resolve().parents[2]


def clean_laps(frame):
    valid = frame.LapTime.notna()
    for column in ("PitInTime", "PitOutTime"):
        if column in frame:
            valid &= frame[column].isna()
    if "IsAccurate" in frame:
        valid &= frame.IsAccurate.astype('boolean').fillna(False)
    if "Deleted" in frame:
        valid &= ~frame.Deleted.astype("boolean").fillna(True)
    if "TrackStatus" in frame:
        valid &= frame.TrackStatus.astype(str).isin(["1"])
    return frame[valid]


def summarize(laps, results):
    rows = []
    for _, driver in results.iterrows():
        subset = laps[laps.Driver == driver.Abbreviation]
        valid = clean_laps(subset)
        times = valid.LapTime.dt.total_seconds() * 1000
        color = str(driver.get("TeamColor", "888888"))
        extra=practice_statistics(valid)
        rows.append({"driver_id": str(driver.get("DriverId", driver.Abbreviation)), "name": str(driver.FullName),
                     "abbreviation": str(driver.Abbreviation), "team": str(driver.TeamName), "color": "#" + color.lstrip("#"),
                     "best_lap_ms": int(times.min()) if len(times) else None,
                     "representative_lap_ms": int(times.median()) if len(times) >= 5 else None,
                     "lap_count": len(valid), "quality": "small sample" if len(times) < 5 else "clean-lap aggregate",
                     "long_run_summary": None, **extra})
    fastest = min((r["best_lap_ms"] for r in rows if r["best_lap_ms"] is not None), default=None)
    for row in rows:
        row["gap_ms"] = row["best_lap_ms"] - fastest if row["best_lap_ms"] is not None and fastest is not None else None
    return sorted(rows, key=lambda r: r["best_lap_ms"] or float("inf"))


def practice_statistics(valid):
    """Shared historical/live aggregates; no race/qualifying information."""
    times=valid.LapTime.dt.total_seconds()*1000
    tyre=pd.to_numeric(valid.get('TyreLife',pd.Series(dtype=float)),errors='coerce')
    result={'lap_iqr_ms':float(times.quantile(.75)-times.quantile(.25)) if len(times)>=5 else None,
            'soft_fraction':float((valid.Compound=='SOFT').mean()) if len(valid) and 'Compound' in valid else None,
            'mean_tyre_age':float(tyre.mean()) if tyre.notna().any() else None,
            'long_run_lap_ms':None,'long_run_compound':None,'long_run_laps':0}
    required={'Stint','Compound','LapNumber','TyreLife'}
    if not len(times) or not required.issubset(valid.columns): return result
    runs=[]
    for (_,compound),group in valid.groupby(['Stint','Compound']):
        if compound not in {'SOFT','MEDIUM','HARD'}: continue
        group=group.sort_values('LapNumber')
        group=group[(group.TyreLife>=3)&(group.TyreLife<=20)&(group.LapTime.dt.total_seconds()*1000<=times.min()*1.07)]
        for _,block in group.groupby(group.LapNumber.diff().ne(1).cumsum()):
            if len(block)>=5: runs.append((float(block.LapTime.dt.total_seconds().median()*1000),compound,len(block)))
    if runs:
        pace,compound,n=min(runs)
        result.update(long_run_lap_ms=pace,long_run_compound=compound,long_run_laps=n)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--sessions", nargs="+", default=["FP1", "FP2", "FP3", "Q"])
    args = parser.parse_args()
    cache = ROOT / "data/raw/fastf1"
    cache.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(cache))
    sessions, coverage = [], []
    for name in args.sessions:
        try:
            session = fastf1.get_session(args.season, args.round, name)
            session.load(telemetry=False, weather=False, messages=True)
            rows = summarize(session.laps, session.results)
            coverage.append({"type": name, "status": "loaded", "drivers": len(rows), "valid_laps": sum(r["lap_count"] for r in rows),
                             "missing_best_laps": sum(r["best_lap_ms"] is None for r in rows), "source": "FastF1"})
            if name == "Q":
                for phase in ["Q1", "Q2", "Q3"]:
                    qrows = []
                    for row in rows:
                        result = session.results[session.results.Abbreviation == row["abbreviation"]].iloc[0]
                        value = result.get(phase)
                        qrows.append({**row, "best_lap_ms": int(value.total_seconds() * 1000) if pd.notna(value) else None,
                                      "representative_lap_ms": None, "lap_count": None, "quality": "phase result" if pd.notna(value) else "no phase time"})
                    fastest = min((r["best_lap_ms"] for r in qrows if r["best_lap_ms"] is not None), default=None)
                    for row in qrows:
                        row["gap_ms"] = row["best_lap_ms"] - fastest if row["best_lap_ms"] is not None and fastest is not None else None
                    sessions.append({"type": phase, "status": "historical", "drivers": qrows})
            else:
                sessions.append({"type": name, "status": "historical", "drivers": rows})
        except Exception as exc:
            coverage.append({"type": name, "status": "unavailable", "reason": type(exc).__name__})
            sessions.append({"type": name, "status": "unavailable", "drivers": []})
    target = ROOT / "data/processed" / f"{args.season}-{args.round:02d}-sessions.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"race_id": f"{args.season}-{args.round:02d}", "is_demo": False, "source": "FastF1",
               "fetched_at": datetime.now(timezone.utc).isoformat(), "parser_version": "fastf1-v1", "sessions": sessions, "coverage": coverage,
               "notice": "Historical session summaries. This retrieval timestamp does not prove pre-race publication."}
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(target), "coverage": coverage}, indent=2))


if __name__ == "__main__":
    main()
