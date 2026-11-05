'use client';

import Image from 'next/image';
import Link from 'next/link';
import {ArrowDown, ArrowUpRight} from 'lucide-react';
import {useRef, type PointerEvent} from 'react';
import type {Race} from '@/lib/types';

export function RacingHero({race}:{race:Race|null}) {
  const hero=useRef<HTMLElement>(null);
  function move(event:PointerEvent<HTMLElement>) {
    if(event.pointerType!=='mouse'||window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    const rect=event.currentTarget.getBoundingClientRect();
    hero.current?.style.setProperty('--hero-x',`${((event.clientX-rect.left)/rect.width-.5)*10}px`);
    hero.current?.style.setProperty('--hero-y',`${((event.clientY-rect.top)/rect.height-.5)*7}px`);
  }
  function reset(){hero.current?.style.setProperty('--hero-x','0px');hero.current?.style.setProperty('--hero-y','0px');}
  return <section ref={hero} className="racing-hero" aria-label="FASTLANE race intelligence" onPointerMove={move} onPointerLeave={reset}>
    <div className="racing-hero-image"><Image src="/images/hero-car.webp" alt="Red open-wheel racing car on a dark, rain-soaked studio floor" fill priority sizes="100vw" quality={85}/></div>
    <div className="hero-grain" aria-hidden="true"/>
    <div className="racing-hero-content">
      <span className="hero-kicker"><span className="hero-kicker-line"/>THE ART OF READING THE RACE</span>
      <h1><span className="hero-title-line">PREDICT THE</span><br/><span className="hero-title-line hero-title-red">UNPREDICTABLE.</span></h1>
      <p>Instinct meets intelligence.<br/>A clearer picture before lights out.</p>
      <div className="hero-actions"><a className="button" href="#race-forecast">Explore predictions <ArrowUpRight size={18}/></a><Link className="hero-secondary" href="/performance">See our track record <ArrowUpRight size={15}/></Link></div>
    </div>
    <div className="hero-footline"><div className="hero-signal-list"><span>Practice pace</span><i/><span>Qualifying form</span><i/><span>Race conditions</span></div><a href="#race-forecast" className="hero-scroll">{race?`ROUND ${String(race.round).padStart(2,'0')} / ${race.country.toUpperCase()}`:'EXPLORE THE WEEKEND'}<ArrowDown size={14}/></a></div>
  </section>;
}
