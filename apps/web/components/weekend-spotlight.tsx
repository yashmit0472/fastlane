'use client';

import Link from 'next/link';
import {useId, useState, type PointerEvent} from 'react';
import {ArrowUpRight, CalendarDays, ChevronRight, MapPin, Pause, Play} from 'lucide-react';
import type {Race} from '@/lib/types';

const labels:Record<string,string>={FP1:'First practice',FP2:'Second practice',FP3:'Final practice',Q:'Qualifying'};
const line='M86 179 L289 76 Q302 69 312 77 L338 96 Q344 101 338 109 L317 128 Q310 134 317 140 L345 157 Q354 163 366 155 L394 137 Q405 131 414 139 L427 151 Q436 161 422 170 L383 196 Q375 201 362 198 L328 191 Q317 188 311 195 L293 216 Q288 222 276 217 L250 205 Q241 202 233 209 L213 228 Q205 234 196 227 L177 208 Q172 202 164 206 L145 216 Q137 222 127 216 L86 191 Q78 186 86 179 Z';

function CircuitSculpture({stage,paused}:{stage:string;paused:boolean}) {
  const id=useId().replace(/:/g,'');
  return <div className={paused?'circuit-sculpture is-paused':'circuit-sculpture'} aria-hidden="true"><div className="sculpture-halo"/><svg viewBox="0 0 500 310" fill="none">
    <defs><linearGradient id={`${id}-base`} x1="100" y1="100" x2="400" y2="250" gradientUnits="userSpaceOnUse"><stop stopColor="#252932"/><stop offset="1" stopColor="#101217"/></linearGradient><linearGradient id={`${id}-edge`} x1="80" y1="70" x2="430" y2="230" gradientUnits="userSpaceOnUse"><stop stopColor="#707784"/><stop offset=".48" stopColor="#282e37"/><stop offset="1" stopColor="#535b69"/></linearGradient><linearGradient id={`${id}-red`}><stop stopColor="#ff5d63"/><stop offset="1" stopColor="#9b252d"/></linearGradient><filter id={`${id}-glow`} x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="4"/></filter></defs>
    <ellipse cx="253" cy="252" rx="175" ry="26" fill="#000" opacity=".55"/>
    <path d="M45 175L289 47L467 156L224 291Z" fill="#080a0d" stroke="#272b34"/>
    <path d="M45 165L289 37L467 146L224 281Z" fill={`url(#${id}-base)`} stroke="#333943"/>
    <g stroke="#626977" strokeWidth=".5" opacity=".15">{[0,1,2,3,4,5,6].map(i=><g key={i}><path d={`M${68+i*30} ${153+i*18}l236 -123`}/><path d={`M${76+i*31} ${149-i*16}l171 104`}/></g>)}</g>
    {[17,13,9,5].map((depth,i)=><path key={depth} d={line} transform={`translate(0 ${depth})`} stroke={['#080a0e','#171b22','#252a34','#434a57'][i]} strokeWidth="25" strokeLinejoin="round"/>)}
    <path d={line} stroke={`url(#${id}-edge)`} strokeWidth="25" strokeLinejoin="round"/>
    <path d={line} stroke="#9c343e" strokeWidth="23" strokeDasharray="3 8" opacity=".8"/>
    <path d={line} stroke="#171b22" strokeWidth="17" strokeLinejoin="round"/>
    <path d={line} stroke="#59616e" strokeWidth=".7" strokeDasharray="3 5" opacity=".65"/>
    <path d={line} className="circuit-running-light circuit-running-glow" stroke="#fb424e" strokeWidth="7" filter={`url(#${id}-glow)`}/>
    <path d={line} className="circuit-running-light" stroke={`url(#${id}-red)`} strokeWidth="2.5" strokeLinecap="round"/>
    <path d="M120 153l11 18" stroke="#f5f5f5" strokeWidth="5" strokeDasharray="2 2"/>
    <circle cx="126" cy="161" r="4" fill="#ff5965"/><circle cx="126" cy="161" r="10" stroke="#ff5965" opacity=".3"/>
    <path d="M126 153V101l-22-13" stroke="#797f8a" strokeWidth=".7"/>
    <text x="52" y="82" fill="#afb4c0" fontFamily="monospace" fontSize="8" letterSpacing="1.5">{stage==='Q'?'ONE LAP. EVERY EDGE.':'EVERY SESSION COUNTS.'}</text>
  </svg><span className="sculpture-caption">Illustrative racing line</span></div>;
}

