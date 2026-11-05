import type {Race, Prediction, Weekend, Circuit, Form, Metrics, RefreshStatus, Evaluation, PracticeMetrics,OutcomeReports,ReportCard,Performance,ValidationReport,SourceValidation,WeatherContext,ConditionsReport} from './types';
const base = process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || 'http://127.0.0.1:8000';
export type Result<T> = {data: T | null; error: string | null};
async function request<T>(path: string,timeoutMs=5000): Promise<Result<T>> {
  try {
    const res = await fetch(`${base}${path}`, {cache: 'no-store', signal: AbortSignal.timeout(timeoutMs)});
    if (!res.ok) return {data: null, error: res.status === 404 ? 'Data is not available yet.' : 'The data service is temporarily unavailable.'};
    return {data: await res.json() as T, error: null};
  } catch {return {data: null, error: 'Could not connect to the data service. Check that the API is running.'};}
}
export const api = {
  current: () => request<Race>('/api/races/current'),
  next: () => request<Race>('/api/races/next'),
  races: () => request<{races: Race[]}>('/api/races'),
  race: (id: string) => request<Race>(`/api/races/${encodeURIComponent(id)}`),
  prediction: (id: string) => request<Prediction>(`/api/races/${encodeURIComponent(id)}/prediction`),
  weekend: (id: string) => request<Weekend>(`/api/races/${encodeURIComponent(id)}/weekend`),
  circuit: (id: string) => request<Circuit>(`/api/circuits/${encodeURIComponent(id)}/history`),
  form: (id: string) => request<Form>(`/api/drivers/${encodeURIComponent(id)}/form`),
  metrics: () => request<Metrics>('/api/model/metrics'),
  practiceMetrics: () => request<{status:string;stages:Record<string,PracticeMetrics>}>('/api/model/practice'),
  outcomeMetrics: () => request<OutcomeReports>('/api/model/outcomes'),
  reportCard:(id:string)=>request<ReportCard>(`/api/races/${encodeURIComponent(id)}/report-card`),
  performance:()=>request<Performance>('/api/performance'),
  validation:()=>request<ValidationReport>('/api/model/validation'),
  sourceValidation:()=>request<SourceValidation>('/api/model/source-validation'),
  weather:(id:string)=>request<WeatherContext>(`/api/races/${encodeURIComponent(id)}/weather`),
  conditions:()=>request<ConditionsReport>('/api/model/conditions'),
  operations:()=>request<{ready:boolean;status:string;blockers:string[];warnings:string[]}>('/api/system/operations',15000),
  status: () => request<RefreshStatus>('/api/system/status'),
  history: (id:string) => request<{race_id:string;predictions:Prediction[]}>(`/api/races/${encodeURIComponent(id)}/predictions`),
  evaluation: (id:string) => request<Evaluation>(`/api/races/${encodeURIComponent(id)}/evaluation`),
};
export function lapTime(ms: number | null) {if (ms == null) return 'Unavailable'; return `${Math.floor(ms / 60000)}:${((ms % 60000) / 1000).toFixed(3).padStart(6, '0')}`;}
export function timestamp(s: string) {return new Intl.DateTimeFormat('en-GB', {day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'}).format(new Date(s)) + ' UTC';}
// Largest remainder rounding preserves exactly 100.0% at displayed precision.
export function displayedProbabilities(drivers: {probability: number}[]) {
  const raw = drivers.map(d => d.probability * 1000);
  const units = raw.map(Math.floor);
  const remaining = 1000 - units.reduce((a,b) => a + b, 0);
  const order = raw.map((n,i) => ({i, fraction: n - units[i]})).sort((a,b) => b.fraction - a.fraction);
  for (let n = 0; n < remaining; n++) units[order[n % order.length].i]++;
  return units.map(n => (n / 10).toFixed(1));
}
