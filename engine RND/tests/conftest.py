"""Shared fixtures.

Every test runs against a hand-built, deliberately awkward miniature dataset
rather than the real 11 MB bundle: it makes each assertion checkable by hand,
and it lets the fixture contain exactly the shapes that break engine_v2 --
an artist with a deep catalogue, a track nobody has reacted to, a track whose
artist is unknown, and a user who exists in the artist model but not the
track model.

`engine_v2` shipped no tests at all, which is how a candidate-collection bug
that silently starves heavy listeners survived into production.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_DIR))

from artifacts import Params  # noqa: E402
from config import ServingConfig  # noqa: E402
from recommender import Recommender  # noqa: E402

# Catalogue layout used by every test:
#
#   artist 10 "deep"     tracks 100..119   (20 tracks, popularity 20..1)
#   artist 20 "shallow"  tracks 200, 201   (popularity 5, 4)
#   artist 30 "quiet"    tracks 300, 301   (301 has NO reactions at all)
#   artist 40 "untrained" -- present in the catalogue, absent from artist_ids
#   track 999            -- artist id -1, unattributed
DEEP, SHALLOW, QUIET, UNTRAINED = 10, 20, 30, 40
DEEP_TRACKS = list(range(100, 120))


@pytest.fixture
def params() -> Params:
    rng = np.random.default_rng(7)
    artist_ids = np.array([DEEP, SHALLOW, QUIET], dtype=np.int64)

    catalogue: list[tuple[int, int]] = [(t, DEEP) for t in DEEP_TRACKS]
    catalogue += [(200, SHALLOW), (201, SHALLOW), (300, QUIET), (301, QUIET)]
    catalogue += [(400, UNTRAINED), (999, -1)]
    catalogue.sort()

    # Track 301 and 400 have no reactions, so no embedding and no popularity.
    scored = [t for t, _ in catalogue if t not in (301, 400, 999)]
    pop = np.array(
        [20 - DEEP_TRACKS.index(t) if t in DEEP_TRACKS else {200: 5, 201: 4, 300: 3}[t]
         for t in scored],
        dtype=np.float32,
    )

    d_artist, d_track = 4, 3
    return Params(
        artist_user_emb=rng.normal(size=(2, d_artist)).astype(np.float32),
        # Artist embeddings chosen so a query of [1,0,0,0] ranks deep > shallow > quiet.
        artist_item_emb=np.array(
            [[1.0, 0.0, 0.0, 0.0], [0.6, 0.5, 0.0, 0.0], [0.2, 0.0, 0.5, 0.0]],
            dtype=np.float32,
        ),
        artist_bias=np.array([0.1, 0.0, -0.1], dtype=np.float32),
        track_user_emb=rng.normal(size=(1, d_track)).astype(np.float32),
        track_item_emb=rng.normal(size=(len(scored), d_track)).astype(np.float32),
        track_pop=pop,
        # user 1 is in both models; user 2 only in the artist model.
        user_ids_artist=np.array([1, 2], dtype=np.int64),
        user_ids_track=np.array([1], dtype=np.int64),
        artist_ids=artist_ids,
        track_ids_scored=np.array(scored, dtype=np.int64),
        catalogue_track_ids=np.array([t for t, _ in catalogue], dtype=np.int64),
        catalogue_artist_ids=np.array([a for _, a in catalogue], dtype=np.int64),
        layout="v3",
        fingerprint="sha256:test",
    )


@pytest.fixture
def config() -> ServingConfig:
    """Small, deterministic settings: no exploration, no popularity prior, so
    a test asserts on ranking logic rather than on tie-breaking noise."""
    return ServingConfig(
        n_artist_candidates=2,
        tracks_per_artist=3,
        top_k_default=5,
        pop_prior_weight=0.0,
        explore_temperature=0.0,
        session_damping=0.0,
        artist_bias_weight=0.0,
        max_tracks_per_artist_in_result=0,
    )


@pytest.fixture
def engine(params, config) -> Recommender:
    return Recommender(params, config)


@pytest.fixture
def deep_profile(engine):
    """A profile pointing straight at the deep artist."""
    from recommender import UserProfile

    return UserProfile(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), None, "trained_embedding")
