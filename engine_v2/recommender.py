"""Loads the artifacts under model_params/ (see Manual.txt / Summary.md) once
and answers recommendation queries against them.

This is the v2 "ensemble" model: an artist-level HybridArtistMF stage picks
a broad set of candidate artists for a user, then a track-level TrackMF
stage re-ranks the unseen tracks from those artists (Summary.md sections
2-6). v1's recommender.py only ever had one embedding space to think in;
this one has two (artist-space and track-space), so instead of a single
"user vector" this module builds a `UserProfile` -- an artist-space vector
plus an optional track-space vector -- and threads that through the
pipeline instead.

Deliberately does NOT load artist_model_state.pt / track_model_state.pt /
genre_features.pt and does NOT import torch: exactly like v1, inference
only ever does precomputed-embedding dot products (Manual.txt section 4:
"We will use the precomputed .npy files for speed. The optional files are
only needed if you want to reload the full models, e.g. after
fine-tuning."). Keeping torch out of this process's venv means a much
lighter install on the server for something that's read-only inference
over a handful of numpy arrays -- see requirements.txt.

This module has no FastAPI/HTTP awareness at all -- main.py is the only
thing that imports it and turns it into endpoints, same split as v1.
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

    `artist_vec` drives stage 1 (artist ranking); `track_vec`, when
    present, drives stage 2 (track re-ranking) -- Summary.md section 2. A
    user can have an artist_vec without a track_vec (e.g. cold-start /
    reacted-artists-only signal), in which case stage 2 falls back to
    popularity within the candidate pool, exactly like Manual.txt section
    5.e / 6.d describe for users with no track-model embedding.
    """

    artist_vec: np.ndarray | None
    track_vec: np.ndarray | None
    source: str | None


