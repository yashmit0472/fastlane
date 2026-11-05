import copy
import unittest
from ml.ingestion.downloaded_data import session_index,weather_audit
from ml.features.practice import apply_session_metadata

HISTORY=[{'season':'2023','round':'1','date':'2023-03-05','time':'15:00:00Z',
    'Circuit':{'circuitId':'bahrain','Location':{'country':'Bahrain','lat':'26.0325','long':'50.5106'}}}]


def row(key,name,start,end,cancelled='False'):
    return {'session_key':str(key),'meeting_key':'1141','session_name':name,'date_start':start,'date_end':end,
        'is_cancelled':cancelled,'year':'2023','country_name':'Bahrain','circuit_short_name':'Sakhir'}


def fixture():
    return [row(1,'Race','2023-03-05T15:00:00Z','2023-03-05T17:00:00Z'),
        row(2,'Practice 1','2023-03-03T11:30:00Z','2023-03-03T12:30:00Z'),
        row(3,'Practice 2','2023-03-03T15:00:00Z','2023-03-03T16:00:00Z','True')]


class DownloadedDataTests(unittest.TestCase):
    def test_cancelled_sessions_are_not_joined(self):
        index=session_index(fixture(),HISTORY)
        self.assertEqual(index['coverage']['mapped_races'],1)
        self.assertEqual(index['coverage']['cancelled_sessions'],1)
        self.assertEqual(index['races']['2023-01']['sessions']['FP1']['session_key'],2)
        self.assertNotIn('FP2',index['races']['2023-01']['sessions'])

    def test_duplicate_ids_and_naive_times_are_rejected(self):
        data=fixture()
        with self.assertRaisesRegex(ValueError,'Duplicate'): session_index(data+[data[0]],HISTORY)
        data[0]['date_start']='2023-03-05T15:00:00'
        with self.assertRaisesRegex(ValueError,'timezone'): session_index(data,HISTORY)

    def test_country_and_ambiguous_race_dates_cannot_silently_join(self):
        data=fixture(); data[0]['country_name']='Germany'
        self.assertEqual(session_index(data,HISTORY)['coverage']['mapped_races'],0)
        extra=copy.deepcopy(HISTORY[0]); extra['round']='2'
        self.assertEqual(session_index(fixture(),HISTORY+[extra])['coverage']['mapped_races'],0)

    def test_berlin_weather_is_not_race_training_data(self):
        content=b'latitude,longitude,elevation,utc_offset_seconds,timezone\n52.5,13.4,38,0,GMT\n\ntime,temperature_2m\n2026-10-19T12:00,14.0\n'
        report=weather_audit(content,HISTORY)
        self.assertFalse(report['training_eligible'])
        self.assertGreater(report['nearest_circuit_distance_km'],25)
        self.assertTrue(any('training window' in reason for reason in report['reasons']))

    def test_metadata_must_match_race_stage_and_time_window(self):
        metadata=session_index(fixture(),HISTORY)['races']['2023-01']['sessions']['FP1']
        summary={'race_id':'2023-01','type':'FP1','started_at':'2023-03-03T11:40:00Z','ended_at':'2023-03-03T12:10:00Z'}
        result=apply_session_metadata(summary,metadata)
        self.assertEqual(result['metadata_session_key'],2)
        self.assertEqual(result['metadata_ended_at'],'2023-03-03T12:30:00+00:00')
        for change in [{'race_id':'2023-02'},{'cancelled':True},{'ended_at':'2023-03-02T12:30:00Z'}]:
            with self.assertRaises(ValueError): apply_session_metadata(summary,{**metadata,**change})


if __name__=='__main__': unittest.main()
