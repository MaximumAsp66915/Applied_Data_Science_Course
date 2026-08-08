"""Contextual bandit over the serving policies.

## Why a bandit and not reinforcement learning proper

Reinforcement learning solves *sequential* credit assignment: an action now
changes the state, and the payoff may not arrive for many steps. That machinery
costs a great deal in sample efficiency, and it buys nothing unless the problem
really has that structure.

Recommending one track does not. The listener finishes it or skips it within
minutes, the reward is observed almost immediately, and the next request starts
from a state that barely depends on which of five reasonable strategies was
used. That is a **contextual bandit**: one-step feedback, small action space,
observed reward. Using full RL here would mean estimating a value function over
a state space we have ~1,300 users' worth of data to cover, and evaluating it
offline would be impossible without exactly the leakage this project already
got burned by (ANALYSIS.md, E-1 to E-4).

The honest framing: this is the *degenerate one-step case* of RL, and solving
the degenerate case well beats solving the general case badly. If the product
later grows genuinely sequential structure -- playlists constructed as a whole,
multi-track arcs with delayed payoff -- the event log written by `events.py` is
exactly the dataset an RL formulation would need, and the arms here become its
action space.

## LinUCB

`LinUCB` (Li et al., 2010), disjoint variant: one independent linear model per
arm. For arm `a` with design matrix `A_a` and response vector `b_a`:

    theta_a = A_a^-1 b_a                     estimated reward weights
    p_a     = theta_a . x + alpha * sqrt(x . A_a^-1 x)

The first term is the predicted reward; the second is the width of its
confidence interval. Picking `argmax p_a` is *optimism under uncertainty*: an
arm gets tried either because it looks good or because we do not yet know that
it is not. `alpha` sets the price of curiosity.

Chosen over the alternatives for concrete reasons. Epsilon-greedy wastes a
fixed fraction of every user's session on arms already known to be bad.
Thompson sampling is competitive but needs a posterior sample per arm per
request; `LinUCB` is deterministic given the state, which makes a served
recommendation reproducible from the log -- worth a lot when debugging why a
user got what they got. Both alternatives are still here: `EpsilonGreedyBandit`
as an off-policy-evaluation baseline, and stochastic sampling available on
`LinUCB` itself via `select(..., stochastic=True)` when logged propensities are
wanted for inverse-propensity scoring.

Updates use the Sherman-Morrison identity to maintain `A^-1` directly, so an
update is O(d^2) rather than the O(d^3) of a fresh inverse. With d = 10 that is
around a microsecond, which is what keeps the learner off the latency budget.
"""
from __future__ import annotations

import logging
import math

import numpy as np

log = logging.getLogger(__name__)

# Context feature layout. Kept explicit and named because a silently reordered
# feature vector between the decision path and a restored snapshot would
# corrupt every model without raising anything.
FEATURE_NAMES: tuple[str, ...] = (
    "bias",
    "log_history",
    "has_track_vector",
    "session_depth",
    "catalogue_exhausted",
    "is_cold_start",
    "profile_trained",
    "profile_blended",
    "recent_reward",
    "artist_concentration",
    "repeat_affinity",
)
FEATURE_DIM = len(FEATURE_NAMES)


def build_context(
    *,
    history_size: int = 0,
    has_track_vector: bool = False,
    session_depth: int = 0,
    catalogue_size: int = 1,
    source: str = "popular_fallback",
    recent_reward: float = 0.0,
    artist_concentration: float = 0.0,
    repeat_affinity: float = 0.0,
) -> np.ndarray:
    """Assemble the context vector from things known at decision time.

    Every feature is bounded to roughly [0, 1] (or [-1, 1] for reward) on
    purpose: LinUCB's confidence term scales with the feature norm, so an
    unbounded feature -- a raw history count, say -- would make one dimension
    dominate the exploration bonus and effectively disable it elsewhere.

    - `history_size`      how many artists/tracks the caller passed as known
                          history: a proxy for how much we know about them.
    - `has_track_vector`  whether stage-2 re-ranking is available at all.
    - `session_depth`     length of the exclude list: how deep into a sitting.
    - `catalogue_exhausted` share of the catalogue already excluded.
    - `is_cold_start`     no trained profile.
    - `profile_*`         which provenance the profile came from.
    - `recent_reward`     this user's reward EMA: are they enjoying this?
    - `artist_concentration` how much of what they have been served comes from
                          one artist -- the "stuck in a rut" detector, and the
                          feature that lets `diversify` earn its place.
    - `repeat_affinity`   how this listener has historically responded when
                          served an artist they were served before. Added after
                          measurement, not before: the first version of this
                          vector had no way to tell a completist from a variety
                          seeker, so the bandit could only learn which arm was
                          best *on average* and paid exploration cost for no
                          contextual gain (see README, "What the simulator
                          showed"). This is the feature that carries that
                          latent trait, and it is observable -- it is just the
                          listener's own past behaviour on repeats.
    """
    x = np.zeros(FEATURE_DIM, dtype=np.float64)
    x[0] = 1.0
    x[1] = min(1.0, math.log1p(max(0, history_size)) / 6.0)
    x[2] = 1.0 if has_track_vector else 0.0
    x[3] = min(1.0, math.log1p(max(0, session_depth)) / 6.0)
    x[4] = min(1.0, max(0, session_depth) / max(1, catalogue_size))
    x[5] = 1.0 if source in ("popular_fallback", "reacted_artists", "reacted_tracks") else 0.0
    x[6] = 1.0 if source == "trained_embedding" else 0.0
    x[7] = 1.0 if source == "blended_profile" else 0.0
    x[8] = float(np.clip(recent_reward, -1.0, 1.0))
    x[9] = float(np.clip(artist_concentration, 0.0, 1.0))
    x[10] = float(np.clip(repeat_affinity, -1.0, 1.0))
    return x


