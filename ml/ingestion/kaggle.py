"""Convert a local relational F1 Kaggle ZIP/directory into FASTLANE source history.

This prepares data only. It never downloads data or trains a model.
"""
import argparse
import csv
import io
import json
import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path


def read_tables(source):
    required = ["races.csv", "results.csv", "qualifying.csv", "drivers.csv", "constructors.csv", "circuits.csv"]
    if source.is_dir():
        candidates = list(source.rglob("*.csv"))
        mapping = {}
        for filename in required:
            matches = [p for p in candidates if p.name == filename]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one {filename}; found {len(matches)}")
            mapping[filename] = matches[0]
        return {name: list(csv.DictReader(path.open(encoding="utf-8-sig", newline=""))) for name, path in mapping.items()}
    with zipfile.ZipFile(source) as archive:
        result = {}
        for filename in required:
            names = [name for name in archive.namelist() if name.rsplit("/", 1)[-1] == filename]
            if len(names) != 1:
                raise ValueError(f"Expected exactly one {filename}; found {len(names)}")
            with archive.open(names[0]) as stream:
                result[filename] = list(csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")))
        return result


def present(value):
    return value is not None and str(value).strip() not in {"", "\\N", "nan", "NaN"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Kaggle archive ZIP or extracted folder")
    parser.add_argument("--history-since", type=int, default=2000, help="Warmup history for circuit priors and rolling form")
    parser.add_argument("--through-season", type=int, default=2025)
    parser.add_argument("--output", type=Path, default=Path("data/processed/kaggle-2018-2025/history.json"))
    args = parser.parse_args()
    tables = read_tables(args.source)
    drivers = {r["driverId"]: r for r in tables["drivers.csv"]}
    constructors = {r["constructorId"]: r for r in tables["constructors.csv"]}
    circuits = {r["circuitId"]: r for r in tables["circuits.csv"]}
    results, qualifying = {}, {}
    for name, destination in [("results.csv", results), ("qualifying.csv", qualifying)]:
        for row in tables[name]:
            destination.setdefault(row["raceId"], []).append(row)

    def driver(value):
        d = drivers[value]
        return {"driverId": d["driverRef"], "givenName": d["forename"], "familyName": d["surname"], "code": d.get("code")}

    def constructor(value):
        c = constructors[value]
        return {"constructorId": c["constructorRef"], "name": c["name"]}

    history, excluded = [], []
    for race in sorted(tables["races.csv"], key=lambda r: (int(r["year"]), int(r["round"]))):
        year = int(race["year"])
        if not args.history_since <= year <= args.through_season:
            continue
        race_results = results.get(race["raceId"], [])
        if not race_results:
            excluded.append({"race_id": race["raceId"], "reason": "no completed race result"})
            continue
        if not present(race.get("time")):
            excluded.append({"race_id": race["raceId"], "reason": "unknown race start time"})
            continue
        circuit = circuits[race["circuitId"]]
        race_time = race["time"].strip()
        if not race_time.endswith("Z") and "+" not in race_time and "-" not in race_time:
            race_time += "Z"  # Kaggle documents race times as UTC, with mixed suffix conventions.
        item = {"season": str(year), "round": race["round"], "raceName": race["name"], "date": race["date"], "time": race_time,
                "source_race_id": race["raceId"],
                "Circuit": {"circuitId": circuit["circuitRef"], "circuitName": circuit["name"],
                            "Location": {"country": circuit["country"], "lat": circuit.get("lat"), "long": circuit.get("lng")}},
                "Results": [], "QualifyingResults": []}
        for row in race_results:
            item["Results"].append({"Driver": driver(row["driverId"]), "Constructor": constructor(row["constructorId"]),
                                    "position": row["positionOrder"], "grid": row["grid"] if present(row["grid"]) else "0", "status_id": row["statusId"]})
        for row in qualifying.get(race["raceId"], []):
            q = {"Driver": driver(row["driverId"]), "Constructor": constructor(row["constructorId"]), "position": row["position"]}
            for phase in ["q1", "q2", "q3"]:
                if present(row.get(phase)):
                    q[phase.upper()] = row[phase]
            item["QualifyingResults"].append(q)
        for prefix, field in [("fp1", "FirstPractice"), ("fp2", "SecondPractice"), ("fp3", "ThirdPractice"), ("quali", "Qualifying"), ("sprint", "Sprint")]:
            if present(race.get(prefix + "_date")):
                item[field] = {"date": race[prefix + "_date"], "time": race.get(prefix + "_time")}
        history.append(item)
    if not history:
        raise ValueError("No eligible historical race records found")
    payload = {"source": "Local Kaggle relational F1 dataset (Arths17/f1-dataset)",
               "source_reference": "https://github.com/Arths17/f1-dataset", "parser_version": "kaggle-relational-v1",
               "fetched_at": datetime.now(timezone.utc).isoformat(), "timestamp_meaning": "local import time; upstream historical publication times are not verified",
               "source_path": str(args.source), "source_archive_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest() if args.source.is_file() else None,
               "races": history, "excluded": excluded}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "history_races": len(history), "seasons": sorted({int(r['season']) for r in history}),
                      "excluded": len(excluded), "note": "Prepared historical records only; model training was not run."}, indent=2))


if __name__ == "__main__":
    main()
