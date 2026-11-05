import unittest
from datetime import datetime,timedelta,timezone
from ml.live.race_window import race_view,focus_race,recent_unclassified,refresh_targets

NOW=datetime(2026,11,1,21,tzinfo=timezone.utc)
MEXICO={'season':'2026','round':'19','date':'2026-11-01','time':'20:00:00Z'}
BRAZIL={'season':'2026','round':'20','date':'2026-11-08','time':'17:00:00Z'}

def payload(raw,status='scheduled'):
    return {**raw,'race_id':f"{raw['season']}-{int(raw['round']):02d}",'scheduled_at':raw['date']+'T'+raw['time'],'status':status,'is_demo':False}

class RaceWindowTests(unittest.TestCase):
    def test_recent_race_stays_visible_until_classification(self):
        mexico=payload(MEXICO); brazil=payload(BRAZIL)
        self.assertEqual(focus_race([brazil,mexico],NOW)['race_id'],'2026-19')
        self.assertEqual(focus_race([brazil,{**mexico,'status':'completed'}],NOW)['race_id'],'2026-20')
        self.assertEqual(focus_race([brazil,mexico],NOW+timedelta(days=2))['race_id'],'2026-20')
        self.assertEqual(mexico['status'],'scheduled')

    def test_pending_race_ingestion_does_not_require_a_published_result(self):
        pending=recent_unclassified([MEXICO,BRAZIL],[],NOW)
        targets=refresh_targets([BRAZIL],pending,[MEXICO],0)
        self.assertEqual([int(r['round']) for r in targets],[20,19])
        self.assertEqual(recent_unclassified([MEXICO],[{**MEXICO,'Results':[{'position':'1'}]}],NOW),[])
        self.assertEqual(recent_unclassified([MEXICO],[],NOW+timedelta(days=8)),[])

    def test_archive_budget_does_not_duplicate_pending_race(self):
        self.assertEqual([r['round'] for r in refresh_targets([BRAZIL],[MEXICO],[MEXICO],1)],['20','19'])

    def test_elapsed_sessions_are_not_reported_as_future_or_published(self):
        p={**payload(MEXICO),'sessions':[{'type':'Q','started_at':'2026-10-31T21:00:00Z','status':'scheduled'}]}
        actual=race_view(p,NOW)
        self.assertEqual(actual['status'],'awaiting_classification')
        self.assertEqual(actual['sessions'][0]['status'],'elapsed')
        self.assertEqual(p['sessions'][0]['status'],'scheduled')

    def test_demo_does_not_become_current_and_offseason_keeps_last_result(self):
        self.assertIsNone(focus_race([{**payload(MEXICO),'is_demo':True}],NOW))
        self.assertEqual(focus_race([payload(MEXICO,'completed')],NOW)['race_id'],'2026-19')

if __name__=='__main__': unittest.main()
