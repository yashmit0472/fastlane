import type {Prediction} from './types';
export type OutcomeKey='probability'|'podium_probability'|'top10_probability';
export const stageOrder=['FP1','FP2','FP3','Q'];
export function previousStage(predictions:Prediction[],selected:Prediction){
  const index=stageOrder.indexOf(selected.stage||'Q');
  return predictions.filter(p=>stageOrder.indexOf(p.stage||'Q')<index&&new Date(p.cutoff)<=new Date(selected.cutoff)).sort((a,b)=>stageOrder.indexOf(a.stage||'Q')-stageOrder.indexOf(b.stage||'Q')||Date.parse(a.cutoff)-Date.parse(b.cutoff)).at(-1);
}
export function probabilityChanges(current:Prediction,previous:Prediction,key:OutcomeKey){
  const before=new Map(previous.drivers.map(d=>[d.driver_id,d]));
  return current.drivers.flatMap(d=>{const old=before.get(d.driver_id);return d[key]!=null&&old?.[key]!=null?[{driver_id:d.driver_id,name:d.name,delta:(d[key]!-old[key]!)*100,before:old[key]!,after:d[key]!}]:[];}).sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta));
}
