"""Per-user online preference learning.

The bandit in `bandit.py` learns *how* to behave. This learns *what a
particular person likes*, from what they do, between retrains.

`Manual.txt` section 7 described the ambition -- "these operations take < 1 ms
and can be performed on every /recommend call; the bot never needs to retrain"
-- and no version of the engine implemented it. A user's vector was frozen from
one weekly retrain to the next, so a listener could skip an artist twenty times
running and be handed a twenty-first.

## The update

Each user carries a **delta** in artist space (and optionally track space) on
top of their trained vector, which is never modified:

    effective = base + delta_u

On an observed reward `r` for a track by artist `a`:

    delta_u  <-  (1 - lambda) * delta_u  +  eta * r * e_a_hat

where `e_a_hat` is the unit-normalised artist embedding. This is one step of
online gradient ascent on the linear reward model `r_hat = (base + delta) . e`,
which is the same object the bandit optimises -- with the item embeddings held
fixed, because they were fitted on far more data than any one listener will
ever produce and are not this loop's to move.

Three safeguards, each earning its place:

**Normalised gradients.** Using `e_a` raw would let a high-norm artist
embedding dominate; normalising means the update direction carries the
information and `eta * r` alone sets the size.

**A trust region.** `||delta|| <= kappa * mean_user_norm` is enforced by
projection after every step. Without it a run of bad luck can push a profile
somewhere the base embeddings never go, and the recommendations become
incoherent rather than merely wrong. With it, the worst case is that the user
is served as if they were a somewhat different -- but still real -- listener.

**Decay.** The `(1 - lambda)` factor makes the delta a leaky accumulator, so
old feedback fades and last month's mood does not outweigh this week's. It also
guarantees the delta stays bounded even if the projection never triggers, and
means a user who stops giving feedback drifts gracefully back to their trained
profile rather than being frozen at whatever they last felt.

`decay_to_now` applies the same leak on a wall-clock half-life, so a user who
disappears for a month comes back mostly reset without any background job
having to touch their state.
"""
from __future__ import annotations

import threading
import time

import numpy as np


