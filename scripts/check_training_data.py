"""Verify real feature tables before training; this script does not fit a model."""
import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

NUMERIC = ["qualifying_position", "qualifying_gap_s", "circuit_grid_prior", "prior_starts", "recent_finish", "recent_win_rate", "team_recent_finish"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, default=Path("data/processed/kaggle-2018-2025/features.csv"))
    parser.add_argument("--validation-season", type=int, default=2024)
    parser.add_argument("--test-season", type=int, default=2025)
    args = parser.parse_args()
    with args.features.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("Feature table is empty")
    assert args.validation_season < args.test_season
    assert len({(r["race_id"], r["driver_id"]) for r in rows}) == len(rows), "Duplicate driver/race keys"
    winners = Counter()
    for row in rows:
        cutoff = datetime.fromisoformat(row["cutoff"])
        start = datetime.fromisoformat(row["race_date"])
        assert cutoff.tzinfo and start.tzinfo and cutoff < start, "Cutoff/timezone problem"
        assert row["target"] in {"0", "1"}
        assert all(row[k] == "" or math.isfinite(float(row[k])) for k in NUMERIC), "Invalid numeric input"
        winners[row["race_id"]] += int(row["target"])
    assert all(count == 1 for count in winners.values()), "Each race needs exactly one winner"
    selectors = {"train": lambda y: y < args.validation_season,
                 "validation": lambda y: args.validation_season <= y < args.test_season,
                 "test": lambda y: y >= args.test_season}
    stats, groups = {}, {}
    for name, predicate in selectors.items():
        selected = [row for row in rows if predicate(int(row["season"]))]
        assert selected, f"Empty {name} split"
        groups[name] = {row["race_id"] for row in selected}
        stats[name] = {"rows": len(selected), "races": len(groups[name]), "seasons": sorted({int(row["season"]) for row in selected})}
    assert not (groups["train"] & groups["validation"] or groups["train"] & groups["test"] or groups["validation"] & groups["test"])
    report = {"checks": "PASS: unique keys, one winner per race, finite present features, aware cutoffs before start, disjoint chronological groups",
              "splits": stats, "training_executed": False}
    (args.features.parent / "preparation_checks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
