# SUT Music recommendation engine — R&D build

A rewrite of the `engine_v2` serving microservice. Same two-stage ensemble
model, same artifacts, same HTTP contract, different everything else.

The model architecture was not the problem — artist-first shortlisting with
track-level re-ranking is the right design for a 1.7%-dense interaction
matrix. The serving code around it was. **[ANALYSIS.md](ANALYSIS.md)** is the
full study: how the v2 pipeline works end to end, 30 findings with evidence,
and what was done about each. This file is how to run the result.

## Why the folder is called `engine RND`

`.github/workflows/deploy-engine.yml` deploys folders matching `engine_v*`.
This one does not match, so it can never be auto-deployed — which is what an
R&D folder should be. Promoting it to production means copying it to
`engine_v3/`; nothing else has to change, the internal layout is identical to
`engine_v1` and `engine_v2` on purpose (`main.py`, `recommender.py`,
`requirements.txt`, `model_params/`, `deploy/start.sh`,
`deploy/sutengine.service`, `setup_venv.sh`).

The space in the name means paths need quoting: `cd "engine RND"`.

## Running it

```bash
cd "engine RND"
bash setup_venv.sh          # creates .venv, installs deps, builds model_params/
source .venv/bin/activate
uvicorn main:app --host 127.0.0.1 --port 8100
```

Binds to **127.0.0.1 only**, never a public interface. There is no auth of its
own; loopback is the entire security boundary, same as v1 and v2. The systemd
unit now enforces that with `IPAddressAllow=localhost` rather than leaving it
to a default argument.

Without a built bundle the engine falls back to reading
`../engine_v2/model_params/` directly (read-only). That works for a quick
look, but needs `scikit-learn` and cannot use the artist bias — see
[`model_params/README.md`](model_params/README.md).

### Tests

```bash
pip install pytest && python -m pytest tests/ -q     # 99 tests
```

`engine_v1` and `engine_v2` have none between them. These cover every fix
listed below, each test naming the v2 behaviour it exists to prevent coming
back, plus the HTTP contract field by field.

### Benchmark

```bash
python tools/benchmark.py --users 300 --session-length 20
```

