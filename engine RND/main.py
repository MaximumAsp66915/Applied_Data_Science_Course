"""SUT Music recommendation engine -- R&D rewrite of the v2 microservice.

Same role, same process model, same loopback-only binding as
``engine_v2/main.py``, and -- deliberately -- the same HTTP contract, so
``app/webapp/engine_client.py`` and everything upstream of it
(``routers/suggestions.py``, ``repository.py``'s ``_suggest_unheard_track``)
work against this process with zero changes. Every response field engine_v2
returned is still returned, with the same name and the same meaning; the new
fields are additive and can be ignored.

What is different is everything behind the endpoints -- see ANALYSIS.md for
the full list, and ``recommender.py``'s module docstring for the nine
serving-path fixes. The API-level changes are:

  * A failed model load no longer produces a process that answers every
    request with a ``KeyError`` traceback. ``/health`` reports ``degraded``
    with the reason, and the recommendation endpoints return 503.
  * Malformed id lists return 422 with a message, not a 500. engine_v2's
    ``int(x)`` on raw query text raised straight through FastAPI.
  * ``/health`` reports the artifact fingerprint, the layout it loaded and
    the serving config actually in force, so it is possible to tell from
    outside which model and which knobs a running process is using.
  * ``/recommend`` and ``/suggest`` accept ``reacted_*`` parameters alongside
    a known ``user_id`` and use both, instead of discarding the live signal.
  * New ``GET /explain`` returns the same ranking plus the intermediate
    stages, which is what makes it possible to debug a bad recommendation
    without attaching a debugger to production.

Binds to 127.0.0.1 only. There is no auth; loopback is the whole security
boundary, exactly as in v1 and v2.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from artifacts import ParamsError, load_params, resolve_params_dir
from config import HOST, PORT, load_config
from recommender import (
    SOURCE_ARTISTS,
    SOURCE_BLENDED,
    SOURCE_POPULAR,
    SOURCE_TRACKS,
    SOURCE_TRAINED,
    Recommender,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("engine")

BASE_DIR = Path(__file__).resolve().parent

# Populated by the lifespan handler. `error` stays set if loading failed, and
# every endpoint checks it -- a half-loaded engine should say so, not crash
# per request.
state: dict = {"recommender": None, "params": None, "config": None, "error": None}


@asynccontextmanager
async def lifespan(app: FastAPI):
    params_dir = resolve_params_dir(BASE_DIR, os.environ.get("ENGINE_PARAMS_DIR"))
    started = time.perf_counter()
    try:
        params = load_params(params_dir)
        config = load_config(params.manifest.get("serving"))
        state.update(
            recommender=Recommender(params, config),
            params=params,
            config=config,
            error=None,
            params_dir=str(params_dir),
            load_seconds=round(time.perf_counter() - started, 3),
        )
        log.info(
            "engine ready in %.3fs from %s (%s, %s)",
            state["load_seconds"],
            params_dir,
            params.layout,
            params.fingerprint,
        )
    except (ParamsError, OSError, ValueError) as exc:
        # Starting anyway is deliberate: systemd would otherwise restart-loop
        # this process forever, and /health can report the real reason to
        # whoever is looking.
        state.update(recommender=None, params=None, config=None, error=str(exc),
                     params_dir=str(params_dir))
        log.error("engine failed to load artifacts from %s: %s", params_dir, exc)
    yield
    state.clear()


app = FastAPI(
    title="SUT Music recommendation engine (R&D)",
    version="3.0.0-rnd",
    lifespan=lifespan,
)


# ----------------------------------------------------------------- helpers


def _require_engine() -> Recommender:
    engine = state.get("recommender")
    if engine is None:
        raise HTTPException(503, f"engine unavailable: {state.get('error') or 'not loaded'}")
    return engine


def _parse_ids(raw: str | None, name: str, limit: int) -> list[int]:
    """Parse a comma-separated id list, rejecting junk with a 422.

    engine_v2 called ``int(x)`` directly on the query string, so
    ``?exclude_track_ids=abc`` came back as an unhandled ``ValueError`` and a
    500 with a traceback in the log.
    """
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) > limit:
        raise HTTPException(422, f"{name}: too many ids ({len(parts)} > {limit})")
    try:
        return [int(p) for p in parts]
    except ValueError:
        raise HTTPException(422, f"{name}: expected a comma-separated list of integers") from None


_REASONS = {
    SOURCE_TRAINED: "Based on your listening history",
    SOURCE_BLENDED: "Based on your listening history",
    SOURCE_ARTISTS: "Because you liked similar artists",
    SOURCE_TRACKS: "Because you liked similar tracks",
}


def _reason_for(source: str) -> str:
    return _REASONS.get(source, "Popular with everyone right now")


def _build(engine: Recommender, user_id, artists_raw, tracks_raw, cfg_limit):
    return engine.build_profile(
        user_id=user_id,
        reacted_artist_ids=_parse_ids(artists_raw, "reacted_artist_ids", cfg_limit),
        reacted_track_ids=_parse_ids(tracks_raw, "reacted_track_ids", cfg_limit),
    )


# --------------------------------------------------------------- endpoints


@app.get("/health")
def health():
    """Liveness plus enough detail to identify what is actually loaded."""
    if state.get("recommender") is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "error": state.get("error") or "not loaded",
                "params_dir": state.get("params_dir"),
            },
        )
    params = state["params"]
    return {
        "status": "ok",
        # engine_v2's three fields, kept verbatim for any existing check.
        "n_users": params.stats["n_users_artist"],
        "n_artists": params.stats["n_artists"],
        "n_tracks": params.stats["n_tracks_total"],
        # Everything below is additive.
        "params_dir": state.get("params_dir"),
        "layout": params.layout,
        "fingerprint": params.fingerprint,
        "load_seconds": state.get("load_seconds"),
        "stats": params.stats,
        "config": state["config"].as_dict(),
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
    """One next-track pick.

    ``{"track_id": int, "reason": str, "source": str}`` -- identical to
    engine_v2, plus a ``pool_size`` field callers may ignore.
    """
    engine = _require_engine()
    limit = state["config"].max_ids_per_param
    exclude = set(_parse_ids(exclude_track_ids, "exclude_track_ids", limit))
    profile = _build(engine, user_id, reacted_artist_ids, reacted_track_ids, limit)

    if profile is not None and (implicit_liked_track_id or implicit_disliked_track_id):
        profile = engine.nudge(profile, implicit_liked_track_id, implicit_disliked_track_id)

    result = engine.suggest_one(profile, exclude=exclude)
    if not result.track_ids:
        raise HTTPException(404, "No tracks available to suggest")

    return {
        "track_id": result.track_ids[0],
        "reason": _reason_for(result.source),
        "source": result.source,
        "pool_size": result.pool_size,
    }


@app.get("/recommend")
def recommend(
    user_id: int | None = None,
    reacted_artist_ids: str | None = None,
    reacted_track_ids: str | None = None,
    exclude_track_ids: str | None = None,
    top_k: int = Query(10, ge=1, le=50),
):
    """A full ranked batch in one round trip.

    ``{"track_ids": [int], "source": str}`` -- identical to engine_v2, plus
    ``pool_size`` / ``reranked``.
    """
    engine = _require_engine()
    limit = state["config"].max_ids_per_param
    exclude = set(_parse_ids(exclude_track_ids, "exclude_track_ids", limit))
    profile = _build(engine, user_id, reacted_artist_ids, reacted_track_ids, limit)

    result = engine.recommend(profile, exclude=exclude, top_k=top_k)
    return {
        "track_ids": result.track_ids,
        "source": result.source,
        "pool_size": result.pool_size,
        "reranked": result.reranked,
    }


@app.get("/onboarding")
def onboarding(
    count: int = Query(5, ge=1, le=20),
    exclude_track_ids: str | None = None,
):
    """Cold-start tracks for a brand-new user: `count` tracks from `count`
    different, mutually dissimilar popular artists."""
    engine = _require_engine()
    limit = state["config"].max_ids_per_param
    exclude = set(_parse_ids(exclude_track_ids, "exclude_track_ids", limit))
    return {"track_ids": engine.onboarding_tracks(count=count, exclude=exclude)}


@app.get("/explain")
def explain(
    user_id: int | None = None,
    reacted_artist_ids: str | None = None,
    reacted_track_ids: str | None = None,
    exclude_track_ids: str | None = None,
    top_k: int = Query(10, ge=1, le=50),
):
    """The same ranking as ``/recommend``, with the intermediate stages.

    New in this version. Answering "why did it pick that?" against engine_v2
    meant reproducing the request in a notebook; here the shortlisted artists,
    their scores, the pool size and how far the search had to widen come back
    with the answer.
    """
    engine = _require_engine()
    params = state["params"]
    limit = state["config"].max_ids_per_param
    exclude = set(_parse_ids(exclude_track_ids, "exclude_track_ids", limit))
    profile = _build(engine, user_id, reacted_artist_ids, reacted_track_ids, limit)

    if profile is None:
        return {
            "source": SOURCE_POPULAR,
            "profile": None,
            "top_artists": [],
            "track_ids": engine.popular_tracks(exclude, top_k),
        }

    scores = engine._artist_scores(profile.artist_vec)
    n = min(state["config"].n_artist_candidates, len(scores))
    rows = np.argpartition(-scores, n - 1)[:n]
    rows = rows[np.argsort(-scores[rows], kind="stable")]
    result = engine.recommend(profile, exclude=exclude, top_k=top_k)

    return {
        "source": result.source,
        "profile": {
            "has_artist_vector": True,
            "has_track_vector": profile.track_vec is not None,
            "artist_vector_norm": round(float(np.linalg.norm(profile.artist_vec)), 4),
        },
        "top_artists": [
            {
                "artist_id": int(params.artist_ids[r]),
                "score": round(float(scores[r]), 4),
                "catalogue_size": int(len(params.artist_tracks.get(int(r), ()))),
            }
            for r in rows
        ],
        "pool_size": result.pool_size,
        "widen_steps": result.widen_steps,
        "reranked": result.reranked,
        "track_ids": result.track_ids,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=HOST, port=PORT)
