"""Regression tests for the serving-path fixes.

Each test names the engine_v2 behaviour it exists to prevent coming back.
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from recommender import Recommender, UserProfile
from tests.conftest import DEEP, DEEP_TRACKS, SHALLOW


def _artist_of(engine, track_ids):
    return [engine.params.track_artist[int(t)] for t in track_ids]


class TestCandidateCollection:
    def test_exclusion_applied_before_the_per_artist_cap(self, engine):
        """[FIX 1] engine_v2 truncated each artist's list to `tracks_per_artist`
        and *then* removed excluded tracks, so a user who had heard an artist's
        top 3 got nothing from that artist -- even with 17 unheard tracks left."""
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")
        heard = set(DEEP_TRACKS[:3])  # exactly the cap

        result = engine.recommend(profile, exclude=heard, top_k=3)

        assert DEEP in _artist_of(engine, result.track_ids), (
            "the deep artist still has 17 unheard tracks and must contribute candidates"
        )
        assert not heard & set(result.track_ids)

    def test_cap_still_limits_a_single_artist(self, engine):
        """The cap governs candidate collection. (A request larger than the
        whole pool is topped up from global popularity and is not bound by
        it -- covered separately below.)"""
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")
        result = engine.recommend(profile, exclude=set(), top_k=5)
        from_deep = [t for t in result.track_ids if engine.params.track_artist[t] == DEEP]
        assert len(from_deep) <= engine.config.tracks_per_artist

    def test_short_pool_is_topped_up_rather_than_returned_short(self, engine):
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")
        result = engine.recommend(profile, exclude=set(), top_k=12)
        assert len(result.track_ids) == 12
        assert len(set(result.track_ids)) == 12

    def test_unscored_tracks_are_reachable(self, params, config):
        """[FIX 6] Track 301 has no reactions, so engine_v2 skipped it while
        building its artist->tracks index and could never return it -- no
        matter what the models thought of it."""
        assert 301 not in params.track_row, "fixture invariant: 301 has no embedding"
        engine = Recommender(params, replace(config, n_artist_candidates=1))
        profile = UserProfile(np.array([0, 0, 1, 0], np.float32), None, "trained_embedding")
        result = engine.recommend(profile, exclude={300}, top_k=1)
        assert result.track_ids == [301]

    def test_unscored_tracks_can_be_switched_off(self, params, config):
        engine = Recommender(
            params, replace(config, include_unscored_tracks=False, n_artist_candidates=1)
        )
        profile = UserProfile(np.array([0, 0, 1, 0], np.float32), None, "trained_embedding")
        result = engine.recommend(profile, exclude={300}, top_k=1)
        assert 301 not in result.track_ids

    def test_unattributed_track_is_never_a_candidate(self, engine):
        """Track 999 has artist -1: it cannot be attributed, so no artist can
        propose it. It stays reachable only through the popularity fallback."""
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")
        result = engine.recommend(profile, exclude=set(), top_k=20)
        assert 999 not in result.track_ids


class TestWidening:
    def test_pool_widens_instead_of_giving_up(self, params, config):
        """[FIX 2] Manual.txt section 5 prescribes widening x1/x2/x5/x10 before
        falling back to global popularity. engine_v2's code never did."""
        engine = Recommender(params, replace(config, n_artist_candidates=1, tracks_per_artist=2))
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")

        # Exhaust the single top artist entirely.
        result = engine.recommend(profile, exclude=set(DEEP_TRACKS), top_k=2)

        assert result.source == "trained_embedding", "must not collapse to popular_fallback"
        assert result.widen_steps > 0
        assert set(_artist_of(engine, result.track_ids)) <= {SHALLOW, 30}

    def test_falls_back_to_popularity_when_everything_is_excluded(self, engine, params):
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")
        everything = {int(t) for t in params.catalogue_track_ids}
        result = engine.recommend(profile, exclude=everything, top_k=5)
        assert result.source == "popular_fallback"
        assert result.track_ids == []


