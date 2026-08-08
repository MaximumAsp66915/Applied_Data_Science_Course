"""Global item learning: how the whole group is reacting, per track.

The per-user deltas in `user_model.py` learn one listener at a time. This
learns from everybody at once, and it is the piece that addresses the open
problem left at the end of ANALYSIS.md: **2,410 tracks have never received a
positive reaction, so the collaborative models have nothing to say about them.**

Those tracks are now reachable (FIX 6), but reachable is not the same as
rankable -- with no interactions, a track's embedding is close to its
initialisation and its popularity prior is zero, so it sits at the bottom of
every candidate pool it enters. The only way it can ever earn a position is if
being *played* counts for something. That is what this does: once the engine
starts serving a track, the group's behaviour towards it becomes evidence, and
a track that people finish climbs without ever needing a reaction.

## The model

One Beta posterior per track over "will a listener served this finish it?":

    alpha_t = prior_alpha + sum of positive reward
    beta_t  = prior_beta  + sum of |negative reward|
    engagement = alpha_t / (alpha_t + beta_t)

Beta-Bernoulli is the right conjugate pair for a bounded success rate, and it
comes with the property that matters most here: **the posterior mean is pulled
towards the prior in proportion to how little data there is.** A track served
twice and finished twice does not leap to the top; it needs sustained evidence.
That is exactly the protection a naive completion-rate average lacks, and the
reason two plays cannot mint a hit.

The serve-time signal is `engagement - prior_mean`, centred so that a track
with no data contributes nothing at all, and scaled by
`shrink = n / (n + confidence_floor)` so that early evidence is damped further.
A track needs roughly `confidence_floor` observations before it can move
materially. This is the same shrinkage-towards-the-prior idea as the popularity
prior in `recommender.py`, applied to live behaviour instead of history.

## Forgetting

Music taste in a group chat is not stationary, so both parameters decay towards
the prior on a half-life. Without it, a track that was loved in March would
outrank a track that is loved now, forever, and the model would slowly become a
record of the past rather than a description of the present.

Artists get the same treatment at their own level, which gives the engine a
usable signal for an artist whose individual tracks are each too sparse to say
anything -- the same density argument that motivates the whole two-stage design
(Chapter 4, section 4.1).
"""
from __future__ import annotations

import threading
import time

import numpy as np


