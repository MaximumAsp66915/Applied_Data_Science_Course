"""Loads the artifacts under model_params/ once and answers recommendation
queries against them -- the v3 serving path.

Same two-stage shape as v2 (artist ranking -> track re-ranking, see
README.md), same HTTP contract upstream (main.py), same pure numpy/pickle
inference with NO torch -- but four behavioural fixes over v2's recommender:

1. Candidates are filtered by `exclude` BEFORE the per-artist cut. v2 took
   each artist's top-N tracks and only then dropped the ones the user had
   already seen, so a heavy listener who had heard an artist's N most
   popular tracks got zero candidates from that artist even if it had 40
   more. v3 takes the top-N *unseen* tracks per artist (which is also what
   the offline evaluation in the v2 notebook assumed).
2. Tracks are indexed under EVERY artist credited on them (track_artists.pkl),
   not only the first one -- "A feat. B" is now a candidate when B is the
   user's top artist.
3. An optional per-artist bias (artist_bias.npy) and a popularity prior
   (`pop_weight`) can be blended in. Both default to the values chosen on a
   validation split by train.py and stored in ensemble_config.json; setting
   both to 0 reproduces v2's plain dot-product behaviour.
4. Artist ids passed in by the app that were merged into a canonical artist
   during name de-duplication (artist_alias.pkl) are mapped to it instead of
   being silently ignored.

Every file added over v2 is OPTIONAL: pointed at a v2-style model_params/
folder this class still loads and behaves like v2 (plus fix 1).

This module has no FastAPI/HTTP awareness at all -- main.py is the only
thing that imports it and turns it into endpoints.
"""
from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class UserProfile:
    """Bundles the two embedding spaces a user can have a vector in.

    `artist_vec` drives stage 1 (artist ranking); `track_vec`, when present,
    drives stage 2 (track re-ranking). A user can have an artist_vec without
    a track_vec (cold-start / reacted-artists-only signal), in which case
    stage 2 falls back to popularity within the candidate pool.
    """

    artist_vec: np.ndarray | None
    track_vec: np.ndarray | None
    source: str | None


