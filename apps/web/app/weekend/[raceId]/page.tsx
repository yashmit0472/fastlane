import {api} from '@/lib/api';
import {PageHeading,Provenance,Empty} from '@/components/ui';
import {RaceNav} from '@/components/race-nav';
import {SessionTabs} from '@/components/session-tabs';
import {RaceResults} from '@/components/race-results';
export const metadata={title:'Weekend pace'};
export default async function WeekendPage({params}:{params:Promise<{raceId:string}>}) {
  const {raceId}=await params;
  const [race,weekend,evaluation]=await Promise.all([api.race(raceId),api.weekend(raceId),api.evaluation(raceId)]);
  return <div className="page-shell"><PageHeading eyebrow="WEEKEND PACE" title={race.data?`${race.data.name.replace(' Grand Prix','')} / session by session.`:'Weekend unavailable.'} description="Compare the best valid laps and representative clean-lap pace. Missing sessions and eliminated drivers stay explicit."/>{race.data&&<RaceNav race={race.data} active="weekend"/>}{weekend.data?<><Provenance demo={weekend.data.is_demo} cutoff={weekend.data.cutoff}/><SessionTabs weekend={weekend.data}/></>:<Empty message={weekend.error||undefined}/>}<RaceResults evaluation={evaluation.data}/></div>;
}