class TestRanking:
    def test_candidates_without_an_embedding_survive_reranking(self, engine, params):
        """[FIX 5] engine_v2 dropped any candidate missing from the track model,
        shrinking the pool silently -- sometimes below the requested top_k."""
        track_vec = np.ones(params.track_item_emb.shape[1], dtype=np.float32)
        profile = UserProfile(np.array([0, 0, 1, 0], np.float32), track_vec, "trained_embedding")
        result = engine.recommend(profile, exclude=set(), top_k=5)
        assert {300, 301} <= set(result.track_ids)

    def test_artist_bias_changes_the_shortlist_when_enabled(self, params, config):
        """[FIX 3] The bias is part of the trained scoring function. It has to
        actually reach the score, or exporting it was pointless."""
        neutral = np.zeros(params.artist_item_emb.shape[1], dtype=np.float32)
        without = Recommender(params, replace(config, artist_bias_weight=0.0))
        with_bias = Recommender(params, replace(config, artist_bias_weight=1.0))
        assert np.allclose(without._artist_scores(neutral), 0.0)
        assert np.allclose(with_bias._artist_scores(neutral), params.artist_bias)

    def test_diversity_cap_limits_one_artist_per_response(self, params, config):
        """[FIX 7] engine_v2's own notebook output shows a user handed five
        consecutive Eminem tracks."""
        engine = Recommender(
            params, replace(config, max_tracks_per_artist_in_result=2, tracks_per_artist=10)
        )
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")
        result = engine.recommend(profile, exclude=set(), top_k=4)
        from_deep = [t for t in result.track_ids if engine.params.track_artist[t] == DEEP]
        assert len(from_deep) <= 2

    def test_diversity_cap_relaxes_rather_than_returning_a_short_list(self, params, config):
        """A cap that produces three tracks when ten were asked for is worse
        than a cap that bends."""
        engine = Recommender(
            params, replace(config, max_tracks_per_artist_in_result=1, tracks_per_artist=10)
        )
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")
        result = engine.recommend(profile, exclude=set(), top_k=8)
        assert len(result.track_ids) == 8

    def test_session_damping_rotates_artists(self, params, config):
        """Serving one track at a time, the only diversity signal available is
        the caller's exclude list."""
        engine = Recommender(params, replace(config, session_damping=2.0))
        profile = UserProfile(np.array([1.0, 0.9, 0.0, 0.0], np.float32), None, "trained_embedding")

        undamped = Recommender(params, replace(config, session_damping=0.0))
        heard = set(DEEP_TRACKS[:6])
        damped_pick = engine.recommend(profile, exclude=heard, top_k=1).track_ids[0]
        plain_pick = undamped.recommend(profile, exclude=heard, top_k=1).track_ids[0]

        assert engine.params.track_artist[plain_pick] == DEEP
        assert engine.params.track_artist[damped_pick] == SHALLOW


class TestProfiles:
    def test_known_user_gets_both_vectors(self, engine):
        profile = engine.profile_from_user_id(1)
        assert profile is not None and profile.track_vec is not None

    def test_user_missing_from_track_model_still_works(self, engine):
        profile = engine.profile_from_user_id(2)
        assert profile is not None and profile.track_vec is None

    def test_unknown_user_returns_none(self, engine):
        assert engine.profile_from_user_id(9999) is None

    def test_live_reactions_move_a_known_users_profile(self, engine):
        """[FIX 8] engine_v2 returned the trained vector and discarded the
        reacted_* parameters entirely, freezing profiles between retrains."""
        trained = engine.profile_from_user_id(1)
        blended = engine.build_profile(user_id=1, reacted_artist_ids=[SHALLOW])
        assert blended.source == "blended_profile"
        assert not np.allclose(trained.artist_vec, blended.artist_vec)

    def test_fresh_signal_weight_zero_restores_v2_behaviour(self, params, config):
        engine = Recommender(params, replace(config, fresh_signal_weight=0.0))
        trained = engine.profile_from_user_id(1)
        blended = engine.build_profile(user_id=1, reacted_artist_ids=[SHALLOW])
        assert np.allclose(trained.artist_vec, blended.artist_vec)

    def test_cold_start_profile_is_scaled_to_trained_norm(self, engine, params):
        """[FIX 9] Otherwise cold and warm users produce scores on different
        scales and the popularity prior means different things for each."""
        profile = engine.profile_from_artists([DEEP, SHALLOW])
        assert profile is not None
        assert np.linalg.norm(profile.artist_vec) == pytest.approx(params.mean_user_norm, rel=1e-5)

    def test_cold_start_from_tracks_resolves_artists(self, engine):
        profile = engine.build_profile(reacted_track_ids=[DEEP_TRACKS[0]])
        assert profile is not None and profile.source == "reacted_tracks"

    def test_unknown_ids_do_not_produce_a_profile(self, engine):
        assert engine.build_profile(user_id=9999, reacted_artist_ids=[123456]) is None


