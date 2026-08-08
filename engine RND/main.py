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
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query
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

# The feedback-learning layer lives in a directory whose name contains a space,
# so it cannot be a normal package import. Putting it on sys.path keeps its
# modules importable by bare name, the same way the engine's own modules are.
IMPROVEMENT_DIR = Path(__file__).resolve().parent / "algorithm improvement"
if IMPROVEMENT_DIR.is_dir() and str(IMPROVEMENT_DIR) not in sys.path:
    sys.path.insert(0, str(IMPROVEMENT_DIR))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("engine")

BASE_DIR = Path(__file__).resolve().parent

# Populated by the lifespan handler. `error` stays set if loading failed, and
# every endpoint checks it -- a half-loaded engine should say so, not crash
# per request.
state: dict = {
    "recommender": None,
    "params": None,
    "config": None,
    "error": None,
    "improvement": None,
}


def _start_improvement_layer(recommender, params, config):
    """Attach the feedback-learning layer, or carry on without it.

    Deliberately best-effort. The engine is a complete, working recommender on
    its own; learning is an enhancement layered on top. If the package is
    missing, its state directory is unwritable, or it raises on construction,
    the engine serves unlearned recommendations and says so in /health --
    which is a far better outcome than a restart loop.
    """
    if os.environ.get("ENGINE_LEARN_ENABLED", "").strip().lower() in ("0", "false", "no", "off"):
        log.info("feedback learning disabled by ENGINE_LEARN_ENABLED")
        return None
    try:
        from learner import LearnerConfig
        from service import ImprovementLayer

        state_dir = Path(
            os.environ.get("ENGINE_LEARN_STATE_DIR", IMPROVEMENT_DIR / "state")
        )
        layer = ImprovementLayer(
            recommender=recommender,
            params=params,
            base_config=config,
            state_dir=state_dir,
            learner_config=LearnerConfig.from_env(),
        )
        log.info("feedback learning active, state in %s", state_dir)
        return layer
    except Exception as exc:  # noqa: BLE001 - never block startup on this
        log.warning("feedback learning unavailable (%s); serving without it", exc)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    params_dir = resolve_params_dir(BASE_DIR, os.environ.get("ENGINE_PARAMS_DIR"))
    started = time.perf_counter()
    try:
        params = load_params(params_dir)
        config = load_config(params.manifest.get("serving"))
        recommender = Recommender(params, config)
        state.update(
            recommender=recommender,
            params=params,
            config=config,
            error=None,
            params_dir=str(params_dir),
            improvement=_start_improvement_layer(recommender, params, config),
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
                     params_dir=str(params_dir), improvement=None)
        log.error("engine failed to load artifacts from %s: %s", params_dir, exc)
    yield
    # Snapshot what was learned before the process goes away. The event log
    # survives regardless, so a missed snapshot costs replay time, not data.
    layer = state.get("improvement")
    if layer is not None:
        layer.close()
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
        "learning": _learning_summary(),
    }


