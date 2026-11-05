import numpy as np


def race_distribution(scores, temperature=1.0):
    scores = np.asarray(scores, dtype=float)
    if scores.size == 0 or not np.all(np.isfinite(scores)) or np.any(scores < 0):
        raise ValueError("Expected finite, nonnegative driver scores")
    if not np.isfinite(temperature) or temperature <= 0:
        raise ValueError("Temperature must be positive")
    logits = np.log(np.clip(scores, 1e-12, 1)) / temperature
    weights = np.exp(logits - logits.max())
    return weights / weights.sum()


def evaluate(frame, scores, temperature=1.0):
    scores = np.asarray(scores)
    losses, briers, hits, predictions = [], [], [], []
    for race_id in frame["race_id"].unique():
        indices = np.flatnonzero(frame["race_id"].to_numpy() == race_id)
        y = frame.iloc[indices]["target"].to_numpy(dtype=float)
        if y.sum() != 1:
            raise ValueError("Every evaluation race needs exactly one winner")
        p = race_distribution(scores[indices], temperature)
        winner = int(y.argmax())
        losses.append(float(-np.log(max(p[winner], 1e-12))))
        briers.append(float(np.square(p - y).sum()))
        # An equal-score baseline must not get 100% simply because historical
        # result rows happen to put the winner first. Give tied leaders fractional credit.
        leaders=np.isclose(p,p.max(),rtol=0,atol=1e-12)
        hits.append(float(leaders[winner])/int(leaders.sum()))
        predictions.extend({"race_id": race_id, "driver_id": frame.iloc[k]["driver_id"], "probability": float(value), "target": int(y[n])} for n, (k,value) in enumerate(zip(indices,p)))
    if not losses:
        raise ValueError("No evaluation races")
    return {"log_loss": float(np.mean(losses)), "brier": float(np.mean(briers)), "top1_accuracy": float(np.mean(hits)), "races": len(losses)}, predictions


def fit_temperature(frame, scores):
    candidates = np.geomspace(.25, 4, 41)
    return float(min(candidates, key=lambda t: evaluate(frame, scores, t)[0]["log_loss"]))


def reliability(predictions):
    bins = []
    for low in np.arange(0, 1, .1):
        values = [p for p in predictions if low <= p["probability"] < low + .1 or low > .89 and p["probability"] == 1]
        bins.append({"lower": round(float(low), 1), "upper": round(float(low + .1), 1), "n": len(values),
                     "mean_probability": float(np.mean([p["probability"] for p in values])) if values else None,
                     "observed_win_rate": float(np.mean([p["target"] for p in values])) if values else None})
    return bins
