"""Serving summaries built strictly from earlier real events, plus forecast scoring."""
import math
from collections import defaultdict
from datetime import datetime, timezone
from ml.features.build import historical_prior, features_for_race, race_start, lap_ms
from ml.training.evaluate import race_distribution


def earlier(history, cutoff):
    return sorted([r for r in history if race_start(r) < cutoff], key=race_start)


def circuit_summary(history, circuit_id, cutoff, alpha=8):
    past = earlier(history, cutoff)
    races = [r for r in past if r["Circuit"]["circuitId"] == circuit_id]
    if not races:
        return None
    by_grid, drivers, teams = defaultdict(lambda: [0,0,0]), {}, {}
    for race in races:
        for result in race.get("Results", []):
            pos, grid = int(result["position"]), int(result.get("grid") or 0)
            if grid > 0:
                counts = by_grid[grid]
                counts[0] += 1; counts[1] += pos == 1; counts[2] += pos <= 3
            for store, key, name in [(drivers, result["Driver"]["driverId"], result["Driver"].get("givenName", "") + " " + result["Driver"].get("familyName", "")),
                                     (teams, result["Constructor"]["constructorId"], result["Constructor"].get("name", result["Constructor"]["constructorId"]))]:
                item = store.setdefault(key, {"name": name.strip(), "driver_id":key, "starts":0,"wins":0,"podiums":0})
                item["starts"] += 1; item["wins"] += pos == 1; item["podiums"] += pos <= 3
    positions = []
    for grid, (n,w,p) in sorted(by_grid.items()):
        positions.append({"grid_position":grid,"starts":n,"wins":w,"podiums":p,"win_rate":w/n,"podium_rate":p/n,
                          "smoothed_win_rate":historical_prior(past,circuit_id,grid,cutoff,alpha)[0]})
    years = sorted({int(r["season"]) for r in races})
    return {"circuit_id":circuit_id,"name":races[-1]["Circuit"].get("circuitName",circuit_id),
            "country":races[-1]["Circuit"].get("Location",{}).get("country",""),"is_demo":False,
            "years_covered":f"{years[0]}–{years[-1]}","race_count":len(races),"cutoff":cutoff.isoformat(),"alpha":alpha,
            "source":"Jolpica / imported historical results", "position_stats":positions,
            "driver_history":sorted(drivers.values(),key=lambda d:(-d["wins"],-d["podiums"])),
            "constructor_history":sorted(teams.values(),key=lambda d:(-d["wins"],-d["podiums"]))}


def driver_form(entry, history, circuit_id, cutoff):
    recent, gaps, circuit = [], [], []
    for race in earlier(history,cutoff):
        result = next((r for r in race.get("Results",[]) if r["Driver"]["driverId"]==entry["driver_id"]),None)
        if result:
            recent.append({"race":f"{race['season']} / {race['raceName']}","position":int(result["position"])})
            if race["Circuit"]["circuitId"]==circuit_id:
                circuit.append((int(race["season"]),int(result["position"])))
        qualifying = race.get("QualifyingResults",[])
        q = next((q for q in qualifying if q["Driver"]["driverId"]==entry["driver_id"]),None)
        if q:
            phase = next((p for p in ["Q3","Q2","Q1"] if lap_ms(q.get(p)) is not None),None)
            if phase:
                best = min(lap_ms(v[phase]) for v in qualifying if lap_ms(v.get(phase)) is not None)
                gaps.append({"race":f"{race['season']} / {race['raceName']}","gap_ms":lap_ms(q[phase])-best})
    years = sorted({y for y,p in circuit})
    return {**entry,"is_demo":False,"cutoff":cutoff.isoformat(),"recent_results":recent[-5:],"qualifying_gaps":gaps[-5:],
            "circuit_history":{"starts":len(circuit),"wins":sum(p==1 for y,p in circuit),"podiums":sum(p<=3 for y,p in circuit),
                               "years_covered":f"{years[0]}–{years[-1]}" if years else "No earlier starts"}}


