"""Check actual local services, waiting states, source provenance and demo rejection."""
import argparse
from datetime import datetime,timezone
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web",default="http://127.0.0.1:3010")
    parser.add_argument("--api",default="http://127.0.0.1:8000")
    args=parser.parse_args()
    with httpx.Client(timeout=60,follow_redirects=True) as client:
        def get(path):
            response=client.get(args.api+path);response.raise_for_status();return response.json()
        assert get('/health')['status']=='ok'
        state=get('/api/system/status')
        assert state['is_demo'] is False and state.get('last_successful_refresh')
        race=get('/api/races/next');assert race['is_demo'] is False
        assert datetime.fromisoformat(race['scheduled_at'].replace('Z','+00:00'))>datetime.now(timezone.utc)
        records=get('/api/races')['races'];assert records and all(r['is_demo'] is False for r in records)
        for path in ['/api/races/showcase-singapore','/api/races/showcase-singapore/prediction','/api/races/showcase-singapore/weekend']:
            assert client.get(args.api+path).status_code==404
        history=get(f"/api/races/{race['race_id']}/predictions")['predictions']
        for p in history:
            assert not p['is_demo'] and abs(sum(d['probability'] for d in p['drivers'])-1)<1e-8
            assert datetime.fromisoformat(p['cutoff'].replace('Z','+00:00'))<datetime.fromisoformat(race['scheduled_at'].replace('Z','+00:00'))
        completed=next((r for r in records if r['status']=='completed'),None)
        paths=['/','/predictions',f"/races/{race['race_id']}",f"/weekend/{race['race_id']}",f"/circuits/{race['circuit_id']}",'/methodology','/weekend','/circuits']
        if completed:
            evaluation=get(f"/api/races/{completed['race_id']}/evaluation")
            assert evaluation['winner'] and not evaluation['is_demo']
            paths.extend([f"/races/{completed['race_id']}",f"/weekend/{completed['race_id']}",f"/drivers/{evaluation['winner']['driver_id']}"])
        for path in paths:
            response=client.get(args.web+path);response.raise_for_status()
            assert 'FASTLANE' in response.text and 'ILLUSTRATIVE DEMO' not in response.text
            assert 'showcase-singapore' not in response.text
            print(f"PASS {path}: real data / explicit waiting state",flush=True)
        cors=client.options(args.api+'/api/races',headers={'Origin':args.web,'Access-Control-Request-Method':'GET'})
        assert cors.headers.get('access-control-allow-origin')==args.web
        print(f"PASS real next race {race['race_id']}, demo routes rejected, forecast cutoffs, classification, and CORS",flush=True)


if __name__=='__main__': main()
