import argparse
import json
from apps.api.database import SessionLocal
from ml.live.operations import inspect,record_alerts


def main():
    p=argparse.ArgumentParser(); p.add_argument('--record-alerts',action='store_true'); a=p.parse_args()
    with SessionLocal() as db:
        status=inspect(db)
        if a.record_alerts: record_alerts(db,status)
    print(json.dumps(status,indent=2)); raise SystemExit(0 if status['ready'] else 1)


if __name__=='__main__': main()