class UserDeltaStore:
    """Bounded, thread-safe store of per-user preference deltas."""

    def __init__(
        self,
        artist_dim: int,
        track_dim: int,
        mean_user_norm: float = 1.0,
        learning_rate: float = 0.08,
        decay: float = 0.02,
        max_norm_ratio: float = 0.5,
        half_life_days: float = 21.0,
        max_users: int = 50_000,
    ):
        self.artist_dim = int(artist_dim)
        self.track_dim = int(track_dim)
        self.mean_user_norm = float(mean_user_norm) or 1.0
        self.learning_rate = float(learning_rate)
        self.decay = float(decay)
        self.max_norm_ratio = float(max_norm_ratio)
        self.half_life_seconds = float(half_life_days) * 86400.0
        self.max_users = int(max_users)

        self._artist: dict[int, np.ndarray] = {}
        self._track: dict[int, np.ndarray] = {}
        self._touched: dict[int, float] = {}
        self._updates: dict[int, int] = {}
        self._reward_ema: dict[int, float] = {}
        self._repeat_ema: dict[int, float] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ read
    def artist_delta(self, user_id: int | None) -> np.ndarray | None:
        """The user's artist-space delta, decayed to now. None if they have none."""
        if user_id is None:
            return None
        with self._lock:
            delta = self._artist.get(int(user_id))
            if delta is None:
                return None
            return self._decayed(int(user_id), delta)

    def track_delta(self, user_id: int | None) -> np.ndarray | None:
        if user_id is None:
            return None
        with self._lock:
            delta = self._track.get(int(user_id))
            if delta is None:
                return None
            return self._decayed(int(user_id), delta)

    def recent_reward(self, user_id: int | None) -> float:
        """Exponential moving average of this user's recent rewards.

        Fed to the bandit as a context feature: a listener whose recent rewards
        are negative is a listener the current strategy is failing, which is
        exactly when a different arm should be tried.
        """
        if user_id is None:
            return 0.0
        with self._lock:
            return float(self._reward_ema.get(int(user_id), 0.0))

    def repeat_affinity(self, user_id: int | None) -> float:
        """How this listener responds to being served a familiar artist.

        An EMA of reward restricted to impressions whose artist the listener
        had already been served recently. Positive means a completist who is
        happy to go deeper; negative means someone who wants to move on. This
        is the observable stand-in for a trait the engine otherwise has no way
        to see, and it is what makes `deep_cut` and `diversify` separable
        choices rather than a coin flip.
        """
        if user_id is None:
            return 0.0
        with self._lock:
            return float(self._repeat_ema.get(int(user_id), 0.0))

    def update_count(self, user_id: int | None) -> int:
        if user_id is None:
            return 0
        with self._lock:
            return int(self._updates.get(int(user_id), 0))

    # ---------------------------------------------------------------- update
    def update(
        self,
        user_id: int | None,
        reward: float,
        artist_embedding: np.ndarray | None = None,
        track_embedding: np.ndarray | None = None,
        was_repeat_artist: bool = False,
    ) -> None:
        """Apply one reward-weighted gradient step for this user."""
        if user_id is None or reward == 0.0:
            return
        user_id = int(user_id)

        with self._lock:
            if user_id not in self._artist and len(self._artist) >= self.max_users:
                self._evict_locked()

            if artist_embedding is not None:
                self._artist[user_id] = self._step(
                    self._decayed(user_id, self._artist.get(user_id), default_dim=self.artist_dim),
                    artist_embedding,
                    reward,
                )
            if track_embedding is not None:
                self._track[user_id] = self._step(
                    self._decayed(user_id, self._track.get(user_id), default_dim=self.track_dim),
                    track_embedding,
                    reward,
                )

            self._touched[user_id] = time.time()
            self._updates[user_id] = self._updates.get(user_id, 0) + 1
            previous = self._reward_ema.get(user_id, 0.0)
            self._reward_ema[user_id] = 0.7 * previous + 0.3 * float(reward)
            if was_repeat_artist:
                prior = self._repeat_ema.get(user_id, 0.0)
                self._repeat_ema[user_id] = 0.8 * prior + 0.2 * float(reward)

    def _step(self, delta: np.ndarray, embedding: np.ndarray, reward: float) -> np.ndarray:
        embedding = np.asarray(embedding, dtype=np.float64).reshape(-1)
        if embedding.shape[0] != delta.shape[0]:
            return delta
        norm = float(np.linalg.norm(embedding))
        if norm == 0.0:
            return delta
        direction = embedding / norm

        updated = (1.0 - self.decay) * delta + self.learning_rate * float(reward) * direction

        limit = self.max_norm_ratio * self.mean_user_norm
        magnitude = float(np.linalg.norm(updated))
        if magnitude > limit:
            updated *= limit / magnitude
        return updated

    def _decayed(
        self, user_id: int, delta: np.ndarray | None, default_dim: int | None = None
    ) -> np.ndarray:
        """Apply the wall-clock half-life since this user was last touched."""
        if delta is None:
            return np.zeros(default_dim or self.artist_dim, dtype=np.float64)
        last = self._touched.get(user_id)
        if last is None:
            return delta
        elapsed = max(0.0, time.time() - last)
        if elapsed <= 0 or self.half_life_seconds <= 0:
            return delta
        return delta * float(0.5 ** (elapsed / self.half_life_seconds))

    def _evict_locked(self) -> None:
        """Drop the least recently touched user. Cheap and rare -- this only
        fires past `max_users`, which is 40x the current user base."""
        if not self._touched:
            return
        oldest = min(self._touched, key=self._touched.get)
        self._artist.pop(oldest, None)
        self._track.pop(oldest, None)
        self._touched.pop(oldest, None)
        self._updates.pop(oldest, None)
        self._reward_ema.pop(oldest, None)

    def reset(self, user_id: int) -> bool:
        """Forget everything learned about one user.

        Present because it has to be: a user asking to be forgotten, or a
        profile that has visibly gone wrong, needs an answer that is not
        "restart the process".
        """
        user_id = int(user_id)
        with self._lock:
            found = user_id in self._artist or user_id in self._track
            self._artist.pop(user_id, None)
            self._track.pop(user_id, None)
            self._touched.pop(user_id, None)
            self._updates.pop(user_id, None)
            self._reward_ema.pop(user_id, None)
            self._repeat_ema.pop(user_id, None)
            return found

    # -------------------------------------------------------------- reporting
    @property
    def stats(self) -> dict:
        with self._lock:
            norms = [float(np.linalg.norm(v)) for v in self._artist.values()]
            return {
                "users_with_delta": len(self._artist),
                "total_updates": int(sum(self._updates.values())),
                "mean_delta_norm": round(float(np.mean(norms)), 4) if norms else 0.0,
                "max_delta_norm": round(float(np.max(norms)), 4) if norms else 0.0,
                "trust_region": round(self.max_norm_ratio * self.mean_user_norm, 4),
                "learning_rate": self.learning_rate,
            }

    # ------------------------------------------------------------ persistence
    def to_arrays(self) -> dict:
        with self._lock:
            users = sorted(set(self._artist) | set(self._track))
            if not users:
                return {
                    "user_ids": np.zeros(0, dtype=np.int64),
                    "artist_delta": np.zeros((0, self.artist_dim)),
                    "track_delta": np.zeros((0, self.track_dim)),
                    "touched": np.zeros(0),
                    "updates": np.zeros(0, dtype=np.int64),
                    "reward_ema": np.zeros(0),
                    "repeat_ema": np.zeros(0),
                }
            zeros_a = np.zeros(self.artist_dim)
            zeros_t = np.zeros(self.track_dim)
            return {
                "user_ids": np.array(users, dtype=np.int64),
                "artist_delta": np.stack([self._artist.get(u, zeros_a) for u in users]),
                "track_delta": np.stack([self._track.get(u, zeros_t) for u in users]),
                "touched": np.array([self._touched.get(u, 0.0) for u in users]),
                "updates": np.array([self._updates.get(u, 0) for u in users], dtype=np.int64),
                "reward_ema": np.array([self._reward_ema.get(u, 0.0) for u in users]),
                "repeat_ema": np.array([self._repeat_ema.get(u, 0.0) for u in users]),
            }

    def load_arrays(self, payload: dict) -> None:
        with self._lock:
            self._artist.clear()
            self._track.clear()
            self._touched.clear()
            self._updates.clear()
            self._reward_ema.clear()
            self._repeat_ema.clear()

            user_ids = payload["user_ids"]
            artist_delta = payload["artist_delta"]
            track_delta = payload["track_delta"]
            if artist_delta.shape[1:] and artist_delta.shape[1] != self.artist_dim:
                # A retrain that changed the embedding dimension invalidates
                # every delta; starting clean beats serving garbage.
                return
            for index, user in enumerate(user_ids.tolist()):
                user = int(user)
                if np.any(artist_delta[index]):
                    self._artist[user] = artist_delta[index]
                if track_delta.shape[1:] and np.any(track_delta[index]):
                    self._track[user] = track_delta[index]
                self._touched[user] = float(payload["touched"][index])
                self._updates[user] = int(payload["updates"][index])
                self._reward_ema[user] = float(payload["reward_ema"][index])
                if "repeat_ema" in payload:
                    self._repeat_ema[user] = float(payload["repeat_ema"][index])
