'use client';
import {useState} from 'react';
import type {Driver,Prediction,ModelAssociation} from '@/lib/types';
import {lapTime,timestamp} from '@/lib/api';
import {previousStage,probabilityChanges,stageOrder,type OutcomeKey} from '@/lib/forecast-changes';
const targets=[{key:'probability' as OutcomeKey,label:'Winner',target:'winner'},{key:'podium_probability' as OutcomeKey,label:'Podium',target:'podium'},{key:'top10_probability' as OutcomeKey,label:'Top 10',target:'top10'}];
const seconds=(value:number|null|undefined)=>value==null?'Unavailable':`${value>=0?'+':''}${value.toFixed(3)}s`;
const pct=(value:number|null|undefined)=>value==null?'—':`${(value*100).toFixed(1)}%`;

export function SessionChanges({selected,predictions}:{selected:Prediction;predictions:Prediction[]}){
  const [metric,setMetric]=useState<OutcomeKey>('probability');
  const previous=previousStage(predictions,selected);
  const changes=previous?probabilityChanges(selected,previous,metric):[];
  const [focus,setFocus]=useState(selected.drivers[0]?.driver_id||'');
  const points=stageOrder.flatMap((stage,i)=>{const p=predictions.filter(p=>(p.stage||'Q')===stage&&Date.parse(p.cutoff)<=Date.parse(selected.cutoff)).at(-1);const d=p?.drivers.find(d=>d.driver_id===focus);return d?.[metric]!=null?[{stage,x:45+i*125,y:130-d[metric]!*100,value:d[metric]!}]:[];});
  return <section className="insight-panel"><div className="panel-heading"><h2>What changed</h2><div className="segmented">{targets.map(t=><button key={t.key} aria-pressed={metric===t.key} onClick={()=>setMetric(t.key)}>{t.label}</button>)}</div></div>
    {previous?<><p className="insight-copy">After {previous.stage||'Q'} → after {selected.stage||'Q'} · percentage-point changes for drivers present in both snapshots.</p>{changes.length?<div className="change-grid">{changes.slice(0,3).map(d=><div key={d.driver_id}><span>{d.name}</span><strong className={d.delta>=0?'delta-up':'delta-down'}>{d.delta>=0?'+':''}{d.delta.toFixed(1)} pp</strong><small>{pct(d.before)} → {pct(d.after)}</small></div>)}</div>:<p className="insight-copy">This outcome was not recorded in both snapshots.</p>}<p className="subtle-note insight-copy">{previous.model_version!==selected.model_version?'The stage models differ; this change reflects both new data and a different model.':'The same model is used for both snapshots.'} Missing or newly entered drivers receive no invented previous probability.</p></>:<p className="insight-copy">This is the first recorded stage. Changes appear when a later stage has a saved forecast.</p>}
    <details className="quiet-details insight-copy"><summary>Track a driver across sessions</summary><label className="control-label">Driver <select value={focus} onChange={e=>setFocus(e.target.value)}>{selected.drivers.map(d=><option key={d.driver_id} value={d.driver_id}>{d.name}</option>)}</select></label><svg className="journey-chart" viewBox="0 0 470 170" role="img" aria-label="Selected driver's recorded probabilities by stage"><line x1="35" y1="130" x2="445" y2="130" stroke="var(--line)"/>{[0,50,100].map(v=><g key={v}><text x="2" y={134-v} fill="var(--muted)" fontSize="10">{v}%</text><line x1="35" x2="445" y1={130-v} y2={130-v} stroke="var(--line)"/></g>)}<polyline points={points.map(p=>`${p.x},${p.y}`).join(' ')} fill="none" stroke="var(--red)" strokeWidth="2"/>{points.map(p=><g key={p.stage}><circle cx={p.x} cy={p.y} r="4" fill="var(--red)"/><text x={p.x} y={p.y-10} textAnchor="middle" fill="var(--text)" fontSize="11">{pct(p.value)}</text><text x={p.x} y="155" textAnchor="middle" fill="var(--muted)" fontSize="11">{p.stage}</text></g>)}</svg><p className="subtle-note">Only saved snapshots are plotted. Values between points are not forecasts.</p></details>
  </section>;
}

function Associations({value}:{value:ModelAssociation|undefined}){
  if(!value)return <p className="subtle-note">Model associations were not saved for this snapshot.</p>;
  return <><span className="eyebrow">{value.method}</span>{value.signals.map(s=><div className="association" key={s.label}><span>{s.label}</span><strong className={s.contribution>=0?'delta-up':'delta-down'}>{s.contribution>=0?'+':''}{s.contribution.toFixed(2)}</strong></div>)}<p className="subtle-note">Raw-score associations before calibration and race constraints. Positive terms raise the raw score; they are not percentage-point changes or causal effects.</p></>;
}

