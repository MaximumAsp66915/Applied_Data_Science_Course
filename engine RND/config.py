"""Serving configuration for the R&D recommendation engine.

Three layers, lowest priority first:

1. the defaults in `ServingConfig` below,
2. the ``serving`` block of the parameter bundle's ``bundle.json`` (so a
   retrain can ship the settings it was actually tuned for),
3. ``ENGINE_*`` environment variables (so the server can be re-tuned
   without a redeploy of the model files).

`engine_v2` had none of this: its knobs lived in three places that
disagreed with each other -- ``Manual.txt`` said 5 artists / 1 track each,
``Summary.md`` said 15 / 10, and the ``ensemble_config.json`` actually
shipped in ``model_params/`` said 20 / 10 -- with no way to tell which one
the running process was using. Here there is exactly one resolution order,
and ``GET /health`` reports the values in force.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, fields


def _env_name(field_name: str) -> str:
    return f"ENGINE_{field_name.upper()}"


@dataclass(frozen=True)
class ServingConfig:
    # -- stage 1: artist ranking -------------------------------------------
    n_artist_candidates: int = 20
    """How many artists the artist model shortlists per request."""

    artist_bias_weight: float = 0.0
    """Weight on the trained per-artist bias in the stage-1 score.

    The artist model was trained as
    ``score = user . artist + user_bias + artist_bias``, so scoring with the
    dot product alone -- which is all engine_v2 could do, since the bias was
    never exported to ``.npy`` -- optimises a different function than the one
    that was fitted. This engine can now use it: 1.0 reproduces training.

    It defaults to **off** anyway, on measured evidence. ``artist_bias`` is
    essentially a learned popularity term (std 0.30, range -0.80..+1.42), and
    turning it on costs real diversity: over a 150-user simulation, catalogue
    coverage falls from 8.2% to 6.3% and the exposure Gini rises from 0.41 to
    0.51 (``tools/benchmark.py``). Since no leakage-free accuracy evaluation
    exists yet to weigh against that cost, the default is the behaviour that
    does not regress against engine_v2. Set it to 1.0 once there are numbers
    to justify it."""

    widen_factors: tuple[int, ...] = (1, 2, 4, 8)
    """Progressive widening of the artist shortlist when the candidate pool
    comes up empty, before giving up and falling back to global popularity.
    Documented in engine_v2's ``Manual.txt`` section 5, never implemented in
    its ``recommender.py``."""

    # -- stage 2: candidate collection and track re-ranking ----------------
    tracks_per_artist: int = 10
    """Cap on candidates contributed by each shortlisted artist, applied
    *after* removing excluded tracks (engine_v2 applied it before, which
    silently starved heavy listeners -- see ANALYSIS.md, finding S-2)."""

    include_unscored_tracks: bool = True
    """Allow tracks with no positive reactions yet into the candidate pool.

    engine_v2 dropped any track missing from ``track_pop``, which made 2,410
    of 14,843 tracks (16%) permanently unrecommendable no matter what the
    models thought of them."""

    pop_prior_weight: float = 0.10
    """Weight of a log-popularity prior blended into the final track score.

    The median track has 4 positive reactions and 17% have exactly one, so the
    track model's embedding for a tail item is close to noise. A small
    popularity prior on top of the standardised model score is cheap variance
    reduction. Kept deliberately small -- it is a tie-breaker, not a ranker --
    and measurably costs about 0.3 points of catalogue coverage. 0.0 turns it
    off."""

    max_tracks_per_artist_in_result: int = 2
    """Diversity cap on the returned list. Without it the ensemble happily
    returns five tracks by the same artist -- visible in engine_v2's own
    notebook output, where one user's five picks were all Eminem.

    Note this only bites when a response contains several tracks. The
    ``/suggest`` endpoint returns one at a time, so session-level repetition
    is handled by ``session_damping`` instead."""

    session_damping: float = 0.6
    """Stage-1 penalty on artists already well represented in the caller's
    ``exclude_track_ids``.

    The engine is stateless, but ``exclude_track_ids`` is a usable proxy for
    "what this user has already been served": an artist with eight excluded
    tracks has had its turn. The penalty is
    ``session_damping * log1p(excluded tracks by that artist)``, which leaves
    a favourite artist ranked highly while stopping a single deep catalogue
    from monopolising a whole listening session. 0.0 disables it."""

    top_k_default: int = 10

    # -- profile construction ----------------------------------------------
    fresh_signal_weight: float = 0.35
    """How much a request's live ``reacted_artist_ids``/``reacted_track_ids``
    move a *known* user's trained vector.

    engine_v2 ignored live signal entirely whenever ``user_id`` was known, so
    a user's profile was frozen between weekly retrains -- even though
    ``Manual.txt`` section 7 explicitly prescribes recomputing it per request.
    0.0 restores engine_v2's behaviour."""

    nudge_weight: float = 0.35
    """Per-request implicit-feedback nudge (played-to-end / skipped)."""

    scale_cold_start_profile: bool = True
    """Rescale a centroid-built profile to the average norm of the trained
    user vectors, so cold-start and trained users produce comparable scores."""

    # -- request handling ---------------------------------------------------
    max_top_k: int = 50
    max_ids_per_param: int = 2000
    """Hard cap on how many ids a single query parameter may carry, so a
    pathological ``exclude_track_ids`` can't turn into an unbounded parse."""

    explore_temperature: float = 3.0
    """0.0 = always return the top-ranked track from ``/suggest``. Above 0,
    sample from a softmax over rank within the ranked list, so a user who
    sends the same request twice is not locked into the same answer forever
    -- engine_v2's ``/suggest`` was fully deterministic, and a caller that
    passed no ``exclude_track_ids`` got the same track every time.

    At 3.0 the top-ranked track still wins roughly a third of the time while
    the rest of the top ten stays reachable."""

    def merged(self, **overrides) -> "ServingConfig":
        clean = {k: v for k, v in overrides.items() if v is not None}
        return ServingConfig(**{**asdict(self), **clean})

    def as_dict(self) -> dict:
        return asdict(self)


def _coerce(raw: str, template):
    if isinstance(template, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(template, int):
        return int(raw)
    if isinstance(template, float):
        return float(raw)
    if isinstance(template, tuple):
        return tuple(int(x) for x in raw.replace(",", " ").split())
    return raw


def load_config(bundle_serving: dict | None = None) -> ServingConfig:
    """Resolve defaults <- bundle.json's ``serving`` block <- ``ENGINE_*`` env."""
    config = ServingConfig()
    known = {f.name: getattr(config, f.name) for f in fields(ServingConfig)}

    if bundle_serving:
        config = config.merged(**{k: v for k, v in bundle_serving.items() if k in known})

    env_overrides = {}
    for name, template in known.items():
        raw = os.environ.get(_env_name(name))
        if raw is not None and raw != "":
            env_overrides[name] = _coerce(raw, template)
    return config.merged(**env_overrides)


# Host/port keep engine_v2's names and defaults so the systemd unit, the
# start script and app/webapp/engine_client.py all keep working unchanged.
HOST = os.environ.get("ENGINE_HOST", "127.0.0.1")
PORT = int(os.environ.get("ENGINE_PORT", "8100"))
