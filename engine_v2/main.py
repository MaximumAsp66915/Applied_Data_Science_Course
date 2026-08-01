"""SUT Music recommendation engine v2 -- a standalone microservice.

Same role as engine_v1/main.py: its own process, own venv/requirements.txt
(see README.md), separate from the main app's FastAPI webapp. What changed
under the hood is the model -- v1 was a single matrix-factorization model,
v2 is a two-stage ensemble (artist-level ranking + track-level re-ranking,
see Manual.txt / Summary.md) -- but the HTTP contract this process exposes
is unchanged on purpose: /health, /suggest, /recommend, /onboarding, same
params, same response shapes. That's what lets
app/webapp/engine_client.py -- and everything upstream of it
(routers/suggestions.py, repository.py's _suggest_unheard_track) -- keep
working with zero changes, regardless of which engine_v* folder is
currently the one deployed to the server's engine/ (see
.github/workflows/deploy-engine.yml).

Binds to 127.0.0.1 ONLY -- never 0.0.0.0 -- see README.md and
deploy/start.sh's uvicorn invocation, identical reasoning to v1.

Endpoints:
  GET /health      -- liveness + how many users/artists/tracks are loaded
  GET /suggest     -- single best-next-track pick
  GET /recommend   -- a full ranked batch of track_ids in one round trip
  GET /onboarding  -- cold-start tracks for a brand-new user

See engine_client.py on the app side for the client half of this contract,
and README.md in this folder for the full write-up.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query

from recommender import Recommender, UserProfile

PARAMS_DIR = Path(__file__).resolve().parent / "model_params"

# 127.0.0.1 by default and on purpose -- see the module docstring. Only
# override HOST via ENGINE_HOST if you specifically know what you're doing;
# PORT is the only thing meant to be tuned normally.
HOST = os.environ.get("ENGINE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ENGINE_PORT", "8100"))

state: dict[str, Recommender] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Loaded once at process start and kept in memory for the life of the
    # process -- model files are static until the next weekly update
    # (Manual.txt section 8: "replace the entire model_params folder and
    # reload the server"). systemd/start.sh already restarts the whole
    # stack on any child exit.
    state["rec"] = Recommender(PARAMS_DIR)
    yield
    state.clear()


app = FastAPI(title="SUT Music recommendation engine (v2, ensemble)", lifespan=lifespan)


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(x) for x in raw.split(",") if x.strip()]


def _build_profile(
    rec: Recommender,
    user_id: int | None,
    reacted_artist_ids: list[int],
    reacted_track_ids: list[int],
) -> UserProfile | None:
    """Best signal first: a trained profile for a known user beats one
    built from reacted artists, which beats deriving artists from reacted
    tracks -- same precedence as v1's _build_vector."""
    if user_id is not None:
        profile = rec.profile_from_id(user_id)
        if profile is not None:
            return profile
    if reacted_artist_ids:
        profile = rec.profile_from_artists(reacted_artist_ids)
        if profile is not None:
            return profile
    if reacted_track_ids:
        profile = rec.profile_from_tracks(reacted_track_ids)
        if profile is not None:
            return profile
    return None


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
        "n_users": len(rec.user_enc_artist.classes_),
        "n_artists": len(rec.artist_enc.classes_),
        "n_tracks": len(rec.track_id_to_idx),
    }


@app.get("/suggest")
def suggest(
    user_id: int | None = None,
    reacted_artist_ids: str | None = None,
    reacted_track_ids: str | None = None,
    exclude_track_ids: str | None = None,
    implicit_liked_track_id: int | None = None,
    implicit_disliked_track_id: int | None = None,
):
    """GET /suggest?user_id=...&reacted_artist_ids=1,2&exclude_track_ids=3,4
    -> {"track_id": int, "reason": str, "source": str}

    Identical contract to engine_v1 -- see README.md. `implicit_liked_track_id`
    / `implicit_disliked_track_id` nudge the profile for this single
    response only (Recommender.nudge_profile) -- never persisted anywhere.
    """
    rec = state["rec"]
    exclude = set(_parse_ids(exclude_track_ids))
    profile = _build_profile(
        rec, user_id, _parse_ids(reacted_artist_ids), _parse_ids(reacted_track_ids)
    )

    if profile is not None and (
        implicit_liked_track_id is not None or implicit_disliked_track_id is not None
    ):
        profile = rec.nudge_profile(profile, implicit_liked_track_id, implicit_disliked_track_id)

    picks: list[int] = []
    source = profile.source if profile is not None else None
    if profile is not None:
        picks = rec.recommend_from_profile(profile, exclude=exclude, top_k=1)
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
    track_ids in one round trip. Same params and fallback behavior as
    /suggest, just returns the whole ranked list."""
    rec = state["rec"]
    exclude = set(_parse_ids(exclude_track_ids))
    profile = _build_profile(
        rec, user_id, _parse_ids(reacted_artist_ids), _parse_ids(reacted_track_ids)
    )

    track_ids: list[int] = []
    source = profile.source if profile is not None else None
    if profile is not None:
        track_ids = rec.recommend_from_profile(profile, exclude=exclude, top_k=top_k)
        if not track_ids:
            source = None

    if not track_ids:
        track_ids = rec.popular_tracks(exclude=exclude, top_k=top_k)
        source = None

    return {"track_ids": track_ids, "source": source or "popular_fallback"}


@app.get("/onboarding")
def onboarding(count: int = Query(5, ge=1, le=20), exclude_track_ids: str | None = None):
    """Cold-start tracks for a brand-new user (Manual.txt section 6):
    `count` tracks from `count` different popular artists."""
    rec = state["rec"]
    track_ids = rec.onboarding_tracks(count=count, exclude=set(_parse_ids(exclude_track_ids)))
    return {"track_ids": track_ids}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT)
