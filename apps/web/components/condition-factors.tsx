import Link from 'next/link';
import type {Prediction} from '@/lib/types';
import {timestamp} from '@/lib/api';

export function ConditionFactors({prediction}:{prediction:Prediction}){
  const c=prediction.conditions_context;
  if(!c)return null;
  const w=c.forecast;
  return <section className="context-card condition-factors"><div className="panel-heading"><div><span className="eyebrow">Weather &amp; race conditions</span><h2>{c.used_by_model?'Weather is included in this forecast':'Weather candidate under evaluation'}</h2></div><span className="tag">{c.used_by_model?'Model input':'Context only'}</span></div>
    <p>{c.reason} <Link className="plain-link" href="/performance#weather-models">View validation →</Link></p>
    {w&&<><strong>{w.temperature_c.toFixed(1)}°C · {w.precipitation_mm.toFixed(2)} mm forecast precipitation · {w.wind_kmh.toFixed(1)} km/h wind</strong><p>Humidity {w.humidity_pct.toFixed(0)}% · JMA GSM · fixed 72-hour lead · valid {timestamp(w.valid_for)}</p><p className="subtle-note">Retrieved {timestamp(w.retrieved_at)}. This older fixed-lead forecast matches the training data; the separate race-hour weather card shows the latest context.</p></>}
    <details className="quiet-details"><summary>How these factors are used</summary><p>{c.notice}</p><p>Weather interactions, earlier driver/team nonfinish rates and earlier circuit nonfinish history are trained together. Unknown result statuses are excluded; lapped finishers count as finishers. Missing source data retains the existing model. Historical forecast release times are conservatively estimated; live retrieval is timestamped.</p></details>
  </section>;
}
