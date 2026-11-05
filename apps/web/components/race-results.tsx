import type {Evaluation} from '@/lib/types';
export function RaceResults({evaluation}:{evaluation:Evaluation|null}) {
  if (!evaluation?.results?.length) return null;
  return <section className="evaluation-panel"><h2>Race results<span className="red">.</span></h2><p>Published winner: <strong>{evaluation.winner?.name}</strong> · {evaluation.source}</p><div className="table-scroll"><table className="data-table"><thead><tr><th>Finish</th><th>Driver</th><th>Status</th></tr></thead><tbody>{evaluation.results.map(r=><tr key={r.driver_id}><td>P{r.position}</td><td>{r.name}</td><td>{r.status||'Published classification'}</td></tr>)}</tbody></table></div></section>;
}
