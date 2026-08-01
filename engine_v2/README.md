# SUT Music recommendation engine (v2, ensemble)

A standalone microservice wrapping the two-stage ensemble model described in
`Manual.txt` / `Summary.md` / `engine_new.ipynb`: an artist-level model
(`HybridArtistMF`) ranks candidate artists for a user, then a track-level
model (`TrackMF`) re-ranks the unseen tracks from those artists. Runs as its
**own process, with its own venv**, completely separate from the main app
(`../app`) and structured identically to `../engine_v1` so it's a drop-in
replacement on the server -- same file layout, same systemd unit, same
loopback-only contract.

It listens on **127.0.0.1 only** -- never a public interface. It has no auth
of its own; loopback-only binding is the entire security boundary, so the
only thing that can ever call it is something already running on the same
machine (the webapp, via `app/webapp/engine_client.py`).

## Only one engine on the server at a time

The server only ever has a single `engine/` folder. `.github/workflows/
deploy-engine.yml` watches every `engine_v*/**` path; whichever `engine_v*`
folder(s) changed in a push get compared, and the highest version number
among them is the one actually rsynced into the server's `engine/` and
restarted (see the workflow itself for the exact logic). So this folder,
`engine_v1/`, and any future `engine_v3/` etc. all need to keep the same
internal shape -- `main.py`, `recommender.py`, `requirements.txt`,
`model_params/`, `deploy/start.sh`, `deploy/sutengine.service`,
`setup_venv.sh`, `.env.example` -- so that whichever one lands on the server
as `engine/` runs under the exact same `sutengine.service` unit unmodified.

## Running it

```bash
cd engine
bash setup_venv.sh          # one-time: creates engine/.venv, installs requirements.txt
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8100
```

### In production

Runs under its own systemd **user** unit, `deploy/sutengine.service` --
deliberately separate from the app stack's `sutmusic.service`
(`../app/deploy/sutmusic.service`), so the two can be deployed and
restarted completely independently. See `.github/workflows/deploy-engine.yml`
for exactly how a push picks which `engine_v*` gets deployed.

One-time setup on the server (see the comment at the top of
`deploy/sutengine.service` for the exact commands): create `engine/.venv`
via `setup_venv.sh`, then install and enable `sutengine.service` the same
way `sutmusic.service` was set up for the app.

Host/port are read from `ENGINE_HOST`/`ENGINE_PORT` (see `.env.example`),
defaulting to `127.0.0.1:8100` -- same knobs as v1.

## Contract

Identical to `engine_v1`'s contract on purpose, so
`app/webapp/engine_client.py` -- and everything upstream of it
(`routers/suggestions.py`, `repository.py`'s `_suggest_unheard_track`) --
needs **no changes** to work with this engine. All endpoints are plain `GET`
with query params, JSON responses.

### `GET /health`
```json
{"status": "ok", "n_users": 1284, "n_artists": 4996, "n_tracks": 12324}
```

### `GET /suggest`
The main endpoint -- a single next-track pick.

| param | required | meaning |
|---|---|---|
| `user_id` | no | Internal user id. If present in the artist model's training snapshot, their real trained profile is used -- the best-quality signal available. If they're also present in the track model's snapshot, track-level re-ranking (stage 2) kicks in too; otherwise stage 2 falls back to popularity within the candidate pool. |
| `reacted_artist_ids` | no | Comma-separated artist ids the user has positively reacted to. Used when `user_id` isn't recognized. |
| `reacted_track_ids` | no | Comma-separated track ids the user has positively reacted to. Their primary artists are averaged -- the cold-start path from `Manual.txt` section 6. |
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
Cold-start tracks for a brand-new user with no reactions yet (`Manual.txt`
section 6) -- `count` tracks (default 5, max 20) from that many different
popular artists:

```json
{"track_ids": [12, 8841, 233, 91, 5]}
```

## Model files (`model_params/`)

Same directory name (`model_params/`) as v1, for structural parity, even
though `Manual.txt` (as handed off) calls it `model_params_colab` -- rename
whatever gets exported from the training notebook to `model_params/` before
dropping it in here. Expected contents (see `Manual.txt` section 2 for the
full description of each):

```
model_params/
  ensemble_config.json
  user_enc_artist.pkl
  artist_enc.pkl
  track_user_enc.pkl
  track_item_enc.pkl
  track_to_artist.pkl
  track_id_to_idx.pkl
  track_pop.npy
  artist_user_embeddings.npy
  artist_artist_embeddings.npy
  track_user_embeddings.npy
  track_item_embeddings.npy
```

The optional `artist_model_state.pt` / `track_model_state.pt` /
`genre_features.pt` files are not read by this service -- only needed if
someone wants to reload the full trainable models (e.g. for fine-tuning),
which is out of scope for `main.py` / `recommender.py` here, exactly as in
v1.

## What this deliberately does NOT do

- No database access, no knowledge of Postgres/the bot's schema. The app
  side gathers whatever signal it has (reacted artists, seen tracks) and
  passes it in on each call -- this stays a pure, stateless "given this
  input, here's the ranking" service, same as v1.
- No retraining, no writing to `model_params/`. Per `Manual.txt` section 8,
  the model files are static between weekly retrains; swapping them in is
  an out-of-band step (export from the notebook, rename to `model_params/`,
  restart this process).
- No public-facing anything -- see the binding note above.
