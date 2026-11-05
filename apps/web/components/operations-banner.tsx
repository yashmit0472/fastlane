import {api} from '@/lib/api';
export async function OperationsBanner(){
  const result=await api.operations();
  if(result.data?.ready)return null;
  return <div className="operations-banner" role="status"><strong>{result.error?'Data service temporarily unavailable.':'Automatic updates are delayed.'}</strong> Last saved forecasts remain available where possible. Source checks and page refreshes retry automatically.</div>;
}