class Recommender:
    def __init__(self, params_dir: Path):
        self.params_dir = Path(params_dir)
        p = self.params_dir
        with open(p / "ensemble_config.json") as f:
            self.config = json.load(f)

        # -- artist model (stage 1) --------------------------------------
        self.user_enc_artist = _load_pickle(p / "user_enc_artist.pkl")
        self.artist_enc = _load_pickle(p / "artist_enc.pkl")
        self.artist_user_emb = np.load(p / "artist_user_embeddings.npy")
        self.artist_artist_emb = np.load(p / "artist_artist_embeddings.npy")
        bias_path = p / "artist_bias.npy"
        self.artist_bias = (
            np.load(bias_path) if bias_path.exists() else np.zeros(len(self.artist_enc.classes_), dtype=np.float32)
        )

        # -- track model (stage 2 re-ranking) -----------------------------
        self.track_user_enc = _load_pickle(p / "track_user_enc.pkl")
        self.track_item_enc = _load_pickle(p / "track_item_enc.pkl")
        self.track_user_emb = np.load(p / "track_user_embeddings.npy")
        self.track_item_emb = np.load(p / "track_item_embeddings.npy")

        # -- shared mappings ----------------------------------------------
        self.track_to_artist: dict[int, int] = _load_pickle(p / "track_to_artist.pkl")
        self.track_id_to_idx: dict[int, int] = _load_pickle(p / "track_id_to_idx.pkl")
        self.track_pop = np.load(p / "track_pop.npy")
        # tid -> [artist ids ...] (every credited artist); falls back to the
        # single primary artist for a v2-style folder without this file.
        ta_path = p / "track_artists.pkl"
        self.track_artists: dict[int, list[int]] = (
            _load_pickle(ta_path) if ta_path.exists() else {t: [a] for t, a in self.track_to_artist.items()}
        )
        alias_path = p / "artist_alias.pkl"
        self.artist_alias: dict[int, int] = _load_pickle(alias_path) if alias_path.exists() else {}

        # LabelEncoder.classes_ is "index -> original id"; these are the
        # reverse lookups (original id -> index) built once here instead of
        # calling .transform() per request.
        self._user_id_to_idx_artist = {int(u): i for i, u in enumerate(self.user_enc_artist.classes_)}
        self._user_id_to_idx_track = {int(u): i for i, u in enumerate(self.track_user_enc.classes_)}
        self._artist_id_to_idx = {int(a): i for i, a in enumerate(self.artist_enc.classes_)}
        self._track_id_to_track_idx = {int(t): i for i, t in enumerate(self.track_item_enc.classes_)}
        self._log_pop = np.log1p(np.asarray(self.track_pop, dtype=np.float64))

        # artist_idx -> [track_id, ...], most popular first (ties broken by
        # track id so results are deterministic). Built once at load time.
        by_artist: dict[int, list[int]] = {}
        for tid, aids in self.track_artists.items():
            if tid not in self.track_id_to_idx:
                continue  # track never made it into the model's universe
            for aid in aids:
                aidx = self._artist_id_to_idx.get(int(aid))
                if aidx is not None:
                    by_artist.setdefault(aidx, []).append(tid)
        for tids in by_artist.values():
            tids.sort(key=lambda t: (-self.track_pop[self.track_id_to_idx[t]], t))
        self._artist_to_tracks = by_artist

        # Artists ordered by total popularity of their tracks -- cold-start
        # onboarding. Uses PRIMARY-artist tracks only so a featured credit
        # doesn't inflate an artist's onboarding rank.
        primary: dict[int, list[int]] = {}
        for tid, aid in self.track_to_artist.items():
            aidx = self._artist_id_to_idx.get(int(aid))
            if aidx is not None and tid in self.track_id_to_idx:
                primary.setdefault(aidx, []).append(tid)
        artist_total_pop = np.zeros(len(self.artist_enc.classes_))
        for aidx, tids in primary.items():
            artist_total_pop[aidx] = sum(self.track_pop[self.track_id_to_idx[t]] for t in tids)
        self._artists_by_popularity = [int(a) for a in np.argsort(-artist_total_pop, kind="stable")]

        # Track ids by raw popularity, most popular first -- the fallback
        # used whenever there is no usable signal at all.
        idx_to_track = {idx: tid for tid, idx in self.track_id_to_idx.items()}
        order = np.argsort(-np.asarray(self.track_pop, dtype=np.float64), kind="stable")
        self._tracks_by_popularity = [int(idx_to_track[int(i)]) for i in order]

    # -- config passthrough ---------------------------------------------------
    @property
    def n_artists_rec(self) -> int:
        return int(self.config.get("n_artists_candidates", 20))

    @property
    def tracks_per_artist(self) -> int:
        return int(self.config.get("tracks_per_artist_candidate", 10))

    @property
    def top_k_default(self) -> int:
        return int(self.config.get("top_k_final", 10))

    @property
    def bias_weight(self) -> float:
        return float(self.config.get("artist_bias_weight", 0.0))

    @property
    def pop_weight(self) -> float:
        return float(self.config.get("pop_weight", 0.0))

    # -- building a user profile ----------------------------------------------
    def _canon(self, artist_id: int) -> int:
        return self.artist_alias.get(int(artist_id), int(artist_id))

    def profile_from_id(self, user_id: int) -> UserProfile | None:
        """The real trained embeddings for a user present at training time --
        artist-space always exists if this returns non-None; track-space is
        included too when the user was also in the track model's data."""
        aidx = self._user_id_to_idx_artist.get(int(user_id))
        if aidx is None:
            return None
        tidx = self._user_id_to_idx_track.get(int(user_id))
        track_vec = self.track_user_emb[tidx] if tidx is not None else None
        return UserProfile(self.artist_user_emb[aidx], track_vec, "trained_embedding")

    def profile_from_artists(self, artist_ids: list[int]) -> UserProfile | None:
        """Average of the given artists' embeddings, for a user the engine
        has no trained embedding for. No track-space vector: re-ranking
        falls back to popularity."""
        idxs = []
        for a in artist_ids:
            i = self._artist_id_to_idx.get(self._canon(a))
            if i is not None:
                idxs.append(i)
        if not idxs:
            return None
        return UserProfile(self.artist_artist_emb[idxs].mean(axis=0), None, "reacted_artists")

    def profile_from_tracks(self, track_ids: list[int]) -> UserProfile | None:
        """Cold-start path: every credited artist of each given track, averaged."""
        artist_ids: list[int] = []
        for tid in track_ids:
            artist_ids.extend(self.track_artists.get(int(tid), []))
        if not artist_ids:
            return None
        profile = self.profile_from_artists(artist_ids)
        if profile is not None:
            profile.source = "reacted_tracks"
        return profile

    # -- ephemeral implicit-feedback nudge -----------------------------------
    def nudge_profile(
        self,
        profile: UserProfile,
        liked_track_id: int | None = None,
        disliked_track_id: int | None = None,
        alpha: float = 0.35,
    ) -> UserProfile:
        """Blends the profile's artist-space vector toward the liked track's
        artist embedding and/or away from the disliked one's, for a single
        request. Nothing is written back anywhere. track_vec is untouched."""
        out = profile.artist_vec
        for track_id, sign in ((liked_track_id, 1.0), (disliked_track_id, -1.0)):
            if track_id is None:
                continue
            artist_id = self.track_to_artist.get(int(track_id))
            if artist_id is None:
                continue
            aidx = self._artist_id_to_idx.get(int(artist_id))
            if aidx is None:
                continue
            out = (1 - alpha) * out + sign * alpha * self.artist_artist_emb[aidx]
        return UserProfile(out, profile.track_vec, profile.source)

    # -- the two-stage pipeline -------------------------------------------------
    def recommend_from_profile(
        self,
        profile: UserProfile,
        exclude: set[int] | None = None,
        top_k: int | None = None,
        n_artists: int | None = None,
        tracks_per_artist: int | None = None,
        bias_weight: float | None = None,
        pop_weight: float | None = None,
    ) -> list[int]:
        top_k = top_k or self.top_k_default
        n_artists = min(n_artists or self.n_artists_rec, len(self.artist_enc.classes_))
        tracks_per_artist = tracks_per_artist or self.tracks_per_artist
        bias_weight = self.bias_weight if bias_weight is None else bias_weight
        pop_weight = self.pop_weight if pop_weight is None else pop_weight
        exclude = exclude or set()

        # Stage 1 -- artist ranking.
        scores = profile.artist_vec @ self.artist_artist_emb.T
        if bias_weight:
            scores = scores + bias_weight * self.artist_bias
        top_artist_idxs = np.argpartition(scores, -n_artists)[-n_artists:]
        top_artist_idxs = top_artist_idxs[np.argsort(-scores[top_artist_idxs], kind="stable")]

        # Stage 2a -- candidates: the top-N UNSEEN tracks of each top artist.
        candidates: dict[int, None] = {}
        for aidx in top_artist_idxs:
            taken = 0
            for tid in self._artist_to_tracks.get(int(aidx), ()):
                if tid in exclude or tid in candidates:
                    continue
                candidates[tid] = None
                taken += 1
                if taken >= tracks_per_artist:
                    break
        if not candidates:
            return []

        # Stage 2b -- re-rank: track-model score when the user has a
        # track-space vector, else popularity within the candidate pool.
        cand = list(candidates)
        if profile.track_vec is not None:
            rows = np.fromiter((self._track_id_to_track_idx[t] for t in cand), dtype=np.int64, count=len(cand))
            s = self.track_item_emb[rows] @ profile.track_vec
            if pop_weight:
                s = s + pop_weight * self._log_pop[[self.track_id_to_idx[t] for t in cand]]
        else:
            s = self._log_pop[[self.track_id_to_idx[t] for t in cand]]
        order = np.argsort(-s, kind="stable")[:top_k]
        return [int(cand[i]) for i in order]

    def popular_tracks(self, exclude: set[int] | None = None, top_k: int = 10) -> list[int]:
        """Last-resort fallback: no usable profile at all."""
        exclude = exclude or set()
        out = [tid for tid in self._tracks_by_popularity if tid not in exclude]
        return out[:top_k]

    # -- cold-start onboarding ----------------------------------------------------
    def onboarding_tracks(self, count: int = 5, exclude: set[int] | None = None) -> list[int]:
        """`count` tracks from `count` different popular artists, for a
        brand-new user's very first session."""
        exclude = exclude or set()
        picked: list[int] = []
        for aidx in self._artists_by_popularity:
            candidate = next((t for t in self._artist_to_tracks.get(int(aidx), []) if t not in exclude), None)
            if candidate is None:
                continue
            picked.append(int(candidate))
            if len(picked) >= count:
                break
        return picked


def _load_pickle(path: Path):
    with open(path, "rb") as f:
        return pickle.load(f)