Runs engine_v2's exact serving algorithm and this one over the same artifacts
and compares them. Numbers in [ANALYSIS.md §3](ANALYSIS.md#3-what-was-measured).

## What changed

### Serving

| | engine_v2 | here |
|---|---|---|
| Candidate collection | truncate to `tracks_per_artist`, then drop excluded | drop excluded, **then** truncate |
| Empty candidate pool | straight to global popularity | widen the artist shortlist ×2, ×4, ×8 first |
| Stage-1 score | dot product only (bias was never exported) | dot product + trained artist bias, weighted |
| Tracks with no reactions | unreachable — 2,410 of 14,843 | eligible candidates |
| Candidates with no track embedding | silently dropped from the pool | scored by popularity prior |
| Repeated artists | unlimited (five Eminem tracks in v2's own output) | per-response cap + session-level damping |
| Live reactions for a known user | discarded | blended into the trained vector |
| `/suggest` | deterministic forever | softmax-over-rank sampling, tunable |
| Stage-2 scoring | Python loop of dot products | one matmul |
| Cold-start centroid | raw mean, different scale to trained vectors | rescaled to the trained norm |

### Operations

| | engine_v2 | here |
|---|---|---|
| Artifact validation | none | 8 consistency checks, fail at load |
| Failed model load | every request 500s on `KeyError` | `/health` reports `degraded`, endpoints 503 |
| Malformed query ids | 500 with a traceback | 422 with a message |
| Which model is running? | unanswerable | `/health` reports layout, fingerprint, config |
| Serving parameters | four sources disagreeing | `config.py`, one resolution order |
| Serving dependencies | fastapi, uvicorn, numpy, **scikit-learn** | fastapi, uvicorn, numpy |
| Pickles at serve time | 4 files | none |
| Artifact size | 29 MB | 11.1 MB bundle |
| `pip install` on restart | yes, every time | no |
| Tests | 0 | 99 |

## HTTP contract

Unchanged from engine_v2, deliberately: `app/webapp/engine_client.py` and
everything upstream of it (`routers/suggestions.py`, `repository.py`'s
`_suggest_unheard_track`) work against this process with **no changes**. Every
field v2 returned is still returned with the same name and meaning; new fields
are additive. `tests/test_api.py::TestEngineV2Contract` pins this down.

### `GET /health`

```json
{"status": "ok", "n_users": 1310, "n_artists": 5107, "n_tracks": 14843,
 "layout": "v3", "fingerprint": "sha256:4b3bb9501a5f924b",
 "stats": {...}, "config": {...}}
```

Returns 503 with `{"status": "degraded", "error": ...}` if the artifacts
failed to load.

### `GET /suggest`

One next-track pick. All parameters optional.

| param | meaning |
|---|---|
| `user_id` | internal user id; a trained profile is used if it exists |
| `reacted_artist_ids` | comma-separated; used for unknown users **and** blended into a known user's profile |
| `reacted_track_ids` | comma-separated; resolved to their primary artists, and to a track-space centroid |
| `exclude_track_ids` | never return these; also drives session-level artist damping |
| `implicit_liked_track_id` | played to the end — nudges this response only |
| `implicit_disliked_track_id` | skipped — nudges this response only |

```json
{"track_id": 4821, "reason": "Based on your listening history",
 "source": "trained_embedding", "pool_size": 137}
```

`source` is one of `trained_embedding`, `blended_profile`, `reacted_artists`,
`reacted_tracks`, `popular_fallback`. Only `blended_profile` is new.

### `GET /recommend`

Same parameters plus `top_k` (default 10, max 50).

```json
{"track_ids": [4821, 991, 233], "source": "trained_embedding",
 "pool_size": 137, "reranked": true}
```

### `GET /onboarding`

`count` tracks (default 5, max 20) from `count` different popular artists,
filtered so the chosen artists are not near-duplicates of each other in
embedding space.

```json
{"track_ids": [12, 8841, 233, 91, 5]}
```

### `GET /explain` — new

The same ranking as `/recommend`, plus the shortlisted artists and their
scores, the candidate pool size, and how far the search had to widen.
Answering "why did it pick that?" against engine_v2 meant reproducing the
request in a notebook.

## Configuration

Defaults in `config.py`, overridden by the bundle's `serving` block,
overridden by `ENGINE_*` environment variables. Whatever wins is reported by
`/health`.

| variable | default | what it does |
|---|---:|---|
| `ENGINE_HOST` / `ENGINE_PORT` | `127.0.0.1` / `8100` | as in v1/v2 |
| `ENGINE_PARAMS_DIR` | auto | override artifact location |
| `ENGINE_N_ARTIST_CANDIDATES` | 20 | stage-1 shortlist size |
| `ENGINE_TRACKS_PER_ARTIST` | 10 | per-artist candidate cap |
| `ENGINE_ARTIST_BIAS_WEIGHT` | 0.0 | 1.0 reproduces the trained scoring function |
| `ENGINE_POP_PRIOR_WEIGHT` | 0.10 | popularity tie-breaker strength |
| `ENGINE_MAX_TRACKS_PER_ARTIST_IN_RESULT` | 2 | diversity cap per response |
| `ENGINE_SESSION_DAMPING` | 0.6 | penalty on already-served artists |
| `ENGINE_FRESH_SIGNAL_WEIGHT` | 0.35 | pull of live reactions on a trained profile |
| `ENGINE_EXPLORE_TEMPERATURE` | 3.0 | 0 = deterministic `/suggest` |
| `ENGINE_INCLUDE_UNSCORED_TRACKS` | true | allow zero-reaction tracks as candidates |

Setting `artist_bias_weight=0`, `pop_prior_weight=0`, `session_damping=0`,
`explore_temperature=0`, `max_tracks_per_artist_in_result=0` and
`fresh_signal_weight=0` gets you engine_v2's behaviour minus its bugs, which
is a useful A/B baseline.

`artist_bias_weight` defaults to **off** even though 1.0 is what the model was
trained with — the measured diversity cost is real and there is no accuracy
evaluation yet to weigh against it. [ANALYSIS.md §4](ANALYSIS.md#4-what-is-still-open)
says exactly what would settle it.

## Layout

```
main.py              FastAPI app: five endpoints, error handling
recommender.py       the two-stage ensemble; nine numbered fixes vs v2
artifacts.py         loading, validation, request-path indexes; v3 and v2 layouts
config.py            serving knobs, one resolution order
evaluation.py        split protocol and metrics (unit-tested, no torch)
tools/
  build_params.py    engine_v2 exports -> validated v3 bundle
  torch_pickle.py    read .pt state dicts as numpy, without torch
  benchmark.py       engine_v2's algorithm vs this one, same artifacts
tests/               99 tests
deploy/              systemd unit + launcher, same contract as v1/v2
model_params/        generated; see its README
ANALYSIS.md          the study this rewrite came out of
```

## What this deliberately still does not do

Unchanged from v2, and right in both:

- **No database access.** The app gathers whatever signal it has and passes it
  in per request; this stays a stateless "given this input, here is the
  ranking" service.
- **No retraining, no writes to `model_params/`.** Retraining is an
  out-of-band step: export from the notebook, run `tools/build_params.py`,
  restart.
- **Nothing public-facing.** See the binding note above.

One small documentation bug inherited from v2, noted rather than fixed since
it is outside this folder: `engine_v2/README.md` tells you to see
`.env.example` for the host/port knobs, but the repository's `.gitignore`
matches `.env*`, so that file has never been committed and does not exist.
The environment table above replaces it.
