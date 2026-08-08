"""The arms: what the learner is actually allowed to choose between.

A recommender can be improved from feedback at several different levels, and
picking the wrong one is the usual way these projects fail. The three
candidates here were:

1. **Learn the ranking function end to end.** A policy network scoring tracks
   directly. Rejected: roughly 1,300 users and ~85,000 historical positives,
   with maybe a few thousand new feedback events per week. A network with
   enough capacity to rank 14,843 items would memorise the log long before it
   generalised, and there is no way to evaluate it offline without exactly the
   leakage this project has already been burned by (ANALYSIS.md, E-1 to E-4).

2. **Learn per-item scores.** Effectively re-learning the embeddings online.
   Partly done -- `item_model.py` maintains an engagement posterior per track,
   which is where feedback about *items* belongs. But item scores alone cannot
   express "this user wants variety today", which is most of what goes wrong.

3. **Learn which serving strategy to use, per user and per situation.** The
   engine already exposes the knobs that decide how adventurous a response is
   (`config.py`). The failure modes found in the v2 review were not "the model
   ranked the wrong track" so much as "the strategy was wrong for this person
   right now" -- a listener deep in one artist's catalogue being fed more of
   the same, or a cold user handed obscure tail tracks.

This module implements (3). Each arm is a named bundle of config overrides -- a
coherent way to behave -- and the bandit in `bandit.py` learns which one to
use given the context. The action space is five, the feedback is one-step, and
the mapping from context to reward is close to linear in the features chosen,
which is precisely the regime where a contextual bandit is the right tool and
deep RL is not.

Adding an arm is safe: the bandit sizes itself from this registry at
construction and an unknown arm name in a restored snapshot is dropped with a
warning rather than crashing.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from config import ServingConfig


@dataclass(frozen=True)
class Policy:
    """One arm: a name, a rationale, and the config it implies."""

    name: str
    description: str
    overrides: dict = field(default_factory=dict)

    def apply(self, base: ServingConfig) -> ServingConfig:
        return replace(base, **self.overrides)


# The five arms span the axis that actually matters here: how far the engine
# strays from what it already believes about a listener. `exploit` at one end,
# `discover` at the other, with three shapes of middle ground.
POLICIES: tuple[Policy, ...] = (
    Policy(
        name="exploit",
        description=(
            "Trust the model. Narrow artist shortlist, low exploration, mild "
            "popularity prior. The right answer for a user with a well-fitted "
            "profile who is listening steadily."
        ),
        overrides={
            "n_artist_candidates": 12,
            "tracks_per_artist": 10,
            "pop_prior_weight": 0.05,
            "session_damping": 0.4,
            "explore_temperature": 1.5,
            "max_tracks_per_artist_in_result": 3,
        },
    ),
    Policy(
        name="discover",
        description=(
            "Reach past the obvious. Wide shortlist, no popularity prior, "
            "strong session damping, zero-reaction tracks fully in play. This "
            "is the arm that can surface the 2,410 tracks nobody has reacted "
            "to yet -- the ones a discovery product exists for."
        ),
        overrides={
            "n_artist_candidates": 40,
            "tracks_per_artist": 6,
            "pop_prior_weight": 0.0,
            "session_damping": 1.0,
            "explore_temperature": 5.0,
            "max_tracks_per_artist_in_result": 1,
            "include_unscored_tracks": True,
        },
    ),
    Policy(
        name="popular",
        description=(
            "Lean on the crowd. Strong popularity prior and the trained artist "
            "bias switched on. Weak personal signal is worse than no signal, so "
            "for a cold or nearly-cold user this is usually the safest arm."
        ),
        overrides={
            "n_artist_candidates": 25,
            "tracks_per_artist": 10,
            "pop_prior_weight": 0.45,
            "artist_bias_weight": 1.0,
            "session_damping": 0.5,
            "explore_temperature": 3.0,
            "max_tracks_per_artist_in_result": 2,
        },
    ),
    Policy(
        name="diversify",
        description=(
            "Break a rut. One track per artist and heavy damping on artists "
            "the listener has already been served. Aimed at the session where "
            "the same catalogue keeps coming back."
        ),
        overrides={
            "n_artist_candidates": 30,
            "tracks_per_artist": 3,
            "pop_prior_weight": 0.1,
            "session_damping": 1.4,
            "explore_temperature": 4.0,
            "max_tracks_per_artist_in_result": 1,
        },
    ),
    Policy(
        name="deep_cut",
        description=(
            "Go deeper, not wider. Few artists, many tracks each. For the "
            "listener who is working through an artist on purpose -- the "
            "behaviour v2's truncate-then-exclude bug made impossible."
        ),
        overrides={
            "n_artist_candidates": 6,
            "tracks_per_artist": 25,
            "pop_prior_weight": 0.0,
            "session_damping": 0.0,
            "explore_temperature": 2.0,
            "max_tracks_per_artist_in_result": 4,
        },
    ),
)

POLICY_NAMES: tuple[str, ...] = tuple(p.name for p in POLICIES)
POLICY_BY_NAME: dict[str, Policy] = {p.name: p for p in POLICIES}

DEFAULT_POLICY = "exploit"
"""Used when the learner is disabled, still warming up, or asked for an arm it
does not recognise. It is the closest arm to the engine's own defaults, so a
disabled learner changes behaviour as little as possible."""


def get_policy(name: str) -> Policy:
    return POLICY_BY_NAME.get(name, POLICY_BY_NAME[DEFAULT_POLICY])


def describe_policies() -> list[dict]:
    """Arm registry, for GET /health and the docs."""
    return [
        {"name": p.name, "description": p.description, "overrides": p.overrides}
        for p in POLICIES
    ]
