# Tempest

Pure Python backend foundation for aviation weather workflows.

## Current scope

- Fetch latest METAR from AviationWeather.gov Data API
- Optionally fetch latest TAF from AviationWeather.gov Data API
- Optionally fetch airport/runway data from AviationWeather.gov Data API
- Normalize the METAR payload into a typed internal model
- Manage personal minimums profiles in a local JSON store
- Compute runway wind components when runway heading data is available
- Evaluate current conditions against a saved personal minimums profile
- Cache responses locally to reduce API calls
- Expose a CLI command for station lookup

Density altitude and fuel-planning checks are still stored as profile data, but they are not fully computed yet in the evaluation engine.

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
  --include-taf \
  --include-airport \
  --include-runway-wind
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
When `--include-airport` is set, output includes `airport` and `airport_source` (or `airport_error`).
When `--include-runway-wind` is set, output includes `runway_wind_components`.

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
  --min-runway-width-ft 75 \
  --allowed-runway-surface asphalt \
  --allowed-runway-surface concrete \
  --min-fuel-reserve-day-min 45 \
  --min-fuel-reserve-night-min 60 \
  --allow-ifr
```

All minimums fields are optional except `profile_id` and `display_name`. If a field is omitted, it is stored as empty (`null`) and ignored by downstream evaluation logic.

List profiles:

```bash
python3 backend/scripts/manage_minimums.py list
```

## Evaluate a flight

Evaluate one saved profile against the current airport weather:

```bash
python3 backend/scripts/evaluate_flight.py KLAF primary --include-taf
```

By default, evaluation checks the live API first so the weather data is as current as possible. Cached data is only used as a fallback if the live fetch fails. Use `--prefer-cache` only if you explicitly want to trust fresh cache entries first.

The evaluator currently checks:

- visibility
- ceiling
- surface wind
- gusts
- IFR/night restrictions
- runway length, width, and surface suitability
- crosswind and tailwind against the best available runway

The result is explainable JSON with `decision`, `fail_reasons`, `caution_reasons`, `pass_reasons`, and `unknowns`.
