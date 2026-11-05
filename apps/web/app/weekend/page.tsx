import {redirect} from 'next/navigation';
import {api} from '@/lib/api';
import {PageHeading,Empty} from '@/components/ui';
export default async function WeekendIndex(){const r=await api.current();if(r.data)redirect(`/weekend/${r.data.race_id}`);return <div className="page-shell"><PageHeading eyebrow="WEEKEND PACE" title="Follow the sessions." description="Practice and qualifying data will appear after ingestion."/><Empty message={r.error||undefined}/></div>;}