def practice_forecast(race, entries, completed, history, stage, cutoff):
    if cutoff >= datetime.fromisoformat(race["scheduled_at"].replace("Z","+00:00")):
        raise ValueError("Cannot create a pre-race forecast after race start")
    latest = completed[stage]
    data = {d["driver_id"]: d for d in latest["drivers"]}
    usable = [e for e in entries if data.get(e["driver_id"],{}).get("best_lap_ms") is not None]
    if len(usable) < max(2,math.ceil(len(entries)*.7)):
        raise ValueError("Waiting for representative practice coverage of the provisional field")
    past = earlier(history,cutoff)
    allowed = ["FP1","FP2","FP3"][:["FP1","FP2","FP3"].index(stage)+1]
    if any(datetime.fromisoformat(s["observed_at"].replace("Z","+00:00"))>cutoff for name,s in completed.items() if name in allowed):
        raise ValueError("Practice input was observed after forecast cutoff")
    scores, factors = [], []
    for entry in entries:
        wins = starts = 0
        for previous in past[-5:]:
            for result in previous.get("Results",[]):
                if result["Driver"]["driverId"]==entry["driver_id"]:
                    starts += 1; wins += int(result["position"])==1
        prior = (wins+.5)/(starts+10)
        gaps = [session["drivers_by_id"][entry["driver_id"]].get("gap_ms") for name, session in completed.items()
                if name in allowed and entry["driver_id"] in session["drivers_by_id"]]
        gaps = [g/1000 for g in gaps if g is not None]
        mean_gap = sum(gaps)/len(gaps) if gaps else None
        scores.append(prior * (math.exp(-min(mean_gap,10)/1.0) if mean_gap is not None else 1))
        factors.append([f"Mean practice best-lap gap: +{mean_gap:.3f}s" if mean_gap is not None else "No eligible practice lap; earlier-form prior only",
                        f"Earlier five-race sample: {wins} wins / {starts} starts", "Provisional field from the latest completed Grand Prix"])
    probabilities = race_distribution(scores)
    drivers = [{**entry,"grid":None,"probability":float(p),"factors":f} for entry,p,f in zip(entries,probabilities,factors)]
    drivers.sort(key=lambda d:d["probability"],reverse=True)
    return {"race_id":race["race_id"],"model_version":"practice-pace-form-v1","cutoff":cutoff.isoformat(),"updated_at":cutoff.isoformat(),
            "race_start":race["scheduled_at"],"is_demo":False,"calibrated":False,"stage":stage,"method":"Experimental practice pace / earlier-form baseline",
            "status":"experimental","field_status":"provisional latest-race field",
            "notice":"Uncalibrated practice baseline; fuel loads, tyres and provisional entries limit comparability. This is not the qualifying-trained CatBoost model.",
            "evidence":[{"source":s.get('source','FastF1'),"session":name,"available_at":s["observed_at"]} for name,s in completed.items() if name in allowed],"drivers":drivers}


def score_forecasts(predictions, classification, observed_at):
    winners = [r for r in classification if int(r["position"])==1]
    if len(winners)!=1:
        raise ValueError("Published classification must have exactly one winner")
    winner = winners[0]["Driver"]
    winner_id = winner["driverId"]
    scores = []
    for prediction in predictions:
        probabilities = {d["driver_id"]:d["probability"] for d in prediction["drivers"]}
        if winner_id not in probabilities:
            scores.append({"stage":prediction.get("stage","Q"),"cutoff":prediction["cutoff"],"model_version":prediction["model_version"],
                           "status":"field mismatch","notice":"Actual winner was absent from this provisional field; forecast cannot be scored."})
            continue
        leader = max(prediction["drivers"],key=lambda d:d["probability"])
        scores.append({"stage":prediction.get("stage","Q"),"cutoff":prediction["cutoff"],"model_version":prediction["model_version"],"status":"scored",
                       "predicted_winner":leader["name"],"correct":leader["driver_id"]==winner_id,"winner_probability":probabilities[winner_id],
                       "log_loss":-math.log(max(probabilities[winner_id],1e-12)),
                       "brier":sum((p-int(driver==winner_id))**2 for driver,p in probabilities.items())})
        positions = {r['Driver']['driverId']:int(r['position']) for r in classification}
        outcomes = {}
        for target, places in [('podium',3),('top10',10)]:
            field = target+'_probability'
            if not all(d.get(field) is not None for d in prediction['drivers']): continue
            if set(probabilities) != set(positions):
                outcomes[target] = {'status':'field mismatch'}
                continue
            if sum(p <= places for p in positions.values()) != places:
                outcomes[target] = {'status':'incomplete classification'}
                continue
            pairs = [(max(1e-12,min(1-1e-12,d[field])),int(positions[d['driver_id']]<=places)) for d in prediction['drivers']]
            outcomes[target] = {'status':'scored','binary_log_loss':sum(-y*math.log(p)-(1-y)*math.log(1-p) for p,y in pairs)/len(pairs),
                'brier':sum((p-y)**2 for p,y in pairs)/len(pairs)}
        scores[-1]['outcomes'] = outcomes
    return {"status":"scored","is_demo":False,"winner":{"driver_id":winner_id,"name":winner.get("givenName","")+" "+winner.get("familyName","")},
            "updated_at":observed_at,"source":"Jolpica published classification","forecasts":scores,
            "notice":"Scores use the published classification and may change if that classification is revised." if scores else "No pre-race forecast was recorded for this event; no retrospective prediction has been invented."}
