'use client';
import Link from 'next/link';
import {useState} from 'react';
import type {Race} from '@/lib/types';
export function RaceList({races}:{races:Race[]}){
  const [search,setSearch]=useState(''),[status,setStatus]=useState('all');
  const visible=races.filter(r=>(`${r.name} ${r.circuit} ${r.country} ${r.season}`).toLowerCase().includes(search.toLowerCase())&&(status==='all'||r.status===status));
  const groups=[{title:'Race start passed · results pending',status:'awaiting_classification',badge:'Results pending'},{title:'Upcoming weekends',status:'scheduled',badge:'Upcoming'},{title:'Completed races',status:'completed',badge:'Results'}];
  return <><div className="race-filters"><label className="control-label">Find a race<input type="search" placeholder="Race, country or circuit" value={search} onChange={e=>setSearch(e.target.value)}/></label><label className="control-label">Show<select value={status} onChange={e=>setStatus(e.target.value)}><option value="all">All races</option><option value="scheduled">Upcoming</option><option value="awaiting_classification">Results pending</option><option value="completed">Completed</option></select></label></div>{groups.map(g=>{const rows=visible.filter(r=>r.status===g.status);return rows.length>0&&<section key={g.status}><h2>{g.title}</h2><div className="race-list">{rows.map(r=><Link className="race-list-card" href={`/races/${r.race_id}`} key={r.race_id}><span className="mono">{r.season} / ROUND {r.round}</span><span className="tag">{g.badge}</span><h2>{r.name}</h2><p>{r.circuit}</p><p>{new Date(r.scheduled_at).toISOString().slice(0,10)}</p><span className="text-link">{g.status==='completed'?'Results & report card':g.status==='awaiting_classification'?'Session archive & race status':'Forecasts & comparisons'} →</span></Link>)}</div></section>;})}{!visible.length&&<p>No races match this filter.</p>}</>;
}
