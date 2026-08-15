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

Fuel reserve is evaluated when the app supplies current usable reserve in minutes. Destination suggestions and aircraft performance/range ranking are future work.

## Project layout

- `backend/app/tempest`: core Python modules
- `backend/app/tempest_api`: FastAPI app layer
- `backend/scripts/fetch_metar.py`: CLI entrypoint
- `frontend`: static V1 app
- `backend/tests`: unit tests
- `data/cache`: local API cache files

## Run the V1 app

Install web dependencies in your virtual environment:

```bash
python3 -m pip install -r requirements-dev.txt
```

Start the app:

```bash
PYTHONPATH=backend/app uvicorn tempest_api.app:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

AI review is optional. For local AI briefings, create a `.env.local` file in the
repo root:

```bash
OPENAI_API_KEY=sk-...
TEMPEST_AI_MODEL=gpt-5-mini
TEMPEST_AI_TIMEOUT_SECONDS=45
TEMPEST_AI_REASONING_EFFORT=minimal
```

The backend loads `.env.local` on startup, and the file is ignored by Git. You
can also set the same values in the server environment before starting the app:

```bash
export OPENAI_API_KEY=...
export TEMPEST_AI_MODEL=gpt-5-mini
export TEMPEST_AI_TIMEOUT_SECONDS=45
export TEMPEST_AI_REASONING_EFFORT=minimal
PYTHONPATH=backend/app uvicorn tempest_api.app:app --reload
```

Without `OPENAI_API_KEY`, deterministic route checks and destination recommendations
still work; the AI panel is shown as unavailable. To let pilots use AI without
entering their own key, host the backend yourself with `OPENAI_API_KEY` configured
server-side and do not expose the key to the browser.

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

API tests require the optional web dependencies in `requirements-dev.txt`.

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
python3 backend/scripts/evaluate_flight.py KLAF primary \
  --include-taf \
  --planned-departure 2026-04-04T18:30:00Z \
  --taf-lookahead-hours 3 \
  --fuel-reserve-min 60
```

By default, evaluation checks the live API first so the weather data is as current as possible. Cached data is only used as a fallback if the live fetch fails. Use `--prefer-cache` only if you explicitly want to trust fresh cache entries first.

For evaluation specifically, cached reports are only trusted when the underlying data is still current:

- METAR: observation/report time must be within 1 hour of current UTC time
- TAF: current time must still fall inside the TAF valid window
- Airport data: cached for longer because runway metadata changes rarely

The evaluator currently checks:

- visibility
- ceiling
- surface wind
- gusts
- IFR/night restrictions
- runway length, width, and surface suitability
- crosswind and tailwind against the best available runway
- forecast ceiling, visibility, wind, and gusts in matching TAF periods
- density altitude when temperature, altimeter, and airport elevation are available
- fuel reserve when the current reserve is supplied

The result is explainable JSON with `decision`, `fail_reasons`, `caution_reasons`, `pass_reasons`, and `unknowns`.
