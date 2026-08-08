"""Tests for the feedback-learning layer.

Grouped by the property being defended rather than by module, because the
properties are what matter: an online learner that is merely "not crashing" can
still be quietly ruining a product. The safety tests -- bounded deltas, exact
attribution, failure isolation -- carry more weight here than the happy paths.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace

import numpy as np
import pytest

from bandit import FEATURE_DIM, EpsilonGreedyBandit, LinUCB, build_context
from events import (
    OUTCOME_COMPLETED,
    OUTCOME_DOWNLOADED,
    OUTCOME_SKIPPED,
    EventLog,
    Impression,
    Outcome,
    PendingImpressions,
    new_impression_id,
)
from item_model import EngagementModel
from learner import Learner, LearnerConfig
from offline_eval import (
    evaluate,
    fixed_policy,
    ips_estimate,
    load_dataset,
    logged_summary,
    replay_estimate,
)
from policies import DEFAULT_POLICY, POLICY_BY_NAME, POLICY_NAMES
from rewards import RewardModel
from user_model import UserDeltaStore
from tests.conftest import DEEP, DEEP_TRACKS, SHALLOW


def _impression(track_id=100, user_id=1, arm="exploit", artist_id=DEEP, propensity=1.0):
    return Impression(
        impression_id=new_impression_id(),
        user_id=user_id,
        track_id=track_id,
        artist_id=artist_id,
        arm=arm,
        propensity=propensity,
        context=[0.0] * FEATURE_DIM,
        source="trained_embedding",
    )


# ---------------------------------------------------------------- event log


class TestEventLog:
    def test_impressions_and_outcomes_round_trip(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl")
        impression = _impression()
        log.append(impression)
        log.append(Outcome(impression.impression_id, OUTCOME_COMPLETED, user_id=1, track_id=100))
        log.close()

        pairs = log.read_pairs()
        assert len(pairs) == 1
        recorded, outcomes = pairs[0]
        assert recorded["track_id"] == 100
        assert [o["kind"] for o in outcomes] == [OUTCOME_COMPLETED]

    def test_impression_with_no_outcome_is_kept(self, tmp_path):
        """Dropping these would bias every estimate upward: a recommendation
        nobody engaged with is a real result, and the most common one."""
        log = EventLog(tmp_path / "events.jsonl")
        log.append(_impression())
        assert log.read_pairs()[0][1] == []

    def test_truncated_final_line_is_skipped_not_fatal(self, tmp_path):
        """The signature of a process killed mid-write, and the reason a
        line-delimited format was chosen over anything with a header."""
        path = tmp_path / "events.jsonl"
        log = EventLog(path)
        log.append(_impression())
        log.close()
        with path.open("a") as handle:
            handle.write('{"event":"impression","truncat')

        assert len(list(log.read())) == 1

    def test_rotation_preserves_history_in_order(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl", max_bytes=800, keep_rotations=2)
        for index in range(40):
            log.append(_impression(track_id=index))
        log.close()

        seen = [e["track_id"] for e in log.read() if e["event"] == "impression"]
        assert seen == sorted(seen), "rotated files must replay oldest-first"
        assert len(seen) > 1

    def test_unknown_outcome_kind_is_rejected_at_construction(self):
        with pytest.raises(ValueError, match="unknown outcome kind"):
            Outcome("abc", "vibed_with_it")

    def test_events_hold_no_personal_data(self, tmp_path):
        """Only internal integer ids and derived numbers. No names, no Telegram
        ids, nothing about what a track is."""
        log = EventLog(tmp_path / "events.jsonl")
        log.append(_impression())
        log.close()
        record = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])
        assert set(record) == {
            "impression_id", "user_id", "track_id", "artist_id", "arm", "propensity",
            "context", "source", "rank", "endpoint", "created_at", "event",
        }
        assert all(not isinstance(v, str) or k in ("impression_id", "arm", "source", "endpoint", "event")
                   for k, v in record.items())


class TestPendingImpressions:
    def test_claim_returns_the_decision_that_served_the_track(self):
        pending = PendingImpressions()
        pending.remember(_impression(track_id=100, arm="discover"))
        assert pending.claim(1, 100)["arm"] == "discover"

    def test_claim_is_once_only(self):
        """A track completed once should be credited once. Otherwise a user
        replaying from history keeps paying reward into the same decision."""
        pending = PendingImpressions()
        pending.remember(_impression(track_id=100))
        assert pending.claim(1, 100) is not None
        assert pending.claim(1, 100) is None

    def test_unknown_track_or_user_claims_nothing(self):
        pending = PendingImpressions()
        pending.remember(_impression(track_id=100, user_id=1))
        assert pending.claim(1, 999) is None
        assert pending.claim(2, 100) is None
        assert pending.claim(None, 100) is None

    def test_per_user_history_is_bounded(self):
        """Unbounded per-user state is a slow leak in a process meant to run
        for weeks."""
        pending = PendingImpressions(per_user=4)
        for track_id in range(20):
            pending.remember(_impression(track_id=track_id))
            time.sleep(0.001)
        assert len(pending) <= 4

    def test_repeat_artist_detection(self):
        pending = PendingImpressions()
        assert pending.is_repeat_artist(1, DEEP) is False
        pending.remember(_impression(track_id=100, artist_id=DEEP))
        assert pending.is_repeat_artist(1, DEEP) is True
        assert pending.is_repeat_artist(1, SHALLOW) is False

    def test_unattributed_artist_is_never_a_repeat(self):
        pending = PendingImpressions()
        pending.remember(_impression(track_id=999, artist_id=-1))
        assert pending.is_repeat_artist(1, -1) is False


# ------------------------------------------------------------------ rewards


class TestRewardModel:
    def test_completed_is_positive_and_skipped_negative(self):
        model = RewardModel()
        assert model.single({"kind": OUTCOME_COMPLETED, "strength": None}) > 0
        assert model.single({"kind": OUTCOME_SKIPPED, "strength": None}) < 0

    def test_skip_is_weaker_evidence_than_completion(self):
        """People skip tracks they like. Treating a skip as symmetric evidence
        would make the engine timid."""
        model = RewardModel()
        assert abs(model.skipped) < abs(model.completed)

    def test_signals_compose_before_clipping(self):
        model = RewardModel()
        both = model.score([
            {"kind": OUTCOME_COMPLETED, "strength": None},
            {"kind": "liked", "strength": None},
        ])
        only_completed = model.score([{"kind": OUTCOME_COMPLETED, "strength": None}])
        assert both > only_completed
        assert both <= 1.0

    def test_reward_is_always_bounded(self):
        model = RewardModel()
        outcomes = [{"kind": OUTCOME_DOWNLOADED, "strength": None}] * 10
        assert model.score(outcomes) == 1.0
        assert model.score([{"kind": OUTCOME_SKIPPED, "strength": None}] * 10) == -1.0

    def test_emoji_strength_is_used_when_present(self):
        """The group bot knows the full reaction_types scale; a fire emoji and a
        shrug are not the same event."""
        model = RewardModel()
        fire = model.single({"kind": "liked", "strength": 4.5})
        mild = model.single({"kind": "liked", "strength": 2.0})
        assert fire > mild > 0

    def test_no_outcomes_is_zero_not_negative(self):
        """Absence of signal is not negative signal."""
        assert RewardModel().score([]) == 0.0


# ------------------------------------------------------------------- bandit


class TestContext:
    def test_every_feature_is_bounded(self):
        """LinUCB's confidence term scales with the feature norm, so one
        unbounded feature would disable exploration everywhere else."""
        x = build_context(
            history_size=10**6,
            session_depth=10**6,
            catalogue_size=10,
            recent_reward=99.0,
            artist_concentration=99.0,
            repeat_affinity=-99.0,
        )
        assert x.shape == (FEATURE_DIM,)
        assert np.all(np.abs(x) <= 1.0)

    def test_source_is_encoded_distinguishably(self):
        trained = build_context(source="trained_embedding")
        cold = build_context(source="popular_fallback")
        assert not np.array_equal(trained, cold)


class TestLinUCB:
    def test_learns_which_arm_pays(self):
        bandit = LinUCB(["good", "bad"], dim=2, exploration_share=0.0,
                        trust_learned_policy=True, min_pulls_to_trust=1,
                        deviation_margin=0.0, default_arm="bad")
        x = np.array([1.0, 0.0])
        for _ in range(60):
            bandit.update("good", x, 1.0)
            bandit.update("bad", x, -1.0)
        assert bandit.select(x)[0] == "good"

    def test_shadow_mode_serves_the_incumbent(self):
        """The default posture: train from day one, do not steer traffic."""
        bandit = LinUCB(list(POLICY_NAMES), exploration_share=0.0, default_arm=DEFAULT_POLICY)
        x = build_context(source="trained_embedding")
        for _ in range(500):
            bandit.update("discover", x, 1.0)
        assert bandit.trust_learned_policy is False
        assert bandit.select(x)[0] == DEFAULT_POLICY

    def test_deviation_requires_enough_observations(self):
        bandit = LinUCB(
            list(POLICY_NAMES), exploration_share=0.0, default_arm=DEFAULT_POLICY,
            trust_learned_policy=True, min_pulls_to_trust=50, deviation_margin=0.01,
        )
        x = build_context(source="trained_embedding")
        for _ in range(10):  # below the threshold
            bandit.update("discover", x, 1.0)
        assert bandit.select(x)[0] == DEFAULT_POLICY

        for _ in range(60):  # now above it
            bandit.update("discover", x, 1.0)
        assert bandit.select(x)[0] == "discover"

    def test_deviation_requires_a_margin(self):
        """Acting on a near-zero difference is acting on noise -- which measured
        as an actual regression, not a theoretical one."""
        bandit = LinUCB(
            ["a", "b"], dim=2, exploration_share=0.0, default_arm="a",
            trust_learned_policy=True, min_pulls_to_trust=1, deviation_margin=0.5,
        )
        x = np.array([1.0, 0.0])
        for _ in range(50):
            bandit.update("a", x, 0.50)
            bandit.update("b", x, 0.52)  # better, but not by the margin
        assert bandit.select(x)[0] == "a"

    def test_exploration_slice_is_uniform_with_honest_propensities(self):
        """Uniform randomisation is what makes the log a valid off-policy
        dataset -- IPS needs to know the probability each arm actually had."""
        bandit = LinUCB(list(POLICY_NAMES), exploration_share=1.0)
        rng = np.random.default_rng(0)
        x = build_context()
        picks = [bandit.select(x, rng=rng) for _ in range(400)]
        arms = {arm for arm, _ in picks}
        propensities = {round(p, 6) for _, p in picks}
        assert arms == set(POLICY_NAMES)
        assert propensities == {round(1.0 / len(POLICY_NAMES), 6)}

    def test_greedy_propensity_accounts_for_the_exploration_slice(self):
        bandit = LinUCB(["a", "b"], dim=2, exploration_share=0.2, default_arm="a")
        rng = np.random.default_rng(1)
        # With share 0.2 over 2 arms, the greedy arm's probability is 0.8 + 0.1.
        for _ in range(50):
            arm, propensity = bandit.select(np.array([1.0, 0.0]), rng=rng)
            assert propensity in (pytest.approx(0.9), pytest.approx(0.1))

    def test_sherman_morrison_matches_a_direct_inverse(self):
        """The incremental update is the hot path; if it drifts from the true
        inverse the confidence intervals become meaningless."""
        bandit = LinUCB(["a"], dim=4, ridge=1.0)
        rng = np.random.default_rng(3)
        contexts = rng.normal(size=(30, 4))
        for x in contexts:
            bandit.update("a", x, float(rng.normal()))
        expected = np.linalg.inv(np.eye(4) + contexts.T @ contexts)
        assert np.allclose(bandit.A_inv[0], expected, atol=1e-8)

    def test_wrong_dimension_update_is_ignored_not_fatal(self):
        bandit = LinUCB(["a"], dim=3)
        bandit.update("a", np.ones(7), 1.0)
        assert bandit.counts[0] == 0

    def test_unknown_arm_update_is_ignored(self):
        bandit = LinUCB(["a"], dim=2)
        bandit.update("nonexistent", np.ones(2), 1.0)
        assert bandit.counts.sum() == 0

    def test_state_survives_a_round_trip(self):
        bandit = LinUCB(list(POLICY_NAMES))
        x = build_context(source="trained_embedding")
        for _ in range(20):
            bandit.update("discover", x, 0.7)
        restored = LinUCB.from_arrays(bandit.to_arrays(), list(POLICY_NAMES))
        assert np.allclose(restored.scores(x), bandit.scores(x))

    def test_a_retired_arm_is_dropped_rather_than_crashing(self):
        """Adding or removing a policy must be a safe deploy, not a state wipe."""
        old = LinUCB(["keep", "retire"], dim=FEATURE_DIM)
        old.update("keep", build_context(), 1.0)
        restored = LinUCB.from_arrays(old.to_arrays(), ["keep", "brand_new"])
        assert restored.arms == ["keep", "brand_new"]
        assert restored.counts[restored._index["keep"]] == 1

    def test_epsilon_greedy_baseline_learns_too(self):
        bandit = EpsilonGreedyBandit(["good", "bad"], epsilon=0.1, seed=0)
        for _ in range(100):
            bandit.update("good", None, 1.0)
            bandit.update("bad", None, 0.0)
        assert bandit.select()[0] == "good"


# --------------------------------------------------------------- user model


class TestUserDeltaStore:
    def make(self, **kwargs):
        return UserDeltaStore(artist_dim=4, track_dim=3, mean_user_norm=1.0, **kwargs)

    def test_positive_reward_moves_toward_the_artist(self):
        store = self.make()
        direction = np.array([1.0, 0.0, 0.0, 0.0])
        store.update(1, 0.8, artist_embedding=direction)
        assert float(store.artist_delta(1) @ direction) > 0

    def test_negative_reward_moves_away(self):
        store = self.make()
        direction = np.array([1.0, 0.0, 0.0, 0.0])
        store.update(1, -0.8, artist_embedding=direction)
        assert float(store.artist_delta(1) @ direction) < 0

    def test_trust_region_is_never_exceeded(self):
        """Without this, a run of bad luck pushes a profile somewhere the base
        embeddings never go and the recommendations become incoherent."""
        store = self.make(learning_rate=5.0, max_norm_ratio=0.5)
        for _ in range(200):
            store.update(1, 1.0, artist_embedding=np.array([1.0, 0.0, 0.0, 0.0]))
        assert float(np.linalg.norm(store.artist_delta(1))) <= 0.5 + 1e-6

    def test_gradient_is_normalised_so_embedding_scale_does_not_matter(self):
        small = self.make()
        large = self.make()
        small.update(1, 1.0, artist_embedding=np.array([0.01, 0, 0, 0]))
        large.update(1, 1.0, artist_embedding=np.array([100.0, 0, 0, 0]))
        assert np.allclose(small.artist_delta(1), large.artist_delta(1))

    def test_delta_decays_over_wall_clock_time(self):
        """A user who disappears for months comes back close to their trained
        profile, with no background job needed to make that happen."""
        store = self.make(half_life_days=7.0)
        store.update(1, 1.0, artist_embedding=np.array([1.0, 0, 0, 0]))
        fresh = float(np.linalg.norm(store.artist_delta(1)))

        store._touched[1] -= 7 * 86400  # one half-life ago
        one_half_life = float(np.linalg.norm(store.artist_delta(1)))
        assert one_half_life == pytest.approx(fresh / 2, rel=1e-6)

        store._touched[1] -= 70 * 86400  # ten more
        assert float(np.linalg.norm(store.artist_delta(1))) < fresh * 0.001

    def test_zero_reward_is_a_no_op(self):
        store = self.make()
        store.update(1, 0.0, artist_embedding=np.ones(4))
        assert store.artist_delta(1) is None

    def test_unknown_user_has_no_delta(self):
        assert self.make().artist_delta(9999) is None
        assert self.make().artist_delta(None) is None

    def test_reward_ema_tracks_satisfaction(self):
        store = self.make()
        for _ in range(5):
            store.update(1, -0.9, artist_embedding=np.ones(4))
        assert store.recent_reward(1) < 0

    def test_repeat_affinity_only_moves_on_repeats(self):
        store = self.make()
        store.update(1, 0.9, artist_embedding=np.ones(4), was_repeat_artist=False)
        assert store.repeat_affinity(1) == 0.0
        store.update(1, 0.9, artist_embedding=np.ones(4), was_repeat_artist=True)
        assert store.repeat_affinity(1) > 0

    def test_a_user_can_be_forgotten(self):
        store = self.make()
        store.update(1, 1.0, artist_embedding=np.ones(4))
        assert store.reset(1) is True
        assert store.artist_delta(1) is None

    def test_state_survives_a_round_trip(self):
        store = self.make()
        store.update(1, 0.9, artist_embedding=np.array([1.0, 0, 0, 0]))
        store.update(2, -0.5, artist_embedding=np.array([0, 1.0, 0, 0]))
        restored = self.make()
        restored.load_arrays(store.to_arrays())
        assert np.allclose(restored.artist_delta(1), store.artist_delta(1))
        assert np.allclose(restored.artist_delta(2), store.artist_delta(2))

    def test_a_dimension_change_invalidates_deltas_rather_than_corrupting(self):
        """A retrain that changes the embedding size makes every delta
        meaningless; starting clean beats serving garbage."""
        store = self.make()
        store.update(1, 1.0, artist_embedding=np.ones(4))
        other = UserDeltaStore(artist_dim=8, track_dim=3)
        other.load_arrays(store.to_arrays())
        assert other.artist_delta(1) is None


# --------------------------------------------------------------- item model


class TestEngagementModel:
    def test_unobserved_track_contributes_nothing(self):
        """An unknown track must not be penalised for being unknown."""
        assert EngagementModel().track_signal(123) == 0.0

    def test_completions_raise_the_signal_and_skips_lower_it(self):
        model = EngagementModel()
        for _ in range(30):
            model.observe(1, DEEP, 0.6)
            model.observe(2, SHALLOW, -0.6)
        assert model.track_signal(1) > 0
        assert model.track_signal(2) < 0

    def test_two_observations_cannot_mint_a_hit(self):
        """The shrinkage that a naive completion-rate average lacks."""
        model = EngagementModel(confidence_floor=8.0)
        model.observe(1, DEEP, 1.0)
        model.observe(1, DEEP, 1.0)
        weak = model.track_signal(1)
        for _ in range(60):
            model.observe(2, DEEP, 1.0)
        assert model.track_signal(2) > weak * 3

    def test_a_zero_reaction_track_can_earn_its_way_up(self):
        """The point of the whole item model: 2,410 tracks have no reactions,
        so live behaviour is the only evidence they can ever accumulate."""
        model = EngagementModel()
        for _ in range(40):
            model.observe(301, 30, 0.6)  # fixture track with no popularity
        assert model.track_signal(301) > 0.1

    def test_evidence_decays(self):
        """Taste in a group chat is not stationary. Without decay, a track that
        was loved in March would outrank one that is loved now, forever."""
        model = EngagementModel(half_life_days=30.0)
        for _ in range(50):
            model.observe(1, DEEP, 1.0)
        fresh = model.track_signal(1)
        assert fresh > 0.1

        model._track[1][2] -= 300 * 86400  # ten half-lives ago
        assert model.track_signal(1) < fresh * 0.01

    def test_vectorised_lookup_matches_scalar(self):
        model = EngagementModel()
        model.observe(1, DEEP, 0.6)
        assert np.allclose(model.track_signals([1, 2]), [model.track_signal(1), 0.0])

    def test_state_survives_a_round_trip(self):
        model = EngagementModel()
        for _ in range(10):
            model.observe(1, DEEP, 0.6)
        restored = EngagementModel()
        restored.load_arrays(model.to_arrays())
        assert restored.track_signal(1) == pytest.approx(model.track_signal(1), abs=1e-6)


# -------------------------------------------------------------- the learner


class TestAttribution:
    def test_outcome_on_a_served_track_is_credited(self, learner):
        decision = learner.decide(user_id=1, source="trained_embedding")
        learner.record_impression(decision, 1, [DEEP_TRACKS[0]], "trained_embedding")
        report = learner.observe(1, DEEP_TRACKS[0], OUTCOME_COMPLETED)
        assert report["attributed"] is True
        assert report["reward"] > 0

    def test_outcome_on_a_track_we_never_served_is_not_credited(self, learner):
        """The user found it through search. Crediting it would teach the engine
        about a decision it never made."""
        report = learner.observe(1, 12345, OUTCOME_COMPLETED)
        assert report["attributed"] is False
        assert learner.bandit.stats["total_updates"] == 0

    def test_the_same_outcome_is_not_credited_twice(self, learner):
        decision = learner.decide(user_id=1, source="trained_embedding")
        learner.record_impression(decision, 1, [DEEP_TRACKS[0]], "trained_embedding")
        assert learner.observe(1, DEEP_TRACKS[0], OUTCOME_COMPLETED)["attributed"]
        assert not learner.observe(1, DEEP_TRACKS[0], OUTCOME_COMPLETED)["attributed"]

    def test_another_users_outcome_is_not_credited(self, learner):
        decision = learner.decide(user_id=1, source="trained_embedding")
        learner.record_impression(decision, 1, [DEEP_TRACKS[0]], "trained_embedding")
        assert not learner.observe(2, DEEP_TRACKS[0], OUTCOME_COMPLETED)["attributed"]

    def test_implicit_hints_close_the_loop_with_no_app_changes(self, learner):
        """The app already sends implicit_liked_track_id / implicit_disliked_
        track_id on /suggest. This is the whole integration story."""
        decision = learner.decide(user_id=1, source="trained_embedding")
        learner.record_impression(decision, 1, [DEEP_TRACKS[0], DEEP_TRACKS[1]], "trained_embedding")

        reports = learner.observe_implicit(1, DEEP_TRACKS[0], DEEP_TRACKS[1])
        assert [r["attributed"] for r in reports] == [True, True]
        assert reports[0]["reward"] > 0 > reports[1]["reward"]

    def test_attribution_rate_is_reported(self, learner):
        decision = learner.decide(user_id=1, source="trained_embedding")
        learner.record_impression(decision, 1, [DEEP_TRACKS[0]], "trained_embedding")
        learner.observe(1, DEEP_TRACKS[0], OUTCOME_COMPLETED)
        learner.observe(1, 999999, OUTCOME_COMPLETED)
        assert learner.stats["attribution_rate"] == pytest.approx(0.5)


class TestLearnerSafety:
    def test_disabled_learner_serves_the_base_config_unchanged(self, params, config, tmp_path):
        learner = Learner(params, config, tmp_path, LearnerConfig(enabled=False))
        decision = learner.decide(user_id=1, source="trained_embedding")
        assert decision.config == config
        assert decision.arm == DEFAULT_POLICY

    def test_a_broken_bandit_does_not_break_the_request(self, learner):
        """Learning is an enhancement to a working recommender, never a
        dependency of one."""
        learner.bandit = None  # simulate an internal failure
        decision = learner.decide(user_id=1, source="trained_embedding")
        assert decision.arm == DEFAULT_POLICY
        assert learner.stats["counters"]["errors"] == 1

    def test_stats_reports_a_broken_component_instead_of_raising(self, learner):
        """/learning is most needed exactly when something has gone wrong."""
        learner.bandit = None
        assert learner.stats["bandit"] == {"error": "unavailable"}

    def test_a_broken_item_model_returns_no_signal_rather_than_raising(self, learner):
        learner.items = None
        assert learner.item_signals([1, 2, 3]) is None

    def test_observe_survives_an_internal_failure(self, learner):
        decision = learner.decide(user_id=1, source="trained_embedding")
        learner.record_impression(decision, 1, [DEEP_TRACKS[0]], "trained_embedding")
        learner.items = None
        report = learner.observe(1, DEEP_TRACKS[0], OUTCOME_COMPLETED)
        assert report["attributed"] is False
        assert report["reason"] == "internal error"


class TestPersistence:
    def test_state_survives_a_restart(self, params, config, learner_config, tmp_path):
        first = Learner(params, config, tmp_path, learner_config)
        decision = first.decide(user_id=1, source="trained_embedding")
        first.record_impression(decision, 1, [DEEP_TRACKS[0]], "trained_embedding")
        first.observe(1, DEEP_TRACKS[0], OUTCOME_COMPLETED)
        before = first.bandit.stats["total_updates"]
        assert first.save() is True
        first.close()

        second = Learner(params, config, tmp_path, learner_config)
        assert second.bandit.stats["total_updates"] == before
        assert second.users.stats["users_with_delta"] == 1

    def test_a_missing_snapshot_is_a_first_start_not_an_error(self, params, config, tmp_path):
        learner = Learner(params, config, tmp_path / "empty", LearnerConfig())
        assert learner.load() is False
        assert learner.stats["counters"]["errors"] == 0

    def test_a_corrupt_snapshot_falls_back_to_fresh_state(self, params, config, tmp_path):
        (tmp_path / "learner_state.npz").write_bytes(b"not an npz file")
        learner = Learner(params, config, tmp_path, LearnerConfig())
        assert learner.bandit.stats["total_updates"] == 0

    def test_snapshots_are_written_atomically(self, params, config, learner_config, tmp_path):
        """A crash mid-snapshot must not leave a truncated file that fails to
        load on the next start."""
        learner = Learner(params, config, tmp_path, learner_config)
        learner.save()
        assert (tmp_path / "learner_state.npz").exists()
        assert not list(tmp_path.glob("*.tmp"))


# --------------------------------------------------- the layer, end to end


class TestImprovementLayer:
    def test_a_suggestion_is_logged_as_an_impression(self, layer):
        profile = layer.recommender.profile_from_user_id(1)
        result, decision = layer.suggest(profile, set(), user_id=1)
        assert result.track_ids
        assert layer.learner.pending.peek(1, result.track_ids[0]) is not None
        assert decision.arm in POLICY_NAMES

    def test_a_dry_run_records_nothing(self, layer):
        """/explain must show what /recommend would do without putting an
        impression nobody saw into the training data."""
        profile = layer.recommender.profile_from_user_id(1)
        result, _ = layer.recommend(profile, set(), top_k=3, user_id=1, dry_run=True)
        assert result.track_ids
        assert len(layer.learner.pending) == 0

    def test_the_full_loop_updates_every_learner(self, layer):
        profile = layer.recommender.profile_from_user_id(1)
        result, _ = layer.suggest(profile, set(), user_id=1)
        report = layer.report(1, result.track_ids[0], OUTCOME_COMPLETED)

        assert report["attributed"] is True
        stats = layer.stats
        assert stats["bandit"]["total_updates"] == 1
        assert stats["users"]["users_with_delta"] == 1
        assert stats["items"]["tracks_observed"] == 1

    def test_personalisation_changes_the_served_profile(self, layer):
        profile = layer.recommender.profile_from_user_id(1)
        for _ in range(10):
            layer.learner.users.update(
                1, 0.9,
                artist_embedding=layer.params.artist_item_emb[layer.params.artist_row[SHALLOW]],
            )
        decision = layer.decide(profile, set(), user_id=1)
        personalised = layer.personalise(profile, decision)
        assert not np.allclose(personalised.artist_vec, profile.artist_vec)

    def test_personalisation_is_a_no_op_without_a_delta(self, layer):
        profile = layer.recommender.profile_from_user_id(1)
        decision = layer.decide(profile, set(), user_id=1)
        assert layer.personalise(profile, decision) is profile

    def test_the_base_embeddings_are_never_modified(self, layer, params):
        """The trained artifacts are read-only. A learning layer that mutates
        them cannot be rolled back."""
        before = params.artist_user_emb.copy()
        profile = layer.recommender.profile_from_user_id(1)
        result, _ = layer.suggest(profile, set(), user_id=1)
        layer.report(1, result.track_ids[0], OUTCOME_COMPLETED)
        assert np.array_equal(params.artist_user_emb, before)

    def test_anonymous_requests_still_get_recommendations(self, layer):
        profile = layer.recommender.profile_from_user_id(1)
        result, _ = layer.suggest(profile, set(), user_id=None)
        assert result.track_ids
        assert len(layer.learner.pending) == 0  # nothing to credit anyone for

    def test_artist_concentration_detects_a_rut(self, layer):
        assert layer._artist_concentration(set()) == 0.0
        assert layer._artist_concentration(set(DEEP_TRACKS[:8])) == pytest.approx(1.0)


# --------------------------------------------------------- offline evaluation


class TestOfflineEvaluation:
    def _log_with_history(self, tmp_path, arms_and_rewards):
        log = EventLog(tmp_path / "events.jsonl")
        for arm, reward, propensity in arms_and_rewards:
            impression = _impression(arm=arm, propensity=propensity)
            log.append(impression)
            kind = OUTCOME_COMPLETED if reward > 0 else OUTCOME_SKIPPED
            log.append(Outcome(impression.impression_id, kind))
        log.close()
        return log

    def test_dataset_keeps_unobserved_impressions(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl")
        log.append(_impression())
        log.close()
        rows = load_dataset(log)
        assert len(rows) == 1 and rows[0]["reward"] == 0.0 and rows[0]["observed"] is False

    def test_replay_scores_a_matching_policy(self, tmp_path):
        log = self._log_with_history(
            tmp_path, [("exploit", 1, 0.5)] * 120 + [("discover", -1, 0.5)] * 120
        )
        rows = load_dataset(log)
        good = replay_estimate(rows, fixed_policy("exploit"), "always-exploit")
        bad = replay_estimate(rows, fixed_policy("discover"), "always-discover")
        assert good.mean_reward > bad.mean_reward
        assert good.events_matched == 120

    def test_replay_warns_on_a_tiny_sample(self, tmp_path):
        log = self._log_with_history(tmp_path, [("exploit", 1, 1.0)] * 5)
        estimate = replay_estimate(load_dataset(log), fixed_policy("exploit"))
        assert any("smoke test" in w for w in estimate.warnings)

    def test_replay_reports_zero_matches_honestly(self, tmp_path):
        log = self._log_with_history(tmp_path, [("exploit", 1, 1.0)] * 10)
        estimate = replay_estimate(load_dataset(log), fixed_policy("deep_cut"))
        assert estimate.events_matched == 0
        assert any("never agreed" in w for w in estimate.warnings)

    def test_ips_refuses_to_pretend_with_deterministic_logs(self, tmp_path):
        """Every propensity 1.0 means the logging policy was greedy, and IPS is
        simply not identifiable. Saying so beats returning a number."""
        log = self._log_with_history(tmp_path, [("exploit", 1, 1.0)] * 50)
        estimate = ips_estimate(load_dataset(log), fixed_policy("exploit"))
        assert any("deterministic" in w for w in estimate.warnings)

    def test_ips_reports_effective_sample_size(self, tmp_path):
        log = self._log_with_history(tmp_path, [("exploit", 1, 0.2)] * 200)
        estimate = ips_estimate(load_dataset(log), fixed_policy("exploit"))
        assert estimate.effective_sample_size == pytest.approx(200, rel=1e-6)

    def test_logged_summary_surfaces_feedback_coverage(self, tmp_path):
        log = EventLog(tmp_path / "events.jsonl")
        observed = _impression(track_id=1)
        log.append(observed)
        log.append(Outcome(observed.impression_id, OUTCOME_COMPLETED))
        log.append(_impression(track_id=2))  # no outcome
        log.close()
        assert logged_summary(load_dataset(log))["feedback_coverage"] == pytest.approx(0.5)

    def test_evaluate_compares_several_candidates(self, tmp_path):
        log = self._log_with_history(
            tmp_path, [("exploit", 1, 0.5)] * 60 + [("popular", -1, 0.5)] * 60
        )
        report = evaluate(
            load_dataset(log),
            {name: fixed_policy(name) for name in ("exploit", "popular")},
        )
        assert report["policies"]["exploit"]["replay"]["mean_reward"] > (
            report["policies"]["popular"]["replay"]["mean_reward"]
        )


# ---------------------------------------------------------------- policies


class TestPolicies:
    def test_every_arm_produces_a_valid_config(self, config):
        for name in POLICY_NAMES:
            applied = POLICY_BY_NAME[name].apply(config)
            assert applied.n_artist_candidates >= 1
            assert applied.tracks_per_artist >= 1
            assert applied.pop_prior_weight >= 0

    def test_arms_are_actually_different(self):
        """Five arms that behave identically would make the bandit a very
        expensive random number generator."""
        signatures = {
            json.dumps(POLICY_BY_NAME[name].overrides, sort_keys=True) for name in POLICY_NAMES
        }
        assert len(signatures) == len(POLICY_NAMES)

    def test_the_default_arm_exists(self):
        assert DEFAULT_POLICY in POLICY_NAMES

    def test_an_unknown_arm_falls_back_to_the_default(self):
        from policies import get_policy

        assert get_policy("no_such_arm").name == DEFAULT_POLICY

    def test_arms_change_what_gets_served(self, params, config):
        """If the arms produced identical rankings there would be nothing to
        learn about."""
        from recommender import Recommender

        engine = Recommender(params, config)
        profile = engine.profile_from_user_id(1)
        rankings = {
            name: tuple(
                engine.recommend(
                    profile, exclude=set(), top_k=5,
                    config=replace(POLICY_BY_NAME[name].apply(config), explore_temperature=0.0),
                ).track_ids
            )
            for name in POLICY_NAMES
        }
        assert len(set(rankings.values())) > 1
