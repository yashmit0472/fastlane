"""Reproducibly construct small fictional display data, with conspicuous provenance."""
import json
from pathlib import Path

DRIVERS = [
    ("norris", "Lando Norris", "NOR", 4, "McLaren", "#ff9b42", 1, 31.8),
    ("max_verstappen", "Max Verstappen", "VER", 1, "Red Bull Racing", "#639aff", 2, 24.6),
    ("leclerc", "Charles Leclerc", "LEC", 16, "Ferrari", "#ef4444", 9, 14.2),
    ("piastri", "Oscar Piastri", "PIA", 81, "McLaren", "#ff9b42", 5, 10.4),
    ("hamilton", "Lewis Hamilton", "HAM", 44, "Mercedes", "#55d4bc", 3, 6.8),
    ("russell", "George Russell", "RUS", 63, "Mercedes", "#55d4bc", 4, 4.6),
    ("sainz", "Carlos Sainz", "SAI", 55, "Ferrari", "#ef4444", 10, 2.8),
    ("perez", "Sergio Pérez", "PER", 11, "Red Bull Racing", "#639aff", 13, 1.5),
    ("alonso", "Fernando Alonso", "ALO", 14, "Aston Martin", "#64c9a4", 7, 0.8),
    ("hulkenberg", "Nico Hülkenberg", "HUL", 27, "Haas", "#d2d4dc", 6, 0.5),
    ("tsunoda", "Yuki Tsunoda", "TSU", 22, "RB", "#8b94fa", 8, 0.4),
    ("colapinto", "Franco Colapinto", "COL", 43, "Williams", "#6bbdff", 12, 0.3),
    ("albon", "Alexander Albon", "ALB", 23, "Williams", "#6bbdff", 11, 0.3),
    ("ricciardo", "Daniel Ricciardo", "RIC", 3, "RB", "#8b94fa", 16, 0.2),
    ("stroll", "Lance Stroll", "STR", 18, "Aston Martin", "#64c9a4", 17, 0.2),
    ("ocon", "Esteban Ocon", "OCO", 31, "Alpine", "#ed80bd", 15, 0.2),
    ("gasly", "Pierre Gasly", "GAS", 10, "Alpine", "#ed80bd", 18, 0.1),
    ("bottas", "Valtteri Bottas", "BOT", 77, "Kick Sauber", "#a6df61", 19, 0.1),
    ("zhou", "Zhou Guanyu", "ZHO", 24, "Kick Sauber", "#a6df61", 20, 0.1),
    ("magnussen", "Kevin Magnussen", "MAG", 20, "Haas", "#d2d4dc", 14, 0.1),
]


def main():
    cutoff = "2024-09-21T16:00:00Z"
    race = {"race_id": "showcase-singapore", "name": "Singapore Grand Prix", "season": 2024, "round": 18,
            "circuit_id": "marina_bay", "circuit": "Marina Bay Street Circuit", "country": "Singapore",
            "scheduled_at": "2024-09-22T12:00:00Z", "timezone": "Asia/Singapore", "status": "showcase",
            "is_demo": True, "source": "Synthetic educational fixture", "source_updated_at": cutoff,
            "laps": 62, "length_km": 4.94, "corners": 19}
    drivers = [{"driver_id": d[0], "name": d[1], "abbreviation": d[2], "number": d[3], "team": d[4], "color": d[5],
                "grid": d[6], "probability": d[7] / 100,
                "factors": [f"Starting from P{d[6]}", "Relative practice pace", "Prior circuit conversion"]} for d in DRIVERS]
    sessions = []
    for j, session in enumerate(["FP1", "FP2", "FP3", "Q1", "Q2", "Q3"]):
        rows = []
        for i, driver in enumerate(drivers):
            eliminated = (session == "Q2" and driver["grid"] > 15) or (session == "Q3" and driver["grid"] > 10)
            missing = session == "FP3" and i == 19
            rows.append({"driver_id": driver["driver_id"], "name": driver["name"], "abbreviation": driver["abbreviation"],
                         "team": driver["team"], "color": driver["color"],
                         "best_lap_ms": None if eliminated or missing else int(91400 - j * 410 + (driver["grid"] - 1) * 91 + ((i * 73 + j * 53) % 180)),
                         "representative_lap_ms": None if j > 2 or missing else 96500 + i * 84 + j * 110,
                         "lap_count": None if eliminated or missing else (18 + (i * 3) % 12 if j < 3 else 5 + i % 3),
                         "quality": "eliminated" if eliminated else "unavailable" if missing else "synthetic",
                         "long_run_summary": None})
        valid = sorted([r for r in rows if r["best_lap_ms"] is not None], key=lambda r: r["best_lap_ms"])
        fastest = valid[0]["best_lap_ms"]
        for r in rows:
            r["gap_ms"] = r["best_lap_ms"] - fastest if r["best_lap_ms"] is not None else None
        sessions.append({"type": session, "status": "illustrative", "drivers": valid + [r for r in rows if r["best_lap_ms"] is None]})
    circuit = {"circuit_id": "marina_bay", "name": "Marina Bay Street Circuit", "country": "Singapore",
               "is_demo": True, "years_covered": "2010–2023 (illustrative sample)", "race_count": 12,
               "cutoff": cutoff, "alpha": 8, "source": "Synthetic educational fixture",
               "position_stats": [{"grid_position": i + 1, "starts": 12, "wins": w, "podiums": p,
                                    "win_rate": w / 12, "podium_rate": p / 12,
                                    "smoothed_win_rate": (w + 8 * prior) / 20}
                                   for i, (w, p, prior) in enumerate([(6, 10, .42), (3, 9, .24), (1, 7, .14), (1, 4, .08), (0, 3, .04), (1, 2, .03), (0, 1, .02), (0, 0, .01), (0, 0, .01), (0, 0, .01)])],
               "driver_history": [{"name": d["name"], "driver_id": d["driver_id"], "starts": 5, "wins": max(0, 2 - i), "podiums": max(0, 4 - i)} for i, d in enumerate(drivers[:6])],
               "constructor_history": [{"name": "Red Bull Racing", "starts": 24, "wins": 4, "podiums": 10}, {"name": "Mercedes", "starts": 24, "wins": 4, "podiums": 11}, {"name": "Ferrari", "starts": 24, "wins": 3, "podiums": 9}]}
    forms = [{**d, "is_demo": True, "cutoff": cutoff, "recent_results": [{"race": name, "position": ((i + j * 2) % 13) + 1} for j, name in enumerate(["Belgium", "Netherlands", "Italy", "Azerbaijan"])],
              "qualifying_gaps": [{"race": name, "gap_ms": 110 + i * 61 + j * 30} for j, name in enumerate(["Belgium", "Netherlands", "Italy", "Azerbaijan"])],
              "circuit_history": {"starts": 5, "wins": max(0, 2 - i), "podiums": max(0, 4 - i), "years_covered": "Illustrative prior seasons"}} for i, d in enumerate(drivers)]
    output = {"race": race, "prediction": {"race_id": race["race_id"], "model_version": "showcase-v1", "cutoff": cutoff,
              "updated_at": cutoff, "race_start": race["scheduled_at"], "is_demo": True, "calibrated": False, "status": "illustrative", "drivers": drivers},
              "weekend": {"race_id": race["race_id"], "is_demo": True, "cutoff": cutoff, "updated_at": cutoff, "sessions": sessions}, "circuit": circuit, "forms": forms}
    target = Path(__file__).resolve().parents[1] / "data/sample/showcase.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