class LinUCB:
    """Disjoint LinUCB over a fixed set of named arms."""

    def __init__(
        self,
        arms: list[str],
        dim: int = FEATURE_DIM,
        alpha: float = 0.6,
        ridge: float = 1.0,
        softmax_temperature: float = 0.05,
        exploration_share: float = 0.10,
        default_arm: str | None = None,
        min_pulls_to_trust: int = 150,
        deviation_margin: float = 0.02,
        trust_learned_policy: bool = False,
    ):
        if not arms:
            raise ValueError("LinUCB needs at least one arm")
        self.arms = list(arms)
        self.dim = int(dim)
        self.alpha = float(alpha)
        self.ridge = float(ridge)
        # Temperature for stochastic selection, on the scale of the reward.
        # This has to match the data: rewards here live in [-1, 1] and arms
        # typically differ by 0.02-0.10, so a temperature of 1.0 -- the obvious
        # default -- makes exp() of those differences indistinguishable and
        # turns "sample proportional to quality" into "sample uniformly".
        # 0.05 means a 0.05 reward gap is roughly a factor of e in probability.
        self.softmax_temperature = float(softmax_temperature)
        # Share of requests on which the confidence bonus is allowed to steer
        # the choice. See `select` for why this is not simply 1.0.
        self.exploration_share = float(exploration_share)
        # The incumbent: what the engine would have served with no learning at
        # all. Deviating from it requires evidence -- see `select`.
        self.default_arm = default_arm if default_arm in arms else arms[0]
        self.min_pulls_to_trust = int(min_pulls_to_trust)
        self.deviation_margin = float(deviation_margin)
        # Off until an off-policy estimate says the learned policy beats the
        # incumbent. See `select`.
        self.trust_learned_policy = bool(trust_learned_policy)

        n = len(self.arms)
        # A_inv starts at I/ridge, the inverse of the ridge-regularised prior.
        self.A_inv = np.stack([np.eye(self.dim) / self.ridge for _ in range(n)])
        self.b = np.zeros((n, self.dim))
        self.counts = np.zeros(n, dtype=np.int64)
        self.reward_sums = np.zeros(n)
        self._index = {arm: i for i, arm in enumerate(self.arms)}

    # ------------------------------------------------------------- selection
    def scores(self, x: np.ndarray) -> np.ndarray:
        """Upper confidence bound per arm."""
        x = np.asarray(x, dtype=np.float64).reshape(-1)
        if x.shape[0] != self.dim:
            raise ValueError(f"context has dim {x.shape[0]}, expected {self.dim}")
        theta = np.einsum("aij,aj->ai", self.A_inv, self.b)  # (n_arms, dim)
        mean = theta @ x
        # x . A^-1 . x, per arm. Clipped at 0: A_inv stays positive definite in
        # exact arithmetic, but floating point can produce a tiny negative.
        variance = np.einsum("i,aij,j->a", x, self.A_inv, x)
        width = self.alpha * np.sqrt(np.maximum(variance, 0.0))
        return mean + width

    def means(self, x: np.ndarray) -> np.ndarray:
        """Predicted reward per arm, with no exploration bonus."""
        x = np.asarray(x, dtype=np.float64).reshape(-1)
        theta = np.einsum("aij,aj->ai", self.A_inv, self.b)
        return theta @ x

    def select(
        self,
        x: np.ndarray,
        stochastic: bool = False,
        rng: np.random.Generator | None = None,
        exploration_share: float | None = None,
    ) -> tuple[str, float]:
        """Choose an arm. Returns `(arm_name, propensity)`.

        The default behaviour is **shadow mode**, and it is a deliberate
        departure from textbook LinUCB that measurement forced:

        * On `exploration_share` of requests, an arm is drawn **uniformly at
          random**. This is the data-collection slice. Uniform randomisation is
          what makes the resulting log a valid off-policy dataset -- inverse
          propensity scoring needs to know the probability each arm had, and
          uniform is the only choice that guarantees every arm is observed
          across the whole context distribution rather than only where some
          policy already liked it.
        * On the rest, the **incumbent** arm is served -- what the engine would
          have done with no learning at all -- unless `trust_learned_policy` is
          switched on, in which case the evidence-gated `_exploit` choice
          decides.

        Why not just act on the learned model straight away? Because in
        measurement it made the product worse, for a reason worth recording. In
        disjoint LinUCB each arm's weights are fitted only on the contexts in
        which that arm was chosen, so comparing predicted means *across* arms
        compares models trained on different distributions. In the simulator
        this showed up starkly: `deep_cut` had the highest observed mean reward
        of any arm (0.36) while being the second *worst* arm by actual
        completion rate (0.69 against the incumbent's 0.72) -- it was simply
        chosen more often for listeners who were already doing well. Acting on
        that comparison is acting on confounding.

        So the sequence is: collect an unbiased log, estimate candidate
        policies off-policy with `offline_eval.py`, and only then set
        `trust_learned_policy`. Until that point the cost of learning is
        bounded and knowable: `exploration_share x (incumbent - mean other
        arm)`, which for the shipped default of 0.10 is around 0.3 points of
        completion rate.

        `exploration_share=1.0` with `trust_learned_policy=True` recovers
        standard LinUCB, for anyone who wants it.
        """
        share = self.exploration_share if exploration_share is None else float(exploration_share)
        rng = rng or np.random.default_rng()
        n = len(self.arms)

        if stochastic:
            # Softmax over UCB scores. Retained for experimentation; the
            # uniform slice above is the better source of evaluation data
            # because its propensities do not depend on the model's own state.
            scores = self.scores(x)
            temperature = max(self.softmax_temperature, 1e-6)
            shifted = (scores - scores.max()) / temperature
            weights = np.exp(shifted)
            probabilities = weights / weights.sum()
            index = int(rng.choice(n, p=probabilities))
            return self.arms[index], float(probabilities[index])

        if share > 0 and rng.random() < share:
            index = int(rng.integers(n))
            return self.arms[index], share / n

        arm = self._exploit(x) if self.trust_learned_policy else self.default_arm
        # P(this arm) = greedy mass + its slice of the uniform exploration.
        return arm, (1.0 - share) + share / n

    def _exploit(self, x: np.ndarray) -> str:
        """Serve the best arm we can defend, defaulting to the incumbent.

        Deviating from the incumbent policy requires two things: enough
        observations of the challenger to believe its estimate at all, and a
        margin over the incumbent large enough not to be noise. Without this
        rule the bandit acts on near-zero-evidence differences from its first
        few dozen requests, which in measurement cost more than the contextual
        signal was worth -- the engine got slightly worse before it got better,
        and "before it got better" was longer than a product can be asked to
        wait.

        The consequence is a hard bound on how badly learning can go: on
        exploitation requests the engine either serves the incumbent or an arm
        with real evidence behind it, so worst-case regret comes only from the
        `exploration_share` slice.
        """
        means = self.means(x)
        default_index = self._index[self.default_arm]
        best_index = default_index
        best_value = means[default_index]

        for index in range(len(self.arms)):
            if index == default_index:
                continue
            if self.counts[index] < self.min_pulls_to_trust:
                continue
            if means[index] > best_value + self.deviation_margin:
                best_index, best_value = index, means[index]
        return self.arms[best_index]

    def update(self, arm: str, x: np.ndarray, reward: float) -> None:
        """Fold one observed reward into that arm's model.

        Sherman-Morrison: for A' = A + x x^T,

            A'^-1 = A^-1 - (A^-1 x x^T A^-1) / (1 + x^T A^-1 x)

        which keeps the update O(d^2) and never forms A itself.
        """
        index = self._index.get(arm)
        if index is None:
            log.warning("update for unknown arm %r ignored", arm)
            return

        x = np.asarray(x, dtype=np.float64).reshape(-1)
        if x.shape[0] != self.dim:
            log.warning("update with context dim %d, expected %d -- ignored", x.shape[0], self.dim)
            return

        A_inv = self.A_inv[index]
        Ax = A_inv @ x
        denominator = 1.0 + float(x @ Ax)
        if denominator <= 1e-12:  # pragma: no cover - numerically unreachable
            return
        self.A_inv[index] = A_inv - np.outer(Ax, Ax) / denominator
        self.b[index] += float(reward) * x
        self.counts[index] += 1
        self.reward_sums[index] += float(reward)

    # -------------------------------------------------------------- reporting
    def theta(self, arm: str) -> np.ndarray:
        index = self._index[arm]
        return self.A_inv[index] @ self.b[index]

    @property
    def stats(self) -> dict:
        return {
            "algorithm": "linucb",
            "alpha": self.alpha,
            "softmax_temperature": self.softmax_temperature,
            "exploration_share": self.exploration_share,
            "default_arm": self.default_arm,
            "min_pulls_to_trust": self.min_pulls_to_trust,
            "trust_learned_policy": self.trust_learned_policy,
            "mode": "acting" if self.trust_learned_policy else "shadow",
            "dim": self.dim,
            "total_updates": int(self.counts.sum()),
            "arms": {
                arm: {
                    "pulls": int(self.counts[i]),
                    "mean_reward": round(
                        float(self.reward_sums[i] / self.counts[i]) if self.counts[i] else 0.0, 4
                    ),
                }
                for i, arm in enumerate(self.arms)
            },
        }

    # ------------------------------------------------------------ persistence
    def to_arrays(self) -> dict:
        return {
            "arms": np.array(self.arms, dtype=object),
            "A_inv": self.A_inv,
            "b": self.b,
            "counts": self.counts,
            "reward_sums": self.reward_sums,
            "alpha": np.array([self.alpha]),
            "ridge": np.array([self.ridge]),
            "exploration_share": np.array([self.exploration_share]),
        }

    @classmethod
    def from_arrays(cls, payload: dict, arms: list[str]) -> "LinUCB":
        """Restore, tolerating an arm registry that has changed since the
        snapshot was written.

        Arms that no longer exist are dropped and new ones start from the
        prior, so adding a policy is a safe deploy rather than a state wipe.
        """
        stored = [str(a) for a in payload["arms"].tolist()]
        bandit = cls(
            arms,
            dim=int(payload["b"].shape[1]),
            alpha=float(payload["alpha"][0]),
            ridge=float(payload["ridge"][0]),
            exploration_share=(
                float(payload["exploration_share"][0])
                if "exploration_share" in payload
                else 0.25
            ),
        )
        for stored_index, arm in enumerate(stored):
            index = bandit._index.get(arm)
            if index is None:
                log.info("dropping state for retired arm %r", arm)
                continue
            bandit.A_inv[index] = payload["A_inv"][stored_index]
            bandit.b[index] = payload["b"][stored_index]
            bandit.counts[index] = payload["counts"][stored_index]
            bandit.reward_sums[index] = payload["reward_sums"][stored_index]
        return bandit


