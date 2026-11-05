import type {RefreshStatus} from '@/lib/types';
import {timestamp} from '@/lib/api';
export function LiveStatus({status}:{status:RefreshStatus|null}){
  const good=status?.status==='ok';
  const label=good?'Post-session updates':status?.status==='partial'?'Some session data pending':status?.status==='stale'?'Updates delayed':status?.status==='refreshing'?'Checking sources':'Awaiting source update';
  return <div className="source-status"><details><summary><span className={good?'source-dot good':'source-dot'}/>{label}</summary><p>{status?.last_successful_refresh?`Last completed check: ${timestamp(status.last_successful_refresh)}. `:''}{status?.last_attempt?`Last attempt: ${timestamp(status.last_attempt)}. `:''}{status?.status!=='stale'&&status?.next_check_at?`Next check: ${timestamp(status.next_check_at)}. `:''}{status?.notice||'Free post-session sources are checked every 5 minutes. Open pages refresh every minute. In-session streaming is not configured.'}</p></details></div>;
}
