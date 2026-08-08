"""Turning what a listener did into a number the learner can optimise.

This is the most consequential file in the package and the easiest to get
wrong, because every downstream component -- the bandit, the per-user vectors,
the item posteriors -- optimises exactly what is written here and nothing else.
Reward shaping *is* the objective function.

Three principles, each of which rules something out:

**Only credit what we served.** A reward is attached to an impression, never to
a bare track id. If the listener found a track through search and played it to
the end, that says nothing about the engine's decision, and counting it would
reward the engine for the user's own initiative.

**Absence of signal is not negative signal.** A served track with no reported
outcome contributes nothing. It is tempting to treat silence as a skip -- it
would produce far more training data -- but the app reports outcomes only on
some paths, so silence mostly encodes *which screen the user was on*, and
learning from it would fit the instrumentation rather than the listener.

**Bound every contribution.** Reward is clipped to [-1, 1]. One furious user
mashing dislike should move the model about as much as one delighted user can,
and a bounded reward keeps the bandit's confidence intervals meaningful.

The weights below are defaults, not findings. They encode a judgement -- that
finishing a track is good evidence, skipping one is weaker evidence against
(people skip for reasons that have nothing to do with taste), an explicit
reaction is stronger than either, and a download is the strongest signal the
app can produce because it costs the user an action with a consequence. Every
one of them is a constructor argument, and `offline_eval.py` exists so the
question "were these weights any good?" can be answered from logged data
rather than argued about.
"""
from __future__ import annotations

from dataclasses import dataclass

from events import (
    OUTCOME_COMPLETED,
    OUTCOME_DISLIKED,
    OUTCOME_DOWNLOADED,
    OUTCOME_IGNORED,
    OUTCOME_LIKED,
    OUTCOME_SKIPPED,
)

# The reaction_types strength scale runs to +/-5 (Chapter 3, section A.8), so
# dividing by this maps a raw emoji strength onto the reward scale.
MAX_REACTION_STRENGTH = 5.0


@dataclass(frozen=True)
class RewardModel:
    """Maps a set of outcomes for one impression to a scalar in [-1, 1]."""

    completed: float = 0.6
    """Played to its natural end. Good evidence, not conclusive -- a track can
    finish because the listener walked away from their phone."""

    skipped: float = -0.35
    """Deliberately smaller in magnitude than `completed`. Skips are noisy:
    people skip tracks they like because they are not in the mood, because
    they already know it, or because they are hunting for something specific.
    Treating a skip as symmetric evidence would make the engine timid."""

    liked: float = 0.8
    disliked: float = -0.8
    """Used when the caller reports a reaction without a numeric strength --
    which is all the Mini App can do, since its buttons are like/dislike."""

    downloaded: float = 1.0
    """Sending a track to your own chat is the costliest positive action the
    product offers, so it saturates the scale."""

    ignored: float = -0.1
    """Served and never played. Weak, and only ever reported explicitly."""

    reaction_scale: float = 1.0
    """Multiplier on the normalised reaction_types strength, for callers that
    report the full emoji scale rather than a coarse like/dislike."""

    def score(self, outcomes) -> float:
        """Combine every outcome recorded for one impression.

        Contributions add before clipping, so a track that was completed *and*
        liked scores higher than one that was merely completed -- but the sum
        still cannot exceed 1.0. Adding rather than taking the maximum matters:
        two independent positive signals really are stronger evidence than one.
        """
        total = 0.0
        for outcome in outcomes:
            total += self.single(outcome)
        return _clip(total)

    def single(self, outcome) -> float:
        """Reward contribution of one outcome record (dict or Outcome)."""
        kind = outcome["kind"] if isinstance(outcome, dict) else outcome.kind
        strength = outcome.get("strength") if isinstance(outcome, dict) else outcome.strength

        if kind in (OUTCOME_LIKED, OUTCOME_DISLIKED) and strength is not None:
            # A caller that knows the emoji knows more than "positive": a fire
            # emoji (+4.5) and a shrug (-1.5) are not the same event.
            normalised = float(strength) / MAX_REACTION_STRENGTH
            return _clip(normalised * self.reaction_scale)

        return {
            OUTCOME_COMPLETED: self.completed,
            OUTCOME_SKIPPED: self.skipped,
            OUTCOME_LIKED: self.liked,
            OUTCOME_DISLIKED: self.disliked,
            OUTCOME_DOWNLOADED: self.downloaded,
            OUTCOME_IGNORED: self.ignored,
        }.get(kind, 0.0)

    def is_positive(self, reward: float) -> bool:
        return reward > 0.0

    def as_dict(self) -> dict:
        return {
            "completed": self.completed,
            "skipped": self.skipped,
            "liked": self.liked,
            "disliked": self.disliked,
            "downloaded": self.downloaded,
            "ignored": self.ignored,
            "reaction_scale": self.reaction_scale,
        }


def _clip(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


DEFAULT_REWARD_MODEL = RewardModel()