class EpsilonGreedyBandit:
    """Context-free epsilon-greedy, kept as an evaluation baseline.

    Not a serious candidate for serving -- it ignores context entirely, so it
    cannot learn that cold users want `popular` while deep listeners want
    `deep_cut`. Its job is to be the thing `offline_eval.py` compares LinUCB
    against, so "the contextual bandit helps" is a measurement rather than an
    assumption.
    """

    def __init__(self, arms: list[str], epsilon: float = 0.1, seed: int | None = None):
        self.arms = list(arms)
        self.epsilon = float(epsilon)
        self.counts = np.zeros(len(self.arms), dtype=np.int64)
        self.reward_sums = np.zeros(len(self.arms))
        self._rng = np.random.default_rng(seed)
        self._index = {arm: i for i, arm in enumerate(self.arms)}

    def select(self, x=None, stochastic: bool = False, rng=None) -> tuple[str, float]:
        n = len(self.arms)
        explore = self._rng.random() < self.epsilon
        if explore or not self.counts.any():
            index = int(self._rng.integers(n))
            return self.arms[index], self.epsilon / n + (0.0 if explore else 0.0)
        means = np.divide(
            self.reward_sums, self.counts, out=np.full(n, -np.inf), where=self.counts > 0
        )
        index = int(np.argmax(means))
        return self.arms[index], 1.0 - self.epsilon + self.epsilon / n

    def update(self, arm: str, x=None, reward: float = 0.0) -> None:
        index = self._index.get(arm)
        if index is None:
            return
        self.counts[index] += 1
        self.reward_sums[index] += float(reward)

    @property
    def stats(self) -> dict:
        return {
            "algorithm": "epsilon_greedy",
            "epsilon": self.epsilon,
            "total_updates": int(self.counts.sum()),
            "arms": {
                arm: {
                    "pulls": int(self.counts[i]),
                    "mean_reward": round(
                        float(self.reward_sums[i] / self.counts[i]) if self.counts[i] else 0.0, 4
                    ),
                }
                for i, arm in enumerate(self.arms)
            },
        }
