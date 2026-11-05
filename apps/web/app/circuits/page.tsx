import {redirect} from 'next/navigation';
import {api} from '@/lib/api';
import {PageHeading,Empty} from '@/components/ui';
export default async function CircuitIndex(){const r=await api.current();if(r.data)redirect(`/circuits/${r.data.circuit_id}`);return <div className="page-shell"><PageHeading eyebrow="CIRCUITS" title="The track changes everything." description="Explore circuit conversion rates after importing historical results."/><Empty message={r.error||undefined}/></div>;}
