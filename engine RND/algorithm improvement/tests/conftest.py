"""Fixtures for the learning layer's tests.

Learning is tested against the engine's own miniature dataset -- an artist with
a deep catalogue, a track nobody has reacted to, a track with no artist, and a
user missing from the track model -- so the awkward cases are covered by both
suites. Those fixtures are shared from the root `conftest.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ENGINE_DIR = Path(__file__).resolve().parent.parent.parent
IMPROVEMENT_DIR = ENGINE_DIR / "algorithm improvement"
for path in (str(ENGINE_DIR), str(IMPROVEMENT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

# `params`, `config` and `engine` come from the root conftest, which shares
# them with both test directories -- see the note there.
from learner import Learner, LearnerConfig  # noqa: E402
from service import ImprovementLayer  # noqa: E402


@pytest.fixture
def learner_config() -> LearnerConfig:
    """Deterministic settings: no exploration slice, so a test asserts on the
    learning rules rather than on which arm a coin flip produced. Individual
    tests that need exploration opt into it."""
    return LearnerConfig(
        enabled=True,
        exploration_share=0.0,
        user_delta_enabled=True,
        item_signal_weight=0.25,
        snapshot_every=10**9,  # tests snapshot explicitly
    )


@pytest.fixture
def learner(params, config, learner_config, tmp_path) -> Learner:
    return Learner(
        params=params, base_config=config, state_dir=tmp_path, config=learner_config
    )


@pytest.fixture
def layer(engine, params, config, learner_config, tmp_path) -> ImprovementLayer:
    return ImprovementLayer(
        recommender=engine,
        params=params,
        base_config=config,
        state_dir=tmp_path,
        learner_config=learner_config,
    )
