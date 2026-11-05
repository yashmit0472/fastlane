import {api} from '@/lib/api';
import {PageHeading,Empty} from '@/components/ui';
import {RaceList} from '@/components/race-list';
export const metadata={title:'Race forecasts'};
export default async function Predictions(){const {data,error}=await api.races();return <div className="page-shell"><PageHeading eyebrow="RACES & FORECASTS" title="Read the race." description="Choose a weekend for predictions, driver comparisons and session changes. Completed races include classifications and report cards."/>{data?.races.length?<RaceList races={data.races}/>:<Empty message={error||'No weekends have been imported.'}/>}</div>;}
