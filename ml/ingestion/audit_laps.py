"""Audit an external lap CSV without merging it into prediction features."""
import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path


def canonical(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("data/processed/zenodo_audit.json"))
    args = parser.parse_args()
    if not args.source.is_file():
        raise FileNotFoundError("The CSV must finish downloading first. Pass its actual full path using --source.")
    counts, sessions, years = Counter(), Counter(), Counter()
    row_count = 0
    with args.source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        if not columns:
            raise ValueError("CSV has no header")
        lookup = {canonical(name): name for name in columns}
        session_fields = [lookup[name] for name in ["session", "sessiontype", "sessionname", "sessionidentifier"] if name in lookup]
        year_field = next((lookup[name] for name in ["year", "season"] if name in lookup), None)
        for row in reader:
            row_count += 1
            for name in columns:
                if row.get(name) in {None, "", "\\N", "nan", "NaN", "None"}:
                    counts[name] += 1
            for name in session_fields:
                sessions[f"{name}:{row.get(name, '')}"] += 1
            if year_field:
                years[row[year_field]] += 1
    practice = any(re.search(r"(^|:)(fp[123]|practice[ _]?[123]|free practice[ _]?[123])$", value, re.I) for value in sessions)
    report = {"source": str(args.source), "bytes": args.source.stat().st_size, "rows": row_count,
              "columns": columns, "year_counts": dict(years), "session_counts": dict(sessions),
              "missing_by_column": {name: counts[name] for name in columns}, "practice_session_labels_detected": practice,
              "decision": "Practice labels found; audit lap validity, units, event/driver keys and session timestamps before feature aggregation."
                          if practice else "Practice coverage is not established. Do not use current-event laps/weather as pre-race inputs without session provenance.",
              "note": "A column/sample audit does not certify source accuracy or historical availability. No training or feature merge was performed."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "rows": row_count, "columns": columns, "years": dict(years),
                      "sessions": dict(sessions), "decision": report["decision"]}, indent=2))


if __name__ == "__main__":
    main()
