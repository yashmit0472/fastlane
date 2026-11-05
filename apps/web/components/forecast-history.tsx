'use client';
import {useState} from 'react';
import type {Prediction,Evaluation} from '@/lib/types';
import {ForecastTable} from './forecast';
import {Provenance,Empty} from './ui';
import {timestamp} from '@/lib/api';
import {ConditionFactors} from './condition-factors';
import {SessionChanges,DriverCompare,ForecastContext} from './forecast-insights';
export function ForecastHistory({predictions,scheduledStages}:{predictions:Prediction[];evaluation?:Evaluation|null;scheduledStages?:string[]}){
  const [chosen,setChosen]=useState<string|null>(null);
  const selected=predictions.find(p=>p.cutoff===chosen)||predictions.at(-1);
  return <><div className="stage-timeline" aria-label="Saved forecast snapshots">{['FP1','FP2','FP3','Q'].map(stage=>{
    const last=predictions.filter(p=>(p.stage||'Q')===stage).at(-1);
    const scheduled=!scheduledStages||scheduledStages.includes(stage);
    return <button key={stage} disabled={!last} onClick={()=>last&&setChosen(last.cutoff)} aria-pressed={!!last&&selected?.cutoff===last.cutoff}><strong>{stage==='Q'?'After qualifying':`After ${stage}`}</strong><span>{last?'Forecast saved':scheduled?'Awaiting eligible data':'Not scheduled'}</span></button>;
  })}</div>{selected?<><ForecastContext prediction={selected}/><ConditionFactors prediction={selected}/><section className="panel"><div className="panel-heading"><h2>{selected.stage==='Q'?'After qualifying':`After ${selected.stage||'qualifying'}`}</h2><span className="tag">Experimental</span></div><ForecastTable prediction={selected}/><div className="forecast-disclosures"><Provenance demo={false} cutoff={selected.cutoff} version={selected.model_version}/><details className="quiet-details"><summary>Model, inputs &amp; limitations</summary><p>{selected.method||'Qualifying/history model'}</p><p>{selected.notice}</p><p>Field: {selected.field_status}</p>{selected.outcomes_model_version&&<p>Podium / top-10 model: {selected.outcomes_model_version}</p>}</details></div></section><SessionChanges selected={selected} predictions={predictions}/><DriverCompare prediction={selected}/></>:<Empty message="Forecasts appear after a completed session has published usable timing data."/>}
    {predictions.length>1&&<details className="snapshot-details"><summary>All saved snapshots ({predictions.length})</summary>{predictions.map(p=><button key={`${p.model_version}-${p.cutoff}`} onClick={()=>setChosen(p.cutoff)}>{p.stage||'Q'} · {timestamp(p.cutoff)}</button>)}</details>}</>;
}
