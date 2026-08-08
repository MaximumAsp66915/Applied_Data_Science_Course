"""The seam between the engine and the learning layer.

`main.py` should not need to know about bandits, deltas or posteriors, and the
learner should not need to know about FastAPI. This module is the whole of what
passes between them: three methods and a stats dictionary.

    layer = ImprovementLayer(recommender, params, config, state_dir)

    result, decision = layer.suggest(profile, exclude, user_id=...)
    layer.report(user_id, track_id, "completed")

The design rule everywhere here is that the engine must still work if this
layer is absent or broken. `main.py` holds an `ImprovementLayer | None`, every
call site tolerates `None`, and every method inside catches its own exceptions
and falls back to unlearned behaviour. Learning is an enhancement to a working
recommender, never a dependency of one.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from artifacts import Params
from config import ServingConfig
from recommender import Recommendation, Recommender, UserProfile
from learner import Decision, Learner, LearnerConfig
from policies import describe_policies

log = logging.getLogger(__name__)


class ImprovementLayer:
    """Feedback-driven policy selection and personalisation around the engine."""

    def __init__(
        self,
        recommender: Recommender,
        params: Params,
        base_config: ServingConfig,
        state_dir: str | Path,
        learner_config: LearnerConfig | None = None,
    ):
        self.recommender = recommender
        self.params = params
        self.base_config = base_config
        self.learner = Learner(
            params=params,
            base_config=base_config,
            state_dir=Path(state_dir),
            config=learner_config or LearnerConfig(),
        )

    @property
    def enabled(self) -> bool:
        return self.learner.config.enabled

    # ----------------------------------------------------------------- serve
    def decide(
        self,
        profile: UserProfile | None,
        exclude: set[int],
        user_id: int | None,
        history_size: int = 0,
        allow_exploration: bool = True,
    ) -> Decision:
        """Choose a strategy and, if there is one, the user's learned delta."""
        return self.learner.decide(
            user_id=user_id,
            source=profile.source if profile else "popular_fallback",
            history_size=history_size,
            session_depth=len(exclude),
            has_track_vector=bool(profile and profile.track_vec is not None),
            artist_concentration=self._artist_concentration(exclude),
            allow_exploration=allow_exploration,
        )

    def personalise(self, profile: UserProfile | None, decision: Decision) -> UserProfile | None:
        """Add the user's learned delta to their profile for this request.

        The trained vectors are never modified. The delta is a separate,
        bounded, decaying correction (see `user_model.py`), so the worst a bad
        run of feedback can do is serve someone as a slightly different -- but
        still coherent -- listener, and the effect fades on its own.
        """
        if profile is None or decision.artist_delta is None:
            return profile
        try:
            artist_vec = profile.artist_vec.astype(np.float32) + decision.artist_delta.astype(
                np.float32
            )
            track_vec = profile.track_vec
            if track_vec is not None and decision.track_delta is not None:
                track_vec = track_vec.astype(np.float32) + decision.track_delta.astype(np.float32)
            return UserProfile(artist_vec, track_vec, profile.source)
        except Exception:  # noqa: BLE001
            log.exception("personalise failed; serving the unmodified profile")
            return profile

    def suggest(
        self,
        profile: UserProfile | None,
        exclude: set[int],
        user_id: int | None = None,
        history_size: int = 0,
        rng: np.random.Generator | None = None,
    ) -> tuple[Recommendation, Decision]:
        """One pick, chosen under a learned strategy and logged as an impression."""
        decision = self.decide(profile, exclude, user_id, history_size)
        result = self.recommender.suggest_one(
            self.personalise(profile, decision),
            exclude=exclude,
            rng=rng,
            config=decision.config,
            item_signals=self.learner.item_signals,
        )
        self.learner.record_impression(
            decision, user_id, result.track_ids, result.source, endpoint="suggest"
        )
        return result, decision

    def recommend(
        self,
        profile: UserProfile | None,
        exclude: set[int],
        top_k: int,
        user_id: int | None = None,
        history_size: int = 0,
        dry_run: bool = False,
    ) -> tuple[Recommendation, Decision]:
        """A ranked batch, same treatment.

        Every returned track is logged as its own impression with its rank, so
        an outcome on the third track credits the third track -- not the batch.

        `dry_run` runs the identical decision path but records nothing. That is
        what `/explain` needs: it must show the ranking `/recommend` would
        actually produce, including the learned strategy and personalisation,
        without putting an impression nobody saw into the training data.
        """
        decision = self.decide(
            profile, exclude, user_id, history_size, allow_exploration=not dry_run
        )
        result = self.recommender.recommend(
            self.personalise(profile, decision),
            exclude=exclude,
            top_k=top_k,
            config=decision.config,
            item_signals=self.learner.item_signals,
        )
        if not dry_run:
            self.learner.record_impression(
                decision, user_id, result.track_ids, result.source, endpoint="recommend"
            )
        return result, decision

    # -------------------------------------------------------------- feedback
    def report(
        self,
        user_id: int | None,
        track_id: int,
        kind: str,
        strength: float | None = None,
        impression_id: str | None = None,
    ) -> dict:
        """Explicit feedback, from `POST /feedback`."""
        return self.learner.observe(user_id, track_id, kind, strength, impression_id)

    def report_implicit(
        self,
        user_id: int | None,
        liked_track_id: int | None,
        disliked_track_id: int | None,
    ) -> list[dict]:
        """Implicit feedback harvested from parameters the app already sends.

        This is what makes the loop close on day one. `/suggest` has always
        accepted `implicit_liked_track_id` and `implicit_disliked_track_id`;
        the webapp fills them from the player's "completed"/"skipped" report
        about the previous track. engine_v2 used them to tilt one response and
        then discarded them. Here they are also the primary training signal.
        """
        return self.learner.observe_implicit(user_id, liked_track_id, disliked_track_id)

    # ------------------------------------------------------------- lifecycle
    def save(self) -> bool:
        return self.learner.save()

    def close(self) -> None:
        self.learner.close()

    # -------------------------------------------------------------- reporting
    @property
    def stats(self) -> dict:
        return self.learner.stats

    @property
    def policies(self) -> list[dict]:
        return describe_policies()

    # --------------------------------------------------------------- helpers
    def _artist_concentration(self, exclude: set[int]) -> float:
        """Share of the exclude set belonging to its single most common artist.

        The "stuck in one artist" detector, and the feature that lets the
        `diversify` arm learn when it is needed. Capped at 200 lookups so a
        listener with a thousand-track history does not pay for the feature on
        every request.
        """
        if not exclude:
            return 0.0
        counts: dict[int, int] = {}
        total = 0
        for track_id in exclude:
            if total >= 200:
                break
            artist = self.params.track_artist.get(int(track_id), -1)
            if artist == -1:
                continue
            counts[artist] = counts.get(artist, 0) + 1
            total += 1
        if total == 0:
            return 0.0
        return max(counts.values()) / total