export function WeekendSpotlight({race}:{race:Race}) {
  const sessions=(race.sessions||[]).filter(s=>labels[s.type]);
  const [selected,setSelected]=useState(sessions[0]?.type||'FP1');
  const [paused,setPaused]=useState(false);
  const session=sessions.find(s=>s.type===selected);
  const date=new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',timeZone:'UTC'});
  const time=new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'UTC'});
  function tilt(event:PointerEvent<HTMLElement>) {
    if(event.pointerType!=='mouse'||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const rect=event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty('--scene-x',`${((event.clientX-rect.left)/rect.width-.5)*5}deg`);
    event.currentTarget.style.setProperty('--scene-y',`${((event.clientY-rect.top)/rect.height-.5)*-4}deg`);
  }
  function reset(event:PointerEvent<HTMLElement>){event.currentTarget.style.setProperty('--scene-x','0deg');event.currentTarget.style.setProperty('--scene-y','0deg');}
  return <section className="weekend-spotlight" aria-label="Race weekend" onPointerMove={tilt} onPointerLeave={reset}>
    <div className="spotlight-main"><div className="spotlight-copy"><div className="spotlight-kicker"><span className="tag spotlight-round">ROUND {String(race.round).padStart(2,'0')}</span><span>{race.status==='awaiting_classification'?'RACE START PASSED · RESULTS PENDING':`${race.season} WORLD CHAMPIONSHIP`}</span></div><h2>{race.name}</h2><p className="spotlight-location"><MapPin size={13}/>{race.circuit}</p><div className="spotlight-race-date"><CalendarDays size={14}/>{date.format(new Date(race.scheduled_at))}<span/>{time.format(new Date(race.scheduled_at))} UTC<Link href={`/races/${race.race_id}`} aria-label={`View ${race.name} details`}><ArrowUpRight size={18}/></Link></div></div><div className="spotlight-visual"><span className="spotlight-country">{race.country.toUpperCase()}</span><CircuitSculpture stage={selected} paused={paused}/><button className="scene-motion-toggle" type="button" aria-label={paused?'Play circuit animation':'Pause circuit animation'} title={paused?'Play animation':'Pause animation'} onClick={()=>setPaused(!paused)}>{paused?<Play size={12}/>:<Pause size={12}/>}</button></div></div>
    {sessions.length>0&&<div className="spotlight-schedule" aria-label="Weekend schedule">{sessions.map((s,i)=><button key={s.type} type="button" aria-pressed={selected===s.type} aria-label={`${s.type} schedule`} onClick={()=>setSelected(s.type)}><span className="schedule-index">0{i+1}</span><span><strong>{s.type==='Q'?'Qualifying':s.type}</strong><small>{date.format(new Date(s.started_at))}<span> · </span>{time.format(new Date(s.started_at))} UTC</small></span><ChevronRight size={14}/></button>)}</div>}
    {session&&<div className="spotlight-session-note" aria-live="polite"><span className="session-note-dot"/>{labels[selected]}<span className="session-note-divider">/</span>{session.status==='loaded'||session.status==='published'?'Published session data available':session.status==='elapsed'?'Session start has passed; check published timing':'Forecast updates follow published session data'}<Link href={`/weekend/${race.race_id}`}>Session details <ArrowUpRight size={12}/></Link></div>}
  </section>;
}
