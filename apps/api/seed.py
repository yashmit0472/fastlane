"""Seed explicitly synthetic UI fixtures. Never masquerade as a real forecast."""
import json
from pathlib import Path
from .database import initialize, SessionLocal, Race, save_snapshot
from .contracts import Forecast


def main():
    initialize()
    data = json.loads((Path(__file__).resolve().parents[2] / "data/sample/showcase.json").read_text(encoding="utf-8"))
    prediction = Forecast.model_validate(data["prediction"])
    with SessionLocal() as db:
        race = data["race"]
        if not db.get(Race, race["race_id"]):
            db.add(Race(race_id=race["race_id"], season=race["season"], round=race["round"],
                        scheduled_at=race["scheduled_at"], is_demo=True, payload=race))
        for key, entity, payload in [("prediction", race["race_id"], data["prediction"]),
                                     ("weekend", race["race_id"], data["weekend"]),
                                     ("circuit", race["circuit_id"], data["circuit"])]:
            save_snapshot(db, entity, key, "showcase-v1", data["prediction"]["cutoff"], payload)
        for driver in data["forms"]:
            save_snapshot(db, driver["driver_id"], "form", "showcase-v1", data["prediction"]["cutoff"], driver)
        db.commit()
    print("Seeded Singapore showcase: 20 synthetic driver probabilities, session summaries and circuit samples.")


if __name__ == "__main__":
    main()
