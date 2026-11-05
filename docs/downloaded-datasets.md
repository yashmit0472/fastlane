# Downloaded dataset audit — 19 October 2026

Three new F1-related CSV downloads were found in Downloads. Original downloads were not modified.

| File | Finding | Integration |
|---|---|---|
| sessions.csv | 118 OpenF1-format session records, all from 2023; dates, IDs and cancellation flags, without driver lap times | Imported as session metadata. 110 records map to 22 historical races. Five cancelled Imola records and three pre-season testing records remain outside completed-race mappings. |
| open-meteo-52.55N13.41E38m.csv | 168 hourly temperature rows, 18–24 October 2026, near Berlin | Excluded from F1 training: wrong location/date window and no audited forecast-availability provenance. |
| open-meteo-52.51N13.42E38m.csv | 192 hourly temperature rows plus previous-day forecast columns, 12–19 October 2026, near Berlin | Excluded for the same reasons. Previous-day columns alone do not make unrelated location data eligible. |

The weather grid locations are approximately 491–493 km from the nearest circuit in the imported history. Future weather imports need the circuit's latitude/longitude, relevant event dates, and an issuance/availability policy consistent with each prediction cutoff. Rain and wind context would also be useful; these two files contain temperature only.

The importer saves a checksummed raw session CSV under data/raw/user-imports and a normalized index at data/processed/openf1/session-index.json. Matching uses UTC race day, country, bounded race-start difference, meeting ID and unique session IDs. It rejects duplicate IDs and malformed/naive timestamps. The data is treated as user-provided metadata, not proof of historical publication timing.

The practice builder consumes the index automatically when available. It checks session/race/stage identities and cancellation, and cross-checks recorded lap timestamps against the supplied session interval. A compatible end time can make the estimated cutoff more conservative. It never moves a cutoff earlier than the recorded laps or treats a historical download time as pre-race publication proof.

Three Australian GP practice entries conflict with recorded lap timestamps by approximately one hour. Their external clock fields are flagged and ignored; the original validated practice data is retained. This is a source disagreement, not evidence that laps should be shifted by one hour. Historical publication cutoffs remain estimated.

Integration was checked in data/processed/practice-session-metadata-audit, separate from the CSVs used by the currently activated models. The new CSV contains no additional driver/pace observations, so no model retraining or performance improvement is claimed. All 40 regression tests passed. Full findings and source checksums are in [downloaded-datasets-audit.json](downloaded-datasets-audit.json).

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m ml.ingestion.downloaded_data --files "C:\Users\yashm\Downloads\sessions.csv" "C:\Users\yashm\Downloads\open-meteo-52.55N13.41E38m.csv" "C:\Users\yashm\Downloads\open-meteo-52.51N13.42E38m.csv"
.\.venv\Scripts\python.exe -m ml.features.practice --output-dir data/processed/practice-session-metadata-audit
.\.venv\Scripts\python.exe -m scripts.verify_downloaded_import
```

The final command verifies that metadata checks preserve existing eligible driver rows and numerical model inputs; it does not train or publish forecasts. The importer writes the file audit first; the verification command appends the comparison with actual lap data.