export function DriverCompare({prediction}:{prediction:Prediction}){
  const [left,setLeft]=useState(prediction.drivers[0]?.driver_id||''); const [right,setRight]=useState(prediction.drivers[1]?.driver_id||'');
  const [target,setTarget]=useState('winner');
  const a=prediction.drivers.find(d=>d.driver_id===left)||prediction.drivers[0]; const b=prediction.drivers.find(d=>d.driver_id===right)||prediction.drivers[1];
  if(!a||!b)return null;
  const observation=(d:Driver)=>d.observations;
  const rows=[{name:'Win probability',value:(d:Driver)=>pct(d.probability)},{name:'Podium probability',value:(d:Driver)=>pct(d.podium_probability)},{name:'Top-10 probability',value:(d:Driver)=>pct(d.top10_probability)},
    {name:'Recent average finish',value:(d:Driver)=>observation(d)?.recent_average_finish?.toFixed(1)??'Unavailable'},
    {name:'Recent finishes',value:(d:Driver)=>observation(d)?.recent_results.map(r=>`P${r.position}`).join(' · ')||'Unavailable'},
    {name:'Qualifying gap (same phase)',value:(d:Driver)=>{const q=observation(d)?.qualifying;return q?.phase?`${q.phase} ${seconds(q.gap_s)}`:'Unavailable';}},
    {name:'Teammate qualifying gap',value:(d:Driver)=>{const q=observation(d)?.qualifying;return q?.teammate_phase?`${q.teammate_phase} ${seconds(q.teammate_gap_s)}`:'Unavailable';}},
    {name:'Practice best / median',value:(d:Driver)=>{const p=observation(d)?.practice;return p?`${p.best_lap_ms!=null?lapTime(p.best_lap_ms):'—'} / ${p.median_lap_ms!=null?lapTime(p.median_lap_ms):'—'}`:'Unavailable';}},
    {name:'Filtered practice laps',value:(d:Driver)=>{const p=observation(d)?.practice;return p?`${p.filtered_laps??'—'}${p.small_sample?' · small sample':''}`:'Unavailable';}},
    {name:'Earlier nonfinish rate (smoothed)',value:(d:Driver)=>{const c=observation(d)?.race_conditions;return c?`${pct(c.driver_nonfinish_rate)} · ${c.driver_status_samples} starts`:'Unavailable';}},
    {name:'Earlier team nonfinish rate',value:(d:Driver)=>pct(observation(d)?.race_conditions?.team_nonfinish_rate)},
    {name:'Long run vs teammate',value:(d:Driver)=>{const p=observation(d)?.practice;return p?.teammate_long_run_gap_s!=null?`${seconds(p.teammate_long_run_gap_s)} · ${p.compound?.toLowerCase()}`:'No compound-matched sample';}}];
  return <section className="insight-panel"><div className="panel-heading"><div><span className="eyebrow">Observed evidence</span><h2>Compare drivers</h2></div></div><div className="compare-selectors">{[{label:'First driver',value:a.driver_id,set:setLeft},{label:'Second driver',value:b.driver_id,set:setRight}].map(c=><label className="control-label" key={c.label}>{c.label}<select value={c.value} onChange={e=>c.set(e.target.value)}>{prediction.drivers.map(d=><option value={d.driver_id} key={d.driver_id}>{d.name}</option>)}</select></label>)}</div><div className="table-scroll"><table className="data-table comparison-table"><thead><tr><th>Evidence / estimate</th><th>{a.name}</th><th>{b.name}</th></tr></thead><tbody>{rows.map(r=><tr key={r.name}><td>{r.name}</td><td>{r.value(a)}</td><td>{r.value(b)}</td></tr>)}</tbody></table></div>
    <p className="subtle-note insight-copy">Observations were frozen with this forecast. Recent finishes are oldest → newest. Teammate gaps are driver minus teammate; negative is faster. Nonfinish rates include accidents/exclusions and use a smoothed prior; they are not predicted mechanical-failure probabilities. Observed comparisons are separate from model-derived associations.</p>
    <details className="quiet-details insight-copy"><summary>Model-derived associations</summary><label className="control-label">Outcome <select value={target} onChange={e=>setTarget(e.target.value)}>{targets.map(t=><option key={t.target} value={t.target}>{t.label}</option>)}</select></label><div className="model-association-grid"><div><h3>{a.name}</h3><Associations value={a.model_associations?.[target]}/></div><div><h3>{b.name}</h3><Associations value={b.model_associations?.[target]}/></div></div></details>
  </section>;
}

export function ForecastContext({prediction}:{prediction:Prediction}){
  const q=prediction.input_quality,w=prediction.weather_context;
  return <div className="context-grid"><section className="context-card"><span className="eyebrow">Input quality at cutoff</span><strong>{prediction.field_status||q?.roster||'Roster status not recorded'}</strong>{q?.roster_source&&<a className="plain-link" href={q.roster_source} target="_blank" rel="noreferrer">Entry-list source ↗</a>}{q?.metadata_conflicts?.length?<details className="quiet-details"><summary>{q.metadata_conflicts.length} metadata discrepancy flagged</summary>{q.metadata_conflicts.map(c=><p key={c}>{c}</p>)}</details>:null}{q?.timing_coverage!=null&&<p>{(q.timing_coverage*100).toFixed(0)}% of entered drivers have timing · {q.missing_entered_drivers.length} missing</p>}{q?.extra_practice_participants.length? <p>{q.extra_practice_participants.length} additional practice participants are outside the forecast field.</p>:null}<p className="subtle-note">{q?.source_switch?'OpenF1 fallback inputs; see the source-shift audit on Performance.':'Missing or small samples remain explicit.'}</p></section><section className="context-card"><span className="eyebrow">Race-hour weather · context only</span>{w?<><strong>{w.temperature_c.toFixed(1)}°C · {w.rain_probability_pct.toFixed(0)}% rain probability</strong><p>Wind {w.wind_kmh.toFixed(1)} km/h · Valid {timestamp(w.valid_for)}</p><p className="subtle-note">Captured {timestamp(w.available_at)} · {w.source}. Weather is not a model input.</p></>:<><strong>No weather forecast saved at this cutoff</strong><p className="subtle-note">Later observations are not substituted into an earlier forecast.</p></>}</section></div>;
}
