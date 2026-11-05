"""Read-only HTTP smoke check for the local dashboard and outcome reports."""
import httpx


def main():
    with httpx.Client(timeout=60) as client:
        base='http://127.0.0.1:8000'
        response=client.get(base+'/health'); response.raise_for_status()
        response=client.get(base+'/api/model/outcomes'); response.raise_for_status()
        reports=response.json(); assert set(reports['stages'])=={'FP1','FP2','FP3','Q'}
        for route in ['/api/model/validation','/api/model/source-validation','/api/performance']:
            response=client.get(base+route); response.raise_for_status()
        races=client.get(base+'/api/races').json()['races']
        assert races and all(r['is_demo'] is False for r in races)
        future=next(r for r in races if r['status']!='completed')
        previous=next(r for r in races if r['status']=='completed')
        for route,expected in [('/','The weekend, in focus.'),('/methodology','Podium &amp; top-10 models'),
                ('/predictions','Completed races'),('/performance','Track the forecast.'),(f"/races/{previous['race_id']}",'Published'),
                (f"/weekend/{previous['race_id']}",'Best lap')]:
            page=client.get('http://127.0.0.1:3010'+route); page.raise_for_status()
            assert expected in page.text,(route,'Missing expected content')
            if route == '/':
                assert 'hero-car.webp' in page.text
                assert 'PREDICT THE' in page.text and 'UNPREDICTABLE.' in page.text
                assert 'racing-hero' in page.text
            print(route,page.status_code,flush=True)
        font=client.get('http://127.0.0.1:3010/fonts/inter-variable.woff2'); font.raise_for_status()
        assert font.content[:4]==b'wOF2'
        prediction=client.get(base+f"/api/races/{future['race_id']}/prediction")
        if prediction.status_code==200:
            payload=prediction.json(); assert payload['is_demo'] is False
            assert payload.get('input_quality') and all(d.get('observations') for d in payload['drivers'])
        else: assert prediction.status_code==404
        for race in [future,previous]:
            response=client.get(base+f"/api/races/{race['race_id']}/report-card"); response.raise_for_status()
        print('Verified real-only API, outcome reports, dashboard routes and self-hosted font.')


if __name__=='__main__': main()
