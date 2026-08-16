# Tempest

Tempest is a private-beta flight planning assistant for pilots. It stores personal
minimums, checks METAR/TAF and runway constraints, recommends destinations from a
home airport, evaluates route weather, and can add an advisory OpenAI briefing.

Tempest is advisory software only. It is not a regulatory weather briefing,
flight release, aircraft performance tool, or substitute for pilot judgment.

## Features

- Open signup with password login and HTTP-only session cookies
- Per-user personal minimums profiles stored in JSON
- Destination recommendations from a home airport with distance range controls
- Favorite airport boosting without overriding deterministic safety decisions
- Route checks for inputs like `KLAF - KIND`
- Enroute weather sampling from the AviationWeather station index
- Decoded METAR/TAF panels and explainable pass/caution/failure reasons
- Optional server-side OpenAI advisory briefing

## Local Development

Install dependencies:

```bash
python3 -m pip install -r requirements-dev.txt
```

Create `.env.local` in the repo root:

```bash
OPENAI_API_KEY=sk-...
TEMPEST_SESSION_SECRET=replace-with-a-long-random-secret
TEMPEST_AI_MODEL=gpt-5-mini
TEMPEST_AI_TIMEOUT_SECONDS=90
TEMPEST_AI_REASONING_EFFORT=minimal
```

`OPENAI_API_KEY` is optional. Without it, deterministic recommendations and route
checks still work and AI is shown as unavailable.

Start the app:

```bash
PYTHONPATH=backend/app uvicorn tempest_api.app:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Render Deployment

This repo includes `render.yaml` for a private beta web service.

Set these Render environment variables:

```text
OPENAI_API_KEY=sk-...
TEMPEST_SESSION_SECRET=<long random secret>
TEMPEST_AI_MODEL=gpt-5-mini
TEMPEST_AI_TIMEOUT_SECONDS=90
TEMPEST_AI_REASONING_EFFORT=minimal
TEMPEST_FETCH_STATION_CACHE=1
TEMPEST_COOKIE_SECURE=1
```

The Render config stores JSON data on a persistent disk mounted at `/var/data`:

```text
TEMPEST_USERS_PATH=/var/data/auth/users.json
TEMPEST_MINIMUMS_PATH=/var/data/minimums/profiles.json
TEMPEST_CACHE_DIR=/var/data/cache
```

After deployment, smoke test:

1. Open the Render URL.
2. Create a beta account.
3. Acknowledge the advisory-use notice.
4. Save a minimums profile with a home airport.
5. Run destination recommendations.
6. Run a route check such as `KLAF - KIND`.
7. Toggle AI advisory review on and off.

## Tests

Run the backend suite:

```bash
pytest backend/tests
```

Run frontend syntax and Python compile checks:

```bash
node --check frontend/app.js
python3 -m compileall backend/app
git diff --check
```

## Important Limitations

- Open signup is enabled for the private beta URL; do not publish the URL widely.
- JSON storage is acceptable for a small beta but should be replaced with a
  database before a larger multi-user launch.
- No email verification, password reset, audit logging, or admin dashboard yet.
- Tempest does not evaluate aircraft-specific performance beyond saved profile
  limits.
- Always verify weather, NOTAMs, airspace, fuel, weight and balance, and legal
  requirements with official sources before flight.
