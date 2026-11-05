import {api} from '@/lib/api';
import {PageHeading,Empty} from '@/components/ui';
import {RaceNav} from '@/components/race-nav';
import {ForecastHistory} from '@/components/forecast-history';
import {LiveStatus} from '@/components/live-status';
import {RaceResults} from '@/components/race-results';
import {RaceReportCard} from '@/components/report-card';
import {RaceChooser} from '@/components/race-chooser';
export const metadata={title:'Race forecast'};
export default async function RacePage({params}:{params:Promise<{raceId:string}>}){
  const {raceId}=await params;
  const [race,history,evaluation,status,card,calendar]=await Promise.all([api.race(raceId),api.history(raceId),api.evaluation(raceId),api.status(),api.reportCard(raceId),api.races()]);
  if(!race.data)return <div className="page-shell"><PageHeading eyebrow="FORECAST" title="Race unavailable." description="A verified race schedule is required for this view."/><Empty message={race.error||undefined}/></div>;
  const completed=race.data.status==='completed';
  const started=race.data.status!=='scheduled';
  return <div className="page-shell"><PageHeading eyebrow={`${race.data.season} / ROUND ${race.data.round}`} title={race.data.name} description={`${race.data.circuit} · ${completed?'Published results and archived weekend data.':started?'Race start has passed; awaiting published classification.':'Session-by-session forecasts from published real data.'}`}/><div className="race-toolbar">{calendar.data&&<RaceChooser races={calendar.data.races} current={raceId}/>}<LiveStatus status={status.data}/></div><RaceNav race={race.data} active="forecast"/><RaceResults evaluation={evaluation.data}/>{started&&!history.data?.predictions.length?<p className="forecast-method">No forecast was recorded before this race started. Published session data can still be imported, but pre-race predictions cannot be reconstructed afterward or scored as original saved picks.</p>:<ForecastHistory predictions={history.data?.predictions||[]} evaluation={evaluation.data} scheduledStages={race.data.sessions?.map(s=>s.type)}/>}<RaceReportCard card={card.data}/></div>;
}
