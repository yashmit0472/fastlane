"""Cached Jolpica client. No upstream calls in serving requests."""
import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[2]
BASE = "https://api.jolpi.ca/ergast/f1"
PARSER_VERSION = "jolpica-v1"


class Client:
    def __init__(self, cache_dir=None):
        self.cache = Path(cache_dir or os.getenv("DATA_CACHE_DIR", ROOT / "data/raw")) / "jolpica"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.http = httpx.Client(timeout=40, headers={"User-Agent": "FASTLANE/0.1 educational historical analysis"})

    def get(self, path, refresh=False):
        key = hashlib.sha256(path.encode()).hexdigest()[:20]
        target = self.cache / (key + ".json")
        if target.exists() and not refresh:
            return json.loads(target.read_text())["payload"]
        for attempt in range(4):
            try:
                response = self.http.get(BASE + "/" + path)
                if response.status_code in (429, 500, 502, 503, 504):
                    retry_after = response.headers.get("Retry-After", "")
                    time.sleep(min(float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1), 60))
                    continue
                response.raise_for_status()
                payload = response.json()
                if "MRData" not in payload:
                    raise ValueError("Unexpected Jolpica response schema")
                envelope = {"source": BASE + "/" + path, "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "parser_version": PARSER_VERSION, "payload": payload}
                temporary = target.with_suffix(".tmp")
                temporary.write_text(json.dumps(envelope), encoding="utf-8")
                temporary.replace(target)
                time.sleep(.55)
                return payload
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("Source unavailable after retries")

    def races(self, season, kind=None, refresh=False):
        records = {}
        offset = 0
        while True:
            path = f"{season}/{kind + '/' if kind else ''}?limit=100&offset={offset}"
            data = self.get(path, refresh)["MRData"]
            field = "Results" if kind == "results" else "QualifyingResults" if kind == "qualifying" else None
            for race in data["RaceTable"]["Races"]:
                key = (race["season"], race["round"])
                if key not in records:
                    records[key] = race
                elif field:
                    records[key][field].extend(race[field])
            offset += int(data["limit"])
            if offset >= int(data["total"]):
                break
        return list(records.values())


def normalize_schedule(race, fetched_at):
    circuit = race["Circuit"]
    return {"race_id": f"{race['season']}-{int(race['round']):02d}", "name": race["raceName"], "season": int(race["season"]),
            "round": int(race["round"]), "circuit_id": circuit["circuitId"], "circuit": circuit["circuitName"],
            "country": circuit["Location"]["country"], "timezone": "UTC", "scheduled_at": race["date"] + "T" + race.get("time", "00:00:00Z"),
            "status": "scheduled", "is_demo": False, "source": "Jolpica-F1", "source_updated_at": fetched_at}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", type=int, default=[2019, 2020, 2021, 2022, 2023, 2024])
    parser.add_argument("--schedule-only", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    client = Client()
    if args.schedule_only:
        from apps.api.database import initialize, SessionLocal, Race
        initialize()
        with SessionLocal() as db:
            for season in args.seasons:
                for r in client.races(season, refresh=args.refresh):
                    if "time" not in r:
                        continue  # Unknown start time is not a verified countdown input.
                    payload = normalize_schedule(r, datetime.now(timezone.utc).isoformat())
                    db.merge(Race(race_id=payload["race_id"], season=season, round=payload["round"],
                                  scheduled_at=payload["scheduled_at"], is_demo=False, payload=payload))
            db.commit()
        print("Saved verified schedule records.")
        return
    history = []
    for season in args.seasons:
        calendar = {int(r["round"]): r for r in client.races(season, refresh=args.refresh)}
        qualifying = {int(r["round"]): r for r in client.races(season, "qualifying", args.refresh)}
        results = client.races(season, "results", args.refresh)
        for race in results:
            for field in ("Sprint", "Qualifying", "FirstPractice", "SecondPractice", "ThirdPractice"):
                if field in calendar.get(int(race["round"]), {}):
                    race[field] = calendar[int(race["round"])][field]
            race["QualifyingResults"] = qualifying.get(int(race["round"]), {}).get("QualifyingResults", [])
            history.append(race)
        print(f"{season}: {len(results)} races, {sum(len(r['QualifyingResults']) for r in results)} qualifying rows", flush=True)
    target = ROOT / "data/processed/history.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"source": "Jolpica-F1", "parser_version": PARSER_VERSION,
                                  "fetched_at": datetime.now(timezone.utc).isoformat(), "races": history}), encoding="utf-8")
    print(f"Saved {len(history)} races to {target}")


if __name__ == "__main__":
    main()