class EngagementModel:
    """Beta-Bernoulli engagement posteriors over tracks and artists."""

    def __init__(
        self,
        prior_alpha: float = 1.0,
        prior_beta: float = 1.0,
        half_life_days: float = 30.0,
        confidence_floor: float = 8.0,
        max_entries: int = 200_000,
    ):
        self.prior_alpha = float(prior_alpha)
        self.prior_beta = float(prior_beta)
        self.half_life_seconds = float(half_life_days) * 86400.0
        self.confidence_floor = float(confidence_floor)
        self.max_entries = int(max_entries)

        self._track: dict[int, list[float]] = {}  # id -> [alpha, beta, last_ts]
        self._artist: dict[int, list[float]] = {}
        self._lock = threading.RLock()

    @property
    def prior_mean(self) -> float:
        return self.prior_alpha / (self.prior_alpha + self.prior_beta)

    # ---------------------------------------------------------------- update
    def observe(self, track_id: int, artist_id: int | None, reward: float) -> None:
        """Fold one observed reward into the track's and artist's posteriors."""
        if reward == 0.0:
            return
        now = time.time()
        with self._lock:
            self._observe_into(self._track, int(track_id), reward, now)
            if artist_id is not None and int(artist_id) != -1:
                self._observe_into(self._artist, int(artist_id), reward, now)

    def _observe_into(self, table: dict, key: int, reward: float, now: float) -> None:
        if key not in table and len(table) >= self.max_entries:
            self._evict_locked(table)
        entry = table.get(key)
        if entry is None:
            entry = [self.prior_alpha, self.prior_beta, now]
            table[key] = entry
        else:
            self._decay_entry(entry, now)
        if reward > 0:
            entry[0] += float(reward)
        else:
            entry[1] += float(-reward)
        entry[2] = now

    def _decay_entry(self, entry: list[float], now: float) -> None:
        """Pull both parameters towards the prior by the elapsed half-lives."""
        if self.half_life_seconds <= 0:
            return
        elapsed = max(0.0, now - entry[2])
        if elapsed <= 0:
            return
        factor = 0.5 ** (elapsed / self.half_life_seconds)
        entry[0] = self.prior_alpha + (entry[0] - self.prior_alpha) * factor
        entry[1] = self.prior_beta + (entry[1] - self.prior_beta) * factor
        entry[2] = now

    # ------------------------------------------------------------------ read
    def track_signal(self, track_id: int) -> float:
        """Centred, shrunk engagement signal for one track, in about [-1, 1].

        Zero for a track nobody has been served, which is the point: an unknown
        track is not penalised for being unknown, it simply has nothing to add
        and falls back on the model's own opinion of it.
        """
        with self._lock:
            return self._signal(self._track, int(track_id))

    def artist_signal(self, artist_id: int) -> float:
        with self._lock:
            return self._signal(self._artist, int(artist_id))

    def track_signals(self, track_ids) -> np.ndarray:
        """Vectorised lookup for a whole candidate pool."""
        with self._lock:
            return np.array(
                [self._signal(self._track, int(t)) for t in track_ids], dtype=np.float32
            )

    def _signal(self, table: dict, key: int) -> float:
        entry = table.get(key)
        if entry is None:
            return 0.0
        self._decay_entry(entry, time.time())
        alpha, beta = entry[0], entry[1]
        observations = (alpha - self.prior_alpha) + (beta - self.prior_beta)
        if observations <= 0:
            return 0.0
        mean = alpha / (alpha + beta)
        shrink = observations / (observations + self.confidence_floor)
        return float((mean - self.prior_mean) * 2.0 * shrink)

    def observation_count(self, track_id: int) -> float:
        with self._lock:
            entry = self._track.get(int(track_id))
            if entry is None:
                return 0.0
            return (entry[0] - self.prior_alpha) + (entry[1] - self.prior_beta)

    def _evict_locked(self, table: dict) -> None:
        oldest = min(table, key=lambda k: table[k][2])
        table.pop(oldest, None)

    # -------------------------------------------------------------- reporting
    @property
    def stats(self) -> dict:
        with self._lock:
            signals = [self._signal(self._track, k) for k in self._track]
            positive = sum(1 for s in signals if s > 0.05)
            negative = sum(1 for s in signals if s < -0.05)
            return {
                "tracks_observed": len(self._track),
                "artists_observed": len(self._artist),
                "tracks_trending_up": positive,
                "tracks_trending_down": negative,
                "prior_mean": round(self.prior_mean, 3),
                "confidence_floor": self.confidence_floor,
            }

    def top_tracks(self, n: int = 10) -> list[tuple[int, float]]:
        """Highest-engagement tracks, for inspection. Useful for spotting a
        zero-reaction track that live behaviour has promoted -- the case this
        model exists to create."""
        with self._lock:
            scored = [(k, self._signal(self._track, k)) for k in self._track]
        scored.sort(key=lambda kv: kv[1], reverse=True)
        return scored[:n]

    # ------------------------------------------------------------ persistence
    def to_arrays(self) -> dict:
        with self._lock:
            def dump(table):
                if not table:
                    return np.zeros(0, dtype=np.int64), np.zeros((0, 3))
                keys = sorted(table)
                return (
                    np.array(keys, dtype=np.int64),
                    np.array([table[k] for k in keys], dtype=np.float64),
                )

            track_ids, track_values = dump(self._track)
            artist_ids, artist_values = dump(self._artist)
            return {
                "track_ids": track_ids,
                "track_values": track_values,
                "artist_ids": artist_ids,
                "artist_values": artist_values,
            }

    def load_arrays(self, payload: dict) -> None:
        with self._lock:
            self._track.clear()
            self._artist.clear()
            for ids, values, table in (
                (payload["track_ids"], payload["track_values"], self._track),
                (payload["artist_ids"], payload["artist_values"], self._artist),
            ):
                for index, key in enumerate(ids.tolist()):
                    table[int(key)] = list(values[index])