class Recommender:
    def __init__(self, params_dir: Path):
        self.params_dir = params_dir
        with open(params_dir / "ensemble_config.json") as f:
            self.config = json.load(f)

        # -- artist model (stage 1) --------------------------------------
        self.user_enc_artist = _load_pickle(params_dir / "user_enc_artist.pkl")
        self.artist_enc = _load_pickle(params_dir / "artist_enc.pkl")
        self.artist_user_emb = np.load(params_dir / "artist_user_embeddings.npy")
        self.artist_artist_emb = np.load(params_dir / "artist_artist_embeddings.npy")

        # -- track model (stage 2 re-ranking) -----------------------------
        self.track_user_enc = _load_pickle(params_dir / "track_user_enc.pkl")
        self.track_item_enc = _load_pickle(params_dir / "track_item_enc.pkl")
        self.track_user_emb = np.load(params_dir / "track_user_embeddings.npy")
        self.track_item_emb = np.load(params_dir / "track_item_embeddings.npy")

        # -- shared mappings ----------------------------------------------
        self.track_to_artist: dict[int, int] = _load_pickle(params_dir / "track_to_artist.pkl")
        self.track_id_to_idx: dict[int, int] = _load_pickle(params_dir / "track_id_to_idx.pkl")
        self.track_pop = np.load(params_dir / "track_pop.npy")

        # LabelEncoder.classes_ is "index -> original id"; these are the
        # reverse lookups (original id -> index) the pipeline needs on
        # every call, built once here rather than re-deriving them (or
        # calling .transform()) per request -- same reasoning as v1.
        self._user_id_to_idx_artist = {int(u): i for i, u in enumerate(self.user_enc_artist.classes_)}
        self._user_id_to_idx_track = {int(u): i for i, u in enumerate(self.track_user_enc.classes_)}
        self._artist_id_to_idx = {int(a): i for i, a in enumerate(self.artist_enc.classes_)}
        self._track_id_to_track_idx = {int(t): i for i, t in enumerate(self.track_item_enc.classes_)}

        # artist_idx -> [track_id, ...], sorted by popularity descending --
        # Summary.md section 6.b's "candidate collection" precomputed once
        # at load time rather than rebuilt on every request.
        by_artist: dict[int, list[int]] = {}
        for tid, aid in self.track_to_artist.items():
            aidx = self._artist_id_to_idx.get(int(aid))
            if aidx is None or tid not in self.track_id_to_idx:
                continue  # artist or track never made it into training data
            by_artist.setdefault(aidx, []).append(tid)
        for tids in by_artist.values():
            tids.sort(key=lambda t: self.track_pop[self.track_id_to_idx[t]], reverse=True)
        self._artist_to_tracks = by_artist

        # Artist indices ordered by total popularity of their own tracks,
        # most popular first -- cold-start onboarding, same idea as v1.
        artist_total_pop = np.zeros(len(self.artist_enc.classes_))
        for aidx, tids in by_artist.items():
            artist_total_pop[aidx] = sum(self.track_pop[self.track_id_to_idx[t]] for t in tids)
        self._artists_by_popularity = list(np.argsort(artist_total_pop)[::-1])

        # Track ids ordered by raw popularity, most popular first -- the
        # fallback used whenever there's no usable signal at all.
        idx_to_track = {idx: tid for tid, idx in self.track_id_to_idx.items()}
        self._tracks_by_popularity = [
            int(idx_to_track[i]) for i in np.argsort(self.track_pop)[::-1]
        ]

    # -- config passthrough (Manual.txt section 4) ---------------------------
    @property
    def n_artists_rec(self) -> int:
        return self.config.get("n_artists_candidates", 15)

    @property
    def tracks_per_artist(self) -> int:
        return self.config.get("tracks_per_artist_candidate", 10)

    @property
    def top_k_default(self) -> int:
        return self.config.get("top_k_final", 10)

    # -- building a user profile (Summary.md sections 3-7) -------------------
    def profile_from_id(self, user_id: int) -> UserProfile | None:
        """The real trained embeddings for a user present at training time --
        artist-space always exists if this returns non-None; track-space is
        included too when the user was also in the track model's training
        data (Manual.txt section 5: re-ranking is skipped otherwise)."""
        aidx = self._user_id_to_idx_artist.get(int(user_id))
        if aidx is None:
            return None
        tidx = self._user_id_to_idx_track.get(int(user_id))
        track_vec = self.track_user_emb[tidx] if tidx is not None else None
        return UserProfile(self.artist_user_emb[aidx], track_vec, "trained_embedding")

    def profile_from_artists(self, artist_ids: list[int]) -> UserProfile | None:
        """Average of the given artists' embeddings -- Manual.txt section 6.d,
        used for a user the engine has no trained embedding for, given the
        artists they've positively reacted to (directly, or via a track).
        No track-space vector: re-ranking falls back to popularity."""
        idxs = [self._artist_id_to_idx[int(a)] for a in artist_ids if int(a) in self._artist_id_to_idx]
        if not idxs:
            return None
        return UserProfile(self.artist_artist_emb[idxs].mean(axis=0), None, "reacted_artists")

    def profile_from_tracks(self, track_ids: list[int]) -> UserProfile | None:
        """Cold-start path (Manual.txt section 6): derive each onboarding
        track's primary artist via track_to_artist, then average those."""
        artist_ids = [
            self.track_to_artist[int(tid)] for tid in track_ids if int(tid) in self.track_to_artist
        ]
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
        """Blends the profile's artist-space vector a bit toward the liked
        track's artist embedding and/or away from the disliked one's, for a
        caller who wants to factor in behavioral signal for a single
        request. Mirrors v1's nudge_vector. Nothing here is written back to
        any stored embedding or model_params/ -- the returned profile is a
        fresh one-off. track_vec is left untouched: it's already the
        strongest available signal and section 7's single-user update only
        ever recomputes it from explicit reactions, never nudges it."""
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

    # -- the actual ensemble pipeline (Summary.md section 6) -----------------
    def recommend_from_profile(
        self,
        profile: UserProfile,
        exclude: set[int] | None = None,
        top_k: int | None = None,
        n_artists: int | None = None,
        tracks_per_artist: int | None = None,
    ) -> list[int]:
        top_k = top_k or self.top_k_default
        n_artists = min(n_artists or self.n_artists_rec, len(self.artist_enc.classes_))
        tracks_per_artist = tracks_per_artist or self.tracks_per_artist
        exclude = exclude or set()

        # Stage 1 -- artist ranking.
        scores = profile.artist_vec @ self.artist_artist_emb.T
        top_artist_idxs = np.argpartition(scores, -n_artists)[-n_artists:]
        top_artist_idxs = top_artist_idxs[np.argsort(scores[top_artist_idxs])[::-1]]

        # Stage 2a -- candidate collection (unseen tracks from those artists).
        candidates: set[int] = set()
        for aidx in top_artist_idxs:
            for tid in self._artist_to_tracks.get(int(aidx), [])[:tracks_per_artist]:
                if tid not in exclude:
                    candidates.add(tid)

        if not candidates:
            return []

        # Stage 2b -- track re-ranking if the user has a track-model
        # embedding, else fall back to popularity within the candidate pool
        # (Summary.md section 6.d / Manual.txt section 5.e).
        if profile.track_vec is not None:
            scored = []
            for tid in candidates:
                tidx = self._track_id_to_track_idx.get(int(tid))
                if tidx is not None:
                    scored.append((tid, float(profile.track_vec @ self.track_item_emb[tidx])))
            scored.sort(key=lambda kv: kv[1], reverse=True)
            ranked = [tid for tid, _ in scored]
        else:
            ranked = sorted(
                candidates,
                key=lambda t: self.track_pop[self.track_id_to_idx[t]],
                reverse=True,
            )

        return [int(tid) for tid in ranked[:top_k]]

    def popular_tracks(self, exclude: set[int] | None = None, top_k: int = 10) -> list[int]:
        """Last-resort fallback: no usable profile at all -- just the most
        popular tracks overall (Manual.txt's get_popular_unseen)."""
        exclude = exclude or set()
        out = [tid for tid in self._tracks_by_popularity if tid not in exclude]
        return out[:top_k]

    # -- cold-start onboarding (Manual.txt section 6) ------------------------
    def onboarding_tracks(self, count: int = 5, exclude: set[int] | None = None) -> list[int]:
        """`count` tracks from `count` different popular artists, for a
        brand-new user's very first session."""
        exclude = exclude or set()
        picked: list[int] = []
        for aidx in self._artists_by_popularity:
            candidate = next(
                (t for t in self._artist_to_tracks.get(int(aidx), []) if t not in exclude),
                None,
            )
            if candidate is None:
                continue
            picked.append(int(candidate))
            if len(picked) >= count:
                break
        return picked


def _load_pickle(path: Path):
    with open(path, "rb") as f:
        return pickle.load(f)
