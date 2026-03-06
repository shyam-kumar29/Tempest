# Tempest

Pure Python backend foundation for aviation weather workflows.

## Current scope

- Fetch latest METAR from AviationWeather.gov Data API
- Optionally fetch latest TAF from AviationWeather.gov Data API
- Normalize the METAR payload into a typed internal model
- Manage personal minimums profiles in a local JSON store
- Cache responses locally to reduce API calls
- Expose a CLI command for station lookup

TAF fetch, personal minimums evaluation, and runway wind component logic are intentionally deferred.

## Project layout

- `backend/app/tempest`: core Python modules
- `backend/scripts/fetch_metar.py`: CLI entrypoint
- `backend/tests`: unit tests
- `data/cache`: local API cache files

## Run METAR fetch

```bash
python3 backend/scripts/fetch_metar.py KLAF
```

Useful options:

```bash
python3 backend/scripts/fetch_metar.py KLAF \
  --cache-dir data/cache \
  --cache-ttl-seconds 300 \
  --min-fetch-interval-seconds 60 \
  --include-taf
```

Example output shape:

```json
{
  "source": "api",
  "metar": {
    "icao_id": "KLAF",
    "raw_text": "KLAF ...",
    "observed_at": "...",
    "wind_speed_kt": 12,
    "flight_category": "VFR",
    "source_payload": {
      "...": "..."
    }
  }
}
```

`source` indicates if the response came from `api`, `cache`, `throttled-cache`, or `stale-cache`.
When `--include-taf` is set, output includes `taf` and `taf_source` (or `taf_error`).

## Tests

```bash
pytest -q backend/tests
```

## Manage personal minimums

Set/update a profile:

```bash
python3 backend/scripts/manage_minimums.py set primary \"Primary Profile\" \
  --min-ceiling-ft-agl 2500 \
  --min-visibility-sm 5 \
  --max-surface-wind-kt 20 \
  --max-crosswind-kt 12 \
  --max-gust-kt 28 \
  --max-tailwind-kt 7 \
  --min-runway-length-ft 3000 \
  --allowed-runway-surface asphalt \
  --allowed-runway-surface concrete \
  --min-fuel-reserve-min 60 \
  --allow-ifr
```

List profiles:

```bash
python3 backend/scripts/manage_minimums.py list
```
