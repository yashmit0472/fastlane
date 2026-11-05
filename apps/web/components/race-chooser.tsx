'use client';
import {useRouter} from 'next/navigation';
import type {Race} from '@/lib/types';
export function RaceChooser({races,current,view='races'}:{races:Race[];current:string;view?:'races'|'weekend'}){
  const router=useRouter();
  return <label className="control-label race-chooser">Race weekend<select value={current} onChange={e=>router.push(`/${view}/${e.target.value}`)}>{races.map(r=><option value={r.race_id} key={r.race_id}>{r.season} · R{r.round} · {r.name}{r.status==='completed'?' · Results':r.status==='awaiting_classification'?' · Results pending':''}</option>)}</select></label>;
}