class TestNudge:
    def test_like_moves_toward_the_artist(self, engine):
        base = UserProfile(np.array([0, 1.0, 0, 0], np.float32), None, "trained_embedding")
        nudged = engine.nudge(base, liked_track_id=DEEP_TRACKS[0])
        deep_vec = engine.params.artist_item_emb[engine.params.artist_row[DEEP]]
        assert float(nudged.artist_vec @ deep_vec) > float(base.artist_vec @ deep_vec)

    def test_dislike_removes_only_the_disliked_direction(self, engine):
        """engine_v2's `(1-a)*v - a*e` shrank the whole vector on every dislike.
        Projecting the component out leaves the orthogonal taste intact."""
        base = UserProfile(np.array([1.0, 0.0, 0.0, 2.0], np.float32), None, "trained_embedding")
        nudged = engine.nudge(base, disliked_track_id=DEEP_TRACKS[0])
        deep_vec = engine.params.artist_item_emb[engine.params.artist_row[DEEP]]

        assert float(nudged.artist_vec @ deep_vec) < float(base.artist_vec @ deep_vec)
        # The 4th dimension is orthogonal to the deep artist and must survive.
        assert nudged.artist_vec[3] == pytest.approx(base.artist_vec[3])

    def test_nudge_on_unknown_track_is_a_no_op(self, engine):
        base = UserProfile(np.array([1.0, 0, 0, 0], np.float32), None, "trained_embedding")
        assert np.allclose(engine.nudge(base, liked_track_id=424242).artist_vec, base.artist_vec)


class TestOnboarding:
    def test_returns_distinct_artists(self, engine):
        tracks = engine.onboarding_tracks(count=3)
        artists = _artist_of(engine, tracks)
        assert len(artists) == len(set(artists))

    def test_respects_exclusions(self, engine):
        first = engine.onboarding_tracks(count=1)[0]
        assert first not in engine.onboarding_tracks(count=2, exclude={first})

    def test_never_returns_more_than_asked(self, engine):
        assert len(engine.onboarding_tracks(count=2)) == 2

    def test_returns_a_short_list_rather_than_repeating_an_artist(self, engine):
        """Only three artists exist in the fixture, so a request for five
        onboarding tracks cannot be satisfied with five different artists."""
        tracks = engine.onboarding_tracks(count=5)
        artists = _artist_of(engine, tracks)
        assert len(artists) == len(set(artists)) <= 3


class TestExploration:
    def test_temperature_zero_is_deterministic(self, params, config):
        engine = Recommender(params, replace(config, explore_temperature=0.0))
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")
        picks = {engine.suggest_one(profile).track_ids[0] for _ in range(5)}
        assert len(picks) == 1

    def test_temperature_above_zero_explores(self, params, config):
        engine = Recommender(params, replace(config, explore_temperature=5.0))
        profile = UserProfile(np.array([1, 0, 0, 0], np.float32), None, "trained_embedding")
        rng = np.random.default_rng(0)
        picks = {engine.suggest_one(profile, rng=rng).track_ids[0] for _ in range(30)}
        assert len(picks) > 1

    def test_suggest_one_returns_exactly_one(self, engine, deep_profile):
        assert len(engine.suggest_one(deep_profile).track_ids) == 1


class TestPopularFallback:
    def test_no_profile_returns_popular_tracks(self, engine):
        result = engine.recommend(None, top_k=3)
        assert result.source == "popular_fallback"
        assert result.track_ids == DEEP_TRACKS[:3]  # popularity 20, 19, 18

    def test_popular_respects_exclusions(self, engine):
        assert DEEP_TRACKS[0] not in engine.popular_tracks({DEEP_TRACKS[0]}, top_k=3)
