"""Read-only smoke checks for the running completed-race archive."""
import httpx

api='http://127.0.0.1:8000'
web='http://127.0.0.1:3010'
with httpx.Client(timeout=30) as client:
    response=client.get(api+'/api/races'); response.raise_for_status()
    completed=[r for r in response.json()['races'] if r['status']=='completed']
    assert completed, 'No completed races served'
    practice=0; pending=[]
    for race in completed:
        key=race['race_id']
        response=client.get(f'{api}/api/races/{key}/evaluation'); response.raise_for_status()
        evaluation=response.json()
        assert evaluation['winner'] and evaluation['results'], key
        response=client.get(f'{api}/api/races/{key}/weekend'); response.raise_for_status()
        weekend=response.json()
        assert weekend['is_demo'] is False
        assert any(s['type']=='Q1' and s['drivers'] for s in weekend['sessions']), key
        for session in weekend['sessions']:
            if session['type'] in {'FP1','FP2','FP3'}:
                if session['drivers']: practice+=1
                else: pending.append(f"{key} {session['type']}")
    for key in [completed[0]['race_id'],completed[-1]['race_id']]:
        for path in [f'/races/{key}',f'/weekend/{key}']:
            response=client.get(web+path); response.raise_for_status()
            assert 'Race results' in response.text, path
            assert 'Awaiting eligible data' not in response.text if path.startswith('/races/') else True
    print(f"PASS: {len(completed)} completed races have classifications and qualifying; {practice} practice sessions imported.")
    print(f"Practice sessions pending: {len(pending)}" + (': '+', '.join(pending) if pending else ''))
