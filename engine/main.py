"""SUT Music recommendation engine -- a standalone microservice.

Deliberately its own process with its own venv/requirements.txt (see
README.md), separate from the main app's FastAPI webapp: it has a
completely different dependency footprint (numpy/scikit-learn for model
artifacts vs. the webapp's Postgres/Telegram stack) and its own release
cadence (model files get swapped out weekly per manual.txt section 7,
independent of app deploys).

Binds to 127.0.0.1 ONLY -- never 0.0.0.0 -- see README.md and
deploy/start.sh's uvicorn invocation. Nothing here is meant to be reachable
from outside the machine; the webapp (app/webapp/engine_client.py) is the
only intended caller, over loopback.

Endpoints:
  GET /health      -- liveness + how many users/artists/tracks are loaded
  GET /suggest     -- single best-next-track pick (what
                      webapp/routers/suggestions.py and
                      repository.py's _suggest_unheard_track use)
  GET /recommend   -- a full ranked batch of track_ids in one round trip
                      (for a "for you" rail / prefetching a queue)
  GET /onboarding  -- cold-start tracks for a brand-new user (manual.txt
                      section 5)

See engine_client.py on the app side for the client half of this contract.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from recommender import Recommender

PARAMS_DIR = Path(__file__).resolve().parent / "model_params"

# 127.0.0.1 by default and on purpose -- see the module docstring. Only
# override HOST via ENGINE_HOST if you specifically know what you're doing;
# PORT is the only thing meant to be tuned normally.
HOST = os.environ.get("ENGINE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ENGINE_PORT", "8100"))

state: dict[str, Recommender] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Loaded once at process start (a few numpy arrays + pickles, well
    # under a second) and kept in memory for the life of the process --
    # manual.txt section 7: "no retraining is needed on the server; the
    # model files are static until the next weekly update." A weekly model
    # refresh means restarting this process (systemd/start.sh already
    # restarts the whole stack on any child exit).
    state["rec"] = Recommender(PARAMS_DIR)
    yield
    state.clear()


app = FastAPI(title="SUT Music recommendation engine", lifespan=lifespan)


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(x) for x in raw.split(",") if x.strip()]


def _build_vector(
    rec: Recommender,
    user_id: int | None,
    reacted_artist_ids: list[int],
    reacted_track_ids: list[int],
) -> tuple["object | None", str | None]:
    """Best signal first: a trained embedding for a known user beats an
    averaged one, which beats deriving artists from reacted tracks."""
    if user_id is not None:
        vector = rec.user_vector_from_id(user_id)
        if vector is not None:
            return vector, "trained_embedding"
    if reacted_artist_ids:
        vector = rec.user_vector_from_artists(reacted_artist_ids)
        if vector is not None:
            return vector, "reacted_artists"
    if reacted_track_ids:
        vector = rec.user_vector_from_tracks(reacted_track_ids)
        if vector is not None:
            return vector, "reacted_tracks"
    return None, None


def _reason_for(source: str | None) -> str:
    return {
        "trained_embedding": "Based on your listening history",
        "reacted_artists": "Because you liked similar artists",
        "reacted_tracks": "Because you liked similar tracks",
    }.get(source, "Popular with everyone right now")


@app.get("/health")
def health():
    rec = state["rec"]
    return {
        "status": "ok",
        "n_users": len(rec.user_enc.classes_),
        "n_artists": len(rec.artist_enc.classes_),
        "n_tracks": len(rec.track_id_to_idx),
    }


@app.get("/suggest")
def suggest(
    user_id: int | None = None,
    reacted_artist_ids: str | None = None,
    reacted_track_ids: str | None = None,
    exclude_track_ids: str | None = None,
):
    """GET /suggest?user_id=...&reacted_artist_ids=1,2&exclude_track_ids=3,4
    -> {"track_id": int, "reason": str, "source": str}

    Every param is optional and additive -- pass whatever the caller
    already has on hand. `user_id` alone (the original, still-supported
    contract) is enough to get a real personalized pick for any user the
    engine was trained on; `reacted_artist_ids` lets a user who joined (or
    started reacting) after the last training snapshot still get a
    personalized pick instead of falling back to popularity."""
    rec = state["rec"]
    exclude = set(_parse_ids(exclude_track_ids))
    vector, source = _build_vector(
        rec, user_id, _parse_ids(reacted_artist_ids), _parse_ids(reacted_track_ids)
    )

    picks: list[int] = []
    if vector is not None:
        picks = rec.recommend_from_vector(vector, exclude=exclude, top_k=1)
        if not picks:
            source = None  # top artists' tracks were all excluded -- fall through

    if not picks:
        picks = rec.popular_tracks(exclude=exclude, top_k=1)
        source = None

    if not picks:
        raise HTTPException(404, "No tracks available to suggest")

    return {"track_id": picks[0], "reason": _reason_for(source), "source": source or "popular_fallback"}


@app.get("/recommend")
def recommend(
    user_id: int | None = None,
    reacted_artist_ids: str | None = None,
    reacted_track_ids: str | None = None,
    exclude_track_ids: str | None = None,
    top_k: int = Query(10, ge=1, le=50),
):
    """Batch version of /suggest -- a full ranked list of up to `top_k`
    track_ids in one round trip, e.g. for a "for you" rail. Same params and
    fallback behavior as /suggest, just returns the whole ranked list."""
    rec = state["rec"]
    exclude = set(_parse_ids(exclude_track_ids))
    vector, source = _build_vector(
        rec, user_id, _parse_ids(reacted_artist_ids), _parse_ids(reacted_track_ids)
    )

    track_ids: list[int] = []
    if vector is not None:
        track_ids = rec.recommend_from_vector(vector, exclude=exclude, top_k=top_k)
        if not track_ids:
            source = None

    if not track_ids:
        track_ids = rec.popular_tracks(exclude=exclude, top_k=top_k)
        source = None

    return {"track_ids": track_ids, "source": source or "popular_fallback"}


@app.get("/onboarding")
def onboarding(count: int = Query(5, ge=1, le=20), exclude_track_ids: str | None = None):
    """Cold-start tracks for a brand-new user (manual.txt section 5):
    `count` tracks from `count` different popular artists."""
    rec = state["rec"]
    track_ids = rec.onboarding_tracks(count=count, exclude=set(_parse_ids(exclude_track_ids)))
    return {"track_ids": track_ids}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT)
