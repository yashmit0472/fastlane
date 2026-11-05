from typing import List, Optional
from datetime import datetime
import math
from pydantic import BaseModel, Field, model_validator


class ForecastDriver(BaseModel):
    driver_id: str
    name: str
    abbreviation: str
    number: int
    team: str
    color: str
    grid: Optional[int] = None
    probability: float = Field(ge=0, le=1)
    podium_probability: Optional[float] = Field(default=None, ge=0, le=1)
    top10_probability: Optional[float] = Field(default=None, ge=0, le=1)
    factors: List[str]
    observations: Optional[dict] = None
    model_associations: Optional[dict] = None


class Forecast(BaseModel):
    race_id: str
    model_version: str
    cutoff: datetime
    updated_at: datetime
    race_start: datetime
    is_demo: bool
    calibrated: bool
    status: str
    drivers: List[ForecastDriver]
    stage: str = "Q"
    method: str = "qualifying-history model"
    notice: Optional[str] = None
    field_status: str = "qualifying participants"
    evidence: List[dict] = []
    outcomes_model_version: Optional[str] = None
    inputs_signature: Optional[str] = None
    input_quality: Optional[dict] = None
    weather_context: Optional[dict] = None
    conditions_context: Optional[dict] = None
    baselines: Optional[List[dict]] = None

    @model_validator(mode="after")
    def validate_distribution(self):
        if self.cutoff.tzinfo is None or self.race_start.tzinfo is None:
            raise ValueError("Cutoffs and race starts must include a timezone")
        if self.cutoff >= self.race_start:
            raise ValueError("Prediction cutoff must precede race start")
        timestamps=[d.observations.get('available_at') for d in self.drivers if d.observations]
        timestamps += [e.get('available_at') for e in self.evidence]
        if self.weather_context: timestamps.append(self.weather_context.get('available_at'))
        if self.conditions_context:
            timestamps.append(self.conditions_context.get('available_at'))
            if self.conditions_context.get('forecast'): timestamps.append(self.conditions_context['forecast'].get('available_at'))
        for value in timestamps:
            if not value: raise ValueError('Observed evidence needs an availability timestamp')
            observed=datetime.fromisoformat(value.replace('Z','+00:00'))
            if observed.tzinfo is None or observed>self.cutoff: raise ValueError('Evidence was unavailable at prediction cutoff')
        if not self.drivers or len({d.driver_id for d in self.drivers}) != len(self.drivers):
            raise ValueError("A forecast needs unique entered drivers")
        for baseline in self.baselines or []:
            at=datetime.fromisoformat(baseline['available_at'].replace('Z','+00:00'))
            if at.tzinfo is None or at>self.cutoff: raise ValueError('Baseline was unavailable at cutoff')
            rows=baseline['drivers']; ids=[r['driver_id'] for r in rows]
            if len(set(ids))!=len(ids) or set(ids)!={d.driver_id for d in self.drivers}: raise ValueError('Baseline field mismatch')
            for field,total in [('probability',1),('podium_probability',3),('top10_probability',10)]:
                values=[r[field] for r in rows]
                if any(not math.isfinite(v) or not 0<=v<=1 for v in values) or not math.isclose(sum(values),total,abs_tol=1e-8): raise ValueError('Invalid baseline probabilities')
            if not all(r['probability']<=r['podium_probability']+1e-9<=r['top10_probability']+2e-9 for r in rows): raise ValueError('Baseline marginals must nest')
        if not math.isclose(sum(d.probability for d in self.drivers), 1, abs_tol=1e-8):
            raise ValueError("Race probabilities must sum to one")
        values = [d.podium_probability is not None or d.top10_probability is not None for d in self.drivers]
        if any(values):
            if not all(d.podium_probability is not None and d.top10_probability is not None for d in self.drivers):
                raise ValueError('Outcome probabilities require the complete field and both targets')
            if not all(d.probability <= d.podium_probability + 1e-9 <= d.top10_probability + 2e-9 for d in self.drivers):
                raise ValueError('Winner / podium / top ten probabilities must nest')
            for field, places in [('podium_probability',3),('top10_probability',10)]:
                if not math.isclose(sum(getattr(d,field) for d in self.drivers),places,abs_tol=1e-8):
                    raise ValueError('Outcome marginals must sum to the number of finishing places')
        return self
