"""Separate the displayed race, future schedule and post-start ingestion window."""
from datetime import datetime,timedelta


def start(race):
    value=race.get('scheduled_at') or race['date']+'T'+race['time']
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None: raise ValueError('Race start needs a timezone')
    return result


def race_view(payload,now):
    value=dict(payload)
    if value.get('status')!='completed':
        value['status']='scheduled' if start(value)>now else 'awaiting_classification'
    value['sessions']=[{**s,'status':'elapsed' if s.get('status')=='scheduled' and datetime.fromisoformat(s['started_at'].replace('Z','+00:00'))<=now else s.get('status','scheduled')} for s in value.get('sessions',[])]
    return value


def focus_race(payloads,now):
    rows=[race_view(p,now) for p in payloads if p.get('is_demo') is False]
    pending=[p for p in rows if p['status']=='awaiting_classification' and timedelta(0)<=now-start(p)<=timedelta(hours=24)]
    if pending: return max(pending,key=start)
    upcoming=[p for p in rows if start(p)>now]
    if upcoming: return min(upcoming,key=start)
    completed=[p for p in rows if p['status']=='completed']
    return max(completed,key=start) if completed else None


def recent_unclassified(calendar,results,now):
    published={(str(r['season']),int(r['round'])) for r in results if r.get('Results')}
    return sorted([r for r in calendar if r.get('time') and (str(r['season']),int(r['round'])) not in published and timedelta(0)<=now-start(r)<=timedelta(days=7)],key=start,reverse=True)


def refresh_targets(upcoming,pending,archives,archive_limit):
    """A started race with delayed results must not fall out of the worker queue."""
    result=[]; seen=set()
    for raw in upcoming[:1]+pending+list(reversed(archives))[:archive_limit]:
        key=(str(raw['season']),int(raw['round']))
        if key not in seen: result.append(raw); seen.add(key)
    return result