def _learning_summary() -> dict:
    """One-line learning status for /health. The full picture is /learning."""
    layer = state.get("improvement")
    if layer is None:
        return {"enabled": False}
    stats = layer.stats
    return {
        "enabled": stats["enabled"],
        "decisions": stats["counters"]["decisions"],
        "outcomes_attributed": stats["counters"]["outcomes_attributed"],
        "attribution_rate": stats["attribution_rate"],
        "users_with_delta": stats["users"]["users_with_delta"],
        "tracks_observed": stats["items"]["tracks_observed"],
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
    layer = state.get("improvement")
    exclude = set(_parse_ids(exclude_track_ids, "exclude_track_ids", limit))
    artist_ids = _parse_ids(reacted_artist_ids, "reacted_artist_ids", limit)
    track_ids = _parse_ids(reacted_track_ids, "reacted_track_ids", limit)

    # Harvest feedback BEFORE choosing this response. These two parameters
    # describe the *previous* track -- whether it played out or was skipped --
    # so folding them in first means this request is decided with the freshest
    # information available. engine_v2 used them to tilt one response and then
    # threw them away; here they are also the primary training signal, which is
    # what lets the loop close with no change to the app (see
    # "algorithm improvement/README.md").
    if layer is not None:
        layer.report_implicit(user_id, implicit_liked_track_id, implicit_disliked_track_id)

    profile = engine.build_profile(user_id, artist_ids, track_ids)

    if profile is not None and (implicit_liked_track_id or implicit_disliked_track_id):
        profile = engine.nudge(profile, implicit_liked_track_id, implicit_disliked_track_id)

    if layer is not None and layer.enabled:
        result, decision = layer.suggest(
            profile, exclude, user_id=user_id, history_size=len(artist_ids) + len(track_ids)
        )
        arm = decision.arm
    else:
        result = engine.suggest_one(profile, exclude=exclude)
        arm = None

    if not result.track_ids:
        raise HTTPException(404, "No tracks available to suggest")

    payload = {
        "track_id": result.track_ids[0],
        "reason": _reason_for(result.source),
        "source": result.source,
        "pool_size": result.pool_size,
    }
    if arm is not None:
        payload["policy"] = arm
    return payload


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
    layer = state.get("improvement")
    exclude = set(_parse_ids(exclude_track_ids, "exclude_track_ids", limit))
    artist_ids = _parse_ids(reacted_artist_ids, "reacted_artist_ids", limit)
    track_ids = _parse_ids(reacted_track_ids, "reacted_track_ids", limit)
    profile = engine.build_profile(user_id, artist_ids, track_ids)

    if layer is not None and layer.enabled:
        result, decision = layer.recommend(
            profile,
            exclude,
            top_k=top_k,
            user_id=user_id,
            history_size=len(artist_ids) + len(track_ids),
        )
        arm = decision.arm
    else:
        result = engine.recommend(profile, exclude=exclude, top_k=top_k)
        arm = None

    payload = {
        "track_ids": result.track_ids,
        "source": result.source,
        "pool_size": result.pool_size,
        "reranked": result.reranked,
    }
    if arm is not None:
        payload["policy"] = arm
    return payload


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


@app.post("/feedback")
def feedback(payload: dict = Body(...)):
    """Report what a listener did with a recommendation.

    ```json
    {"user_id": 123, "track_id": 456, "outcome": "completed"}
    ```

    `outcome` is one of `completed`, `skipped`, `liked`, `disliked`,
    `downloaded`, `ignored`. `strength` may carry a signed reaction_types value
    (-5..+5) when the caller knows it -- the group bot does, the Mini App only
    knows like/dislike.

    **This endpoint is optional.** The learning loop already runs on
    `implicit_liked_track_id` / `implicit_disliked_track_id`, which the app
    sends today. This exists so richer signal -- explicit reactions,
    downloads -- can be adopted without waiting for a retrain, and so an
    integrator can verify attribution immediately: the response says whether
    the outcome was matched to a recommendation this engine actually served.
    """
    _require_engine()  # 503s if the model never loaded
    layer = state.get("improvement")
    if layer is None:
        raise HTTPException(503, "feedback learning is not enabled on this engine")

    outcome = payload.get("outcome") or payload.get("kind")
    track_id = payload.get("track_id")
    if outcome is None or track_id is None:
        raise HTTPException(422, "feedback requires 'track_id' and 'outcome'")

    try:
        track_id = int(track_id)
        user_id = payload.get("user_id")
        user_id = int(user_id) if user_id is not None else None
        strength = payload.get("strength")
        strength = float(strength) if strength is not None else None
    except (TypeError, ValueError):
        raise HTTPException(422, "user_id/track_id must be integers, strength a number") from None

    from events import OUTCOME_KINDS

    if outcome not in OUTCOME_KINDS:
        raise HTTPException(422, f"outcome must be one of {sorted(OUTCOME_KINDS)}")

    return layer.report(
        user_id, track_id, outcome, strength, payload.get("impression_id")
    )


@app.get("/learning")
def learning():
    """What the engine has learned so far, and from how much.

    Exists because a system that changes its own behaviour over time is
    untrustworthy if you cannot see what it currently believes. Reports the
    arm registry, per-arm pull counts and mean rewards, how many users carry a
    learned delta, how many tracks have engagement evidence, and -- the number
    to watch first -- the attribution rate: what share of reported outcomes the
    engine could actually match to a recommendation it made. An attribution
    rate near zero means the loop is not closed, however healthy everything
    else looks.
    """
    layer = state.get("improvement")
    if layer is None:
        return {"enabled": False, "reason": state.get("error") or "learning layer not loaded"}
    return {**layer.stats, "policies": layer.policies}


@app.post("/learning/snapshot")
def learning_snapshot():
    """Force a state snapshot. Snapshots happen automatically every N updates
    and on shutdown; this is for taking one before a deliberate restart."""
    layer = state.get("improvement")
    if layer is None:
        raise HTTPException(503, "feedback learning is not enabled on this engine")
    return {"saved": layer.save()}


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
    layer = state.get("improvement")
    exclude = set(_parse_ids(exclude_track_ids, "exclude_track_ids", limit))
    artist_ids = _parse_ids(reacted_artist_ids, "reacted_artist_ids", limit)
    track_ids = _parse_ids(reacted_track_ids, "reacted_track_ids", limit)
    profile = engine.build_profile(user_id, artist_ids, track_ids)

    if profile is None:
        return {
            "source": SOURCE_POPULAR,
            "profile": None,
            "top_artists": [],
            "track_ids": engine.popular_tracks(exclude, top_k),
        }

    # Run the same path /recommend would, including the learned strategy and
    # the user's delta -- but as a dry run, so an explain call never enters the
    # training data as an impression nobody saw.
    if layer is not None and layer.enabled:
        result, decision = layer.recommend(
            profile,
            exclude,
            top_k=top_k,
            user_id=user_id,
            history_size=len(artist_ids) + len(track_ids),
            dry_run=True,
        )
        scored_profile = layer.personalise(profile, decision)
        cfg = decision.config
        learning = {
            "policy": decision.arm,
            "propensity": round(decision.propensity, 4),
            "personalised": decision.artist_delta is not None,
            "delta_norm": (
                round(float(np.linalg.norm(decision.artist_delta)), 4)
                if decision.artist_delta is not None
                else 0.0
            ),
        }
    else:
        result = engine.recommend(profile, exclude=exclude, top_k=top_k)
        scored_profile, cfg, learning = profile, state["config"], {"policy": None}

    scores = engine._artist_scores(scored_profile.artist_vec, cfg)
    n = min(cfg.n_artist_candidates, len(scores))
    rows = np.argpartition(-scores, n - 1)[:n]
    rows = rows[np.argsort(-scores[rows], kind="stable")]

    return {
        "source": result.source,
        "profile": {
            "has_artist_vector": True,
            "has_track_vector": profile.track_vec is not None,
            "artist_vector_norm": round(float(np.linalg.norm(scored_profile.artist_vec)), 4),
        },
        "learning": learning,
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
