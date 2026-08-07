"""The evaluation protocol itself.

Metrics that are wrong are worse than no metrics: engine_v2 published a
Recall@1 of 0.038 and read it as "the recommended track is a real liked track
7.6% of the time", which the number does not say. These tests pin down what
each function actually computes, on inputs small enough to verify by hand.
"""
from __future__ import annotations

import pytest

from evaluation import (
    Split,
    evaluate_rankings,
    gini,
    hit_rate_at_k,
    ndcg_at_k,
    popularity_from,
    precision_at_k,
    recall_at_k,
    user_stratified_split,
)


class TestSplit:
    def test_every_user_keeps_training_data(self):
        """engine_v2's global random mask could put a user's entire history in
        test, leaving an untrained embedding to be evaluated as if it were
        warm."""
        interactions = [(u, i) for u in range(30) for i in range(5)]
        split = user_stratified_split(interactions, test_fraction=0.5, seed=1)
        for user in range(30):
            assert split.train_by_user.get(user), f"user {user} has no training items"

    def test_users_with_a_single_interaction_stay_in_train(self):
        split = user_stratified_split([(1, 10)], test_fraction=0.5, seed=1)
        assert split.train == [(1, 10)]
        assert split.test == []

    def test_split_is_a_partition(self):
        interactions = [(u, i) for u in range(10) for i in range(7)]
        split = user_stratified_split(interactions, test_fraction=0.3, seed=2)
        assert set(split.train) | set(split.test) == set(interactions)
        assert not set(split.train) & set(split.test)

    def test_split_is_reproducible(self):
        interactions = [(u, i) for u in range(10) for i in range(7)]
        a = user_stratified_split(interactions, seed=5)
        b = user_stratified_split(interactions, seed=5)
        assert a.test == b.test

    def test_invalid_fraction_is_rejected(self):
        with pytest.raises(ValueError):
            user_stratified_split([(1, 1)], test_fraction=1.5)


class TestPopularity:
    def test_counts_only_what_it_is_given(self):
        """The leakage fix in one line: popularity must come from train only."""
        split = user_stratified_split([(u, 1) for u in range(10)] + [(0, 2)], 0.5, seed=3)
        pop = popularity_from(split.train)
        assert sum(pop.values()) == len(split.train)


class TestMetrics:
    RECOMMENDED = [10, 11, 12, 13, 14]
    RELEVANT = {12, 99}

    def test_recall_is_over_the_relevant_set(self):
        assert recall_at_k(self.RECOMMENDED, self.RELEVANT, 5) == pytest.approx(0.5)

    def test_precision_is_over_k(self):
        assert precision_at_k(self.RECOMMENDED, self.RELEVANT, 5) == pytest.approx(0.2)

    def test_hit_rate_is_binary(self):
        assert hit_rate_at_k(self.RECOMMENDED, self.RELEVANT, 5) == 1.0
        assert hit_rate_at_k(self.RECOMMENDED, self.RELEVANT, 2) == 0.0

    def test_recall_and_hit_rate_differ(self):
        """The distinction Summary.txt collapsed: with one hit out of two
        relevant items, recall is 0.5 while the hit rate is 1.0."""
        assert recall_at_k(self.RECOMMENDED, self.RELEVANT, 5) != hit_rate_at_k(
            self.RECOMMENDED, self.RELEVANT, 5
        )

    def test_ndcg_rewards_earlier_hits(self):
        early = ndcg_at_k([1, 2, 3], {1}, 3)
        late = ndcg_at_k([2, 3, 1], {1}, 3)
        assert early == 1.0
        assert late < early

    def test_metrics_are_zero_without_relevant_items(self):
        assert recall_at_k([1, 2], set(), 2) == 0.0
        assert ndcg_at_k([1, 2], set(), 2) == 0.0


class TestGini:
    def test_uniform_exposure_is_zero(self):
        assert gini([5, 5, 5, 5]) == pytest.approx(0.0)

    def test_winner_takes_all_approaches_one(self):
        assert gini([0, 0, 0, 100]) == pytest.approx(0.75)

    def test_order_does_not_matter(self):
        assert gini([1, 9, 3]) == pytest.approx(gini([9, 3, 1]))

    def test_empty_and_zero_inputs_are_safe(self):
        assert gini([]) == 0.0
        assert gini([0, 0]) == 0.0

    def test_negative_values_are_rejected(self):
        with pytest.raises(ValueError):
            gini([-1, 2])


class TestEvaluateRankings:
    def test_scores_accuracy_and_distribution_together(self):
        split = Split(train=[], test=[(1, 100), (2, 200)])
        rankings = {1: [100, 999], 2: [100, 999]}  # both users get the same head

        result = evaluate_rankings(rankings, split, k=2, catalogue_size=1000)

        assert result.users_evaluated == 2
        assert result.recall == pytest.approx(0.5)  # user 2's 200 was missed
        assert result.catalogue_coverage == pytest.approx(2 / 1000)
        assert result.recommendation_gini == pytest.approx(0.0)  # 100 and 999 both twice

    def test_perfect_recall_with_terrible_coverage_is_visible(self):
        """The failure mode a recall-only evaluation cannot see."""
        split = Split(train=[], test=[(u, 1) for u in range(50)])
        rankings = {u: [1] for u in range(50)}
        result = evaluate_rankings(rankings, split, k=1, catalogue_size=10_000)
        assert result.recall == 1.0
        assert result.catalogue_coverage == pytest.approx(0.0001)

    def test_empty_responses_are_counted(self):
        split = Split(train=[], test=[(1, 5)])
        result = evaluate_rankings({1: []}, split, k=3, catalogue_size=10)
        assert result.empty_responses == 1

    def test_as_dict_labels_k_correctly(self):
        split = Split(train=[], test=[(1, 5)])
        payload = evaluate_rankings({1: [5]}, split, k=3, catalogue_size=10).as_dict()
        assert "recall@3" in payload and "precision@3" in payload
