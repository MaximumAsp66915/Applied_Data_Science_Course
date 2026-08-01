# SUT Music recommendation engine

A standalone microservice wrapping the matrix-factorization model described
in `manual.txt` / `engine_new.ipynb`. Runs as its **own process, with its own
venv**, completely separate from the main app (`../app`) -- different
dependencies (no Postgres/Telegram stack, no torch), different release
cadence (model files get swapped out weekly, independent of app deploys),
and it should be possible to restart/redeploy one without touching the
other.

It listens on **127.0.0.1 only** -- never a public interface. It has no
auth of its own; loopback-only binding is the entire security boundary, so
the only thing that can ever call it is something already running on the
same machine (the webapp, via `app/webapp/engine_client.py`).

## Running it

```bash
cd engine
bash setup_venv.sh          # one-time: creates engine/.venv, installs requirements.txt
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8100
```

### In production

This runs under its own systemd **user** unit, `deploy/sutengine.service` --
deliberately separate from the app stack's `sutmusic.service`
(`../app/deploy/sutmusic.service`), so the two can be deployed and
restarted completely independently:

- `.github/workflows/deploy-engine.yml` only fires on pushes that touch
  `engine/**`, syncs this folder to the server, and restarts
  `sutengine.service` -- never `sutmusic.service`.
- `.github/workflows/deploy-app.yml` only fires on pushes that touch
  `app/**`, and only ever restarts `sutmusic.service`.

So a model retrain (new files under `model_params/`) or an engine code
change deploys and restarts in isolation, without taking the bot/webapp/
frontend down, and vice versa.

One-time setup on the server (see the comment at the top of
`deploy/sutengine.service` for the exact commands): create `engine/.venv`
via `setup_venv.sh`, then install and enable `sutengine.service` the same
way `sutmusic.service` was set up for the app.

Host/port are read from `ENGINE_HOST`/`ENGINE_PORT` (see `.env.example`),
defaulting to `127.0.0.1:8100`.

## Contract

All endpoints are plain `GET` with query params, JSON responses.

### `GET /health`
```json
{"status": "ok", "n_users": 1284, "n_artists": 4996, "n_tracks": 12324}
```

### `GET /suggest`
The main endpoint -- a single next-track pick. This is the contract
`app/webapp/routers/suggestions.py` and `repository.py`'s
`_suggest_unheard_track` already speak (`GET /suggest?user_id=...`), now
extended with optional additional signal:

| param | required | meaning |
|---|---|---|
| `user_id` | no | Internal user id. If this user was part of the training snapshot, their real trained embedding is used -- the best-quality signal available. |
| `reacted_artist_ids` | no | Comma-separated artist ids the user has positively reacted to (directly, or via a track -- see `repository.get_liked_artist_ids`). Used when `user_id` isn't recognized (new user / joined after the last training run). |
| `reacted_track_ids` | no | Comma-separated track ids the user has positively reacted to. Their primary artists are averaged -- the cold-start path from `manual.txt` section 5, for onboarding reactions. |
| `exclude_track_ids` | no | Comma-separated track ids to never return (already seen/played). |

Falls back to overall popularity (excluding `exclude_track_ids`) if none of
the above yield anything.

```json
{"track_id": 4821, "reason": "Based on your listening history", "source": "trained_embedding"}
```

`source` is one of `trained_embedding`, `reacted_artists`, `reacted_tracks`,
`popular_fallback`.

### `GET /recommend`
Same params as `/suggest`, plus `top_k` (default 10, max 50) -- returns the
full ranked list in one round trip instead of just the top pick:

```json
{"track_ids": [4821, 991, 233, ...], "source": "trained_embedding"}
```

### `GET /onboarding`
Cold-start tracks for a brand-new user with no reactions yet (`manual.txt`
section 5) -- `count` tracks (default 5, max 20) from that many different
popular artists:

```json
{"track_ids": [12, 8841, 233, 91, 5]}
```

## What this deliberately does NOT do

- No database access, no knowledge of Postgres/the bot's schema. The app
  side gathers whatever signal it has (reacted artists, seen tracks) and
  passes it in on each call -- this stays a pure, stateless "given this
  input, here's the ranking" service.
- No retraining, no writing to `model_params/`. Per `manual.txt` section 7,
  the model files are static between weekly retrains; swapping them in is
  an out-of-band step (copy new files into `model_params/`, restart this
  process).
- No public-facing anything -- see the binding note above.
