import Link from 'next/link';
import {ArrowRight, Clock3} from 'lucide-react';
import {api, timestamp} from '@/lib/api';
import {Empty, Provenance, TextLink} from '@/components/ui';
import {ForecastTable} from '@/components/forecast';
import {SessionTabs} from '@/components/session-tabs';
import {LiveStatus} from '@/components/live-status';
import {RacingHero} from '@/components/racing-hero';
import {WeekendSpotlight} from '@/components/weekend-spotlight';

export default async function Home() {
  const [next,status,calendar]=await Promise.all([api.current(),api.status(),api.races()]);
  const race=next.data;
  const started=!!race&&race.status!=='scheduled';
  const [pred,weekend]=race?await Promise.all([api.prediction(race.race_id),api.weekend(race.race_id)]):[];
  const previous=calendar.data?.races.find(r=>r.status==='completed');
  const result=previous?await api.evaluation(previous.race_id):null;
  return <><RacingHero race={race}/><div id="race-forecast" className="dashboard page-shell">
    <div className="dashboard-heading"><div><span className="eyebrow">Race forecast</span><h2 className="dashboard-title">The weekend, in focus.</h2><p>Winner, podium and top-10 probabilities as each session adds to the picture.</p></div><LiveStatus status={status.data}/></div>
    {race?<>
      <WeekendSpotlight key={race.race_id} race={race}/>
      <div className="dashboard-columns"><section className="panel forecast-panel"><div className="panel-heading"><div><span className="eyebrow">Probabilities</span><h2>Who’s in contention</h2></div><span className="tag">{pred?.data?`After ${pred.data.stage==='Q'?'qualifying':pred.data.stage||'qualifying'}`:'Awaiting session data'}</span></div>
        {pred?.data?<><ForecastTable prediction={pred.data} compact/><Provenance demo={pred.data.is_demo} cutoff={pred.data.cutoff} version={pred.data.model_version}/><details className="quiet-details"><summary>How this forecast was made</summary><p>{pred.data.method}</p><p>{pred.data.notice}</p></details></>:<div className="forecast-wait"><div className="waiting-icon"><Clock3 size={23}/></div><h3>{started?'No pre-race forecast was recorded':'The first forecast is on its way'}</h3><p>{started?'FASTLANE did not save a forecast before this race started. Published session timing can still be imported; a prediction made afterward would not be a pre-race forecast.':'Probabilities appear after a completed session has published enough usable timing data.'}</p><div className="waiting-stages">{(race.sessions||[]).filter(s=>['FP1','FP2','FP3','Q'].includes(s.type)).map(s=><div key={s.type}><strong>{s.type==='Q'?'Qualifying':s.type}</strong><span>{timestamp(s.started_at)}</span></div>)}</div><TextLink href={`/weekend/${race.race_id}`}>{started?'View archived session data':'Check session data'}</TextLink><p className="subtle-note">{started?'Results and archives update when sources publish them. No forecasts are backdated.':'The page updates automatically. Source publication delays can postpone a forecast.'}</p></div>}
      </section><aside className="dashboard-aside"><section className="panel"><div className="panel-heading"><h2>Reading the forecast</h2></div><dl className="outcome-guide"><div><dt>Winner</dt><dd>Chance of finishing P1.</dd></div><div><dt>Podium</dt><dd>Chance of finishing in the top 3.</dd></div><div><dt>Top 10</dt><dd>Chance of a top-10 classified finish.</dd></div></dl><p className="subtle-note">Each column describes a different outcome. A driver’s podium chance includes their chance of winning.</p><Link className="plain-link" href="/methodology">View model evaluation <ArrowRight size={14}/></Link></section>
        {previous&&<section className="panel previous-race"><span className="eyebrow">Last completed race</span><h2>{previous.name}</h2>{result?.data?.winner?<><span className="subtle-note">Race winner</span><strong className="result-winner">{result.data.winner.name}</strong></>:<p className="subtle-note">Published results and session data</p>}<TextLink href={`/races/${previous.race_id}`}>Results &amp; forecasts</TextLink></section>}
        <p className="dashboard-disclaimer">Experimental models. Practice results and qualifying help inform a forecast; strategy, reliability and race incidents remain uncertain.</p>
      </aside></div>
      <section className="panel weekend-panel"><div className="panel-heading"><div><span className="eyebrow">Supporting data</span><h2>Session pace</h2></div><TextLink href={`/weekend/${race.race_id}`}>Full weekend</TextLink></div>{weekend?.data?<SessionTabs weekend={weekend.data} compact/>:<Empty message={weekend?.error||'Session timing is not available yet.'}/>}</section>
    </>:<Empty message={next.error||undefined}/>}
    <div className="dashboard-bottom"><span>Session pace · Recent driver &amp; team form · Circuit history</span><Link href="/predictions">Browse all races <ArrowRight size={14}/></Link></div>
  </div></>;
}
