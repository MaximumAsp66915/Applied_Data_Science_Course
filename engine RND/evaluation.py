"""Offline evaluation: the split protocol and the metrics.

engine_v2's numbers cannot be taken at face value, for four separate reasons
(ANALYSIS.md, findings E-1 to E-4):

* **Popularity leaked.** ``track_pop`` was computed over the *whole*
  interaction matrix and then used to order candidates during evaluation of a
  held-out split. Every "most popular unseen track" decision was made with
  test data in hand.
* **The artist model saw the test set.** The user-artist matrix was built from
  all track reactions, then 20% of the *track* interactions were held out.
  Since a track's signal is aggregated into its artist, the artist model was
  trained on the artists of the very tracks it was later asked to surface.
* **Model selection ran on the test set.** The 1x26x2 grid sweep picked its
  best configuration by test recall, with no validation split in sight.
* **The reported numbers were mislabelled.** The sweep printed
  ``Precision@10`` while computing ``hits / TOP_K_FINAL`` with
  ``TOP_K_FINAL = 1``; ``Summary.txt`` then read a Recall@1 of 0.038 as "the
  recommended track is a real liked track 7.6% of the time", which does not
  follow from that number at all.

This module supplies the pieces needed to do it properly. It is pure numpy on
purpose: the metrics and the split are the part that has to be trustworthy, so
they are small, dependency-light and unit-tested (``tests/test_evaluation.py``)
rather than buried in a training notebook.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Split:
    """A train/test partition of ``(user_id, item_id)`` pairs."""

    train: list[tuple[int, int]]
    test: list[tuple[int, int]]
    test_by_user: dict[int, set[int]] = field(default_factory=dict)
    train_by_user: dict[int, set[int]] = field(default_factory=dict)

    def __post_init__(self):
        if not self.test_by_user:
            grouped = defaultdict(set)
            for user, item in self.test:
                grouped[user].add(item)
            self.test_by_user = dict(grouped)
        if not self.train_by_user:
            grouped = defaultdict(set)
            for user, item in self.train:
                grouped[user].add(item)
            self.train_by_user = dict(grouped)


def user_stratified_split(
    interactions: list[tuple[int, int]],
    test_fraction: float = 0.2,
    seed: int = 43,
    min_train_items: int = 1,
) -> Split:
    """Hold out a fraction of each user's items, keeping everyone trainable.

    engine_v2 masked interactions with a single global ``np.random.rand``
    draw, which lets a user land entirely in test (evaluated as if warm, with
    an untrained embedding) or entirely in train (silently absent from the
    evaluation). Splitting per user removes both failure modes, and users with
    too few interactions to split are kept wholly in train rather than being
    evaluated on a sample of one.
    """
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be in (0, 1)")

    rng = np.random.default_rng(seed)
    by_user: dict[int, list[int]] = defaultdict(list)
    for user, item in interactions:
        by_user[int(user)].append(int(item))

    train: list[tuple[int, int]] = []
    test: list[tuple[int, int]] = []
    for user in sorted(by_user):
        items = sorted(set(by_user[user]))
        n_test = int(round(len(items) * test_fraction))
        n_test = min(n_test, max(0, len(items) - min_train_items))
        if n_test <= 0:
            train.extend((user, i) for i in items)
            continue
        held = set(rng.choice(items, size=n_test, replace=False).tolist())
        train.extend((user, i) for i in items if i not in held)
        test.extend((user, i) for i in sorted(held))
    return Split(train=train, test=test)


def popularity_from(interactions: list[tuple[int, int]]) -> dict[int, float]:
    """Item popularity computed from one side of a split only.

    The whole point: pass ``split.train``, never the full interaction list.
    """
    counts: dict[int, float] = defaultdict(float)
    for _user, item in interactions:
        counts[int(item)] += 1.0
    return dict(counts)


# ------------------------------------------------------------------ metrics


def recall_at_k(recommended: list[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(recommended[:k]) & relevant) / len(relevant)


def precision_at_k(recommended: list[int], relevant: set[int], k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(recommended[:k]) & relevant) / k


def hit_rate_at_k(recommended: list[int], relevant: set[int], k: int) -> float:
    """1.0 if at least one of the top-k is relevant.

    This is the metric that answers "is the track it handed me one I would
    have liked?" -- the question ``Summary.txt`` tried to answer with a
    recall number, which is a different quantity entirely.
    """
    return 1.0 if set(recommended[:k]) & relevant else 0.0


def ndcg_at_k(recommended: list[int], relevant: set[int], k: int) -> float:
    """Binary-relevance nDCG. Rewards putting the hit near the top, which
    plain recall and precision are both blind to."""
    if not relevant:
        return 0.0
    gains = [1.0 / np.log2(i + 2) for i, t in enumerate(recommended[:k]) if t in relevant]
    dcg = float(sum(gains))
    ideal = float(sum(1.0 / np.log2(i + 2) for i in range(min(len(relevant), k))))
    return dcg / ideal if ideal else 0.0


def gini(values: np.ndarray | list[float]) -> float:
    """Concentration of a distribution: 0 = perfectly even, 1 = winner-takes-all.

    Applied to how often each track gets recommended, this is the number that
    would have caught engine_v2 handing the same handful of artists to
    everyone.
    """
    arr = np.sort(np.asarray(list(values), dtype=np.float64))
    if arr.size == 0 or arr.sum() == 0:
        return 0.0
    if (arr < 0).any():
        raise ValueError("gini is undefined for negative values")
    n = arr.size
    index = np.arange(1, n + 1)
    return float((2 * (index * arr).sum()) / (n * arr.sum()) - (n + 1) / n)


@dataclass
class EvalResult:
    users_evaluated: int
    k: int
    recall: float
    precision: float
    hit_rate: float
    ndcg: float
    catalogue_coverage: float
    recommendation_gini: float
    empty_responses: int

    def as_dict(self) -> dict:
        return {
            "users_evaluated": self.users_evaluated,
            "k": self.k,
            f"recall@{self.k}": round(self.recall, 4),
            f"precision@{self.k}": round(self.precision, 4),
            f"hit_rate@{self.k}": round(self.hit_rate, 4),
            f"ndcg@{self.k}": round(self.ndcg, 4),
            "catalogue_coverage": round(self.catalogue_coverage, 4),
            "recommendation_gini": round(self.recommendation_gini, 4),
            "empty_responses": self.empty_responses,
        }


def evaluate_rankings(
    rankings: dict[int, list[int]],
    split: Split,
    k: int,
    catalogue_size: int,
) -> EvalResult:
    """Score a ``{user_id: ranked track ids}`` mapping against a split.

    Accuracy *and* the two distribution metrics together: an engine can buy
    recall by recommending the same popular head to everyone, and only
    coverage and Gini make that visible.
    """
    recalls, precisions, hits, ndcgs = [], [], [], []
    exposure: dict[int, int] = defaultdict(int)
    empty = 0

    for user, relevant in split.test_by_user.items():
        ranked = rankings.get(user)
        if ranked is None:
            continue
        if not ranked:
            empty += 1
        recalls.append(recall_at_k(ranked, relevant, k))
        precisions.append(precision_at_k(ranked, relevant, k))
        hits.append(hit_rate_at_k(ranked, relevant, k))
        ndcgs.append(ndcg_at_k(ranked, relevant, k))
        for track in ranked[:k]:
            exposure[track] += 1

    mean = lambda xs: float(np.mean(xs)) if xs else 0.0  # noqa: E731
    return EvalResult(
        users_evaluated=len(recalls),
        k=k,
        recall=mean(recalls),
        precision=mean(precisions),
        hit_rate=mean(hits),
        ndcg=mean(ndcgs),
        catalogue_coverage=len(exposure) / catalogue_size if catalogue_size else 0.0,
        recommendation_gini=gini(list(exposure.values())) if exposure else 0.0,
        empty_responses=empty,
    )
