import Link from 'next/link';
import type {Race} from '@/lib/types';
export function RaceNav({race,active}:{race:Race;active:string}) {return <nav className="page-subnav" aria-label="Race views"><Link className={active==='forecast'?'active':''} href={`/races/${race.race_id}`}>Race forecast</Link><Link className={active==='weekend'?'active':''} href={`/weekend/${race.race_id}`}>Weekend sessions</Link><Link href={`/circuits/${race.circuit_id}`}>Circuit intelligence</Link><Link href="/predictions">All races ↗</Link></nav>;}
