"""Loads the artifacts under model_params/ (see manual.txt) once and answers
recommendation queries against them. Pure numpy/pickle -- deliberately does
NOT load model_state.pt or import torch: manual.txt's own pipeline (section
4) never calls the model's forward() again, it only ever does
`user_vector @ artist_emb.T` against the already-exported embedding
matrices. Keeping torch out of this process's venv (see requirements.txt)
means a much lighter install on the server for something that's read-only
inference over a handful of numpy arrays.

This module has no FastAPI/HTTP awareness at all -- main.py is the only
thing that imports it and turns it into endpoints. Keeping the split makes
the actual recommendation logic testable/tweakable without dragging a web
server into it, and matches the notebook's own separation between "the
pipeline" (section 4) and "how the bot calls it" (section 6).
"""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np


class Recommender:
    def __init__(self, params_dir: Path):
        self.params_dir = params_dir
        with open(params_dir / "config.json") as f:
            self.config = json.load(f)

        self.user_enc = _load_pickle(params_dir / "user_enc.pkl")
        self.artist_enc = _load_pickle(params_dir / "artist_enc.pkl")
        self.track_to_artist: dict[int, int] = _load_pickle(params_dir / "track_to_artist.pkl")
        self.track_id_to_idx: dict[int, int] = _load_pickle(params_dir / "track_id_to_idx.pkl")

        self.track_pop = np.load(params_dir / "track_pop.npy")
        self.user_emb = np.load(params_dir / "user_embeddings.npy")
        self.artist_emb = np.load(params_dir / "artist_embeddings.npy")

        # LabelEncoder.classes_ is "index -> original id"; these are the
        # reverse lookups (original id -> index) the pipeline actually needs
        # on every call, built once here instead of re-deriving them (or
        # calling the comparatively slow .transform()) per request.
        self._user_id_to_idx = {int(uid): i for i, uid in enumerate(self.user_enc.classes_)}
        self._artist_id_to_idx = {int(aid): i for i, aid in enumerate(self.artist_enc.classes_)}

        # artist_idx -> [track_id, ...], sorted by popularity descending --
        # manual.txt section 4.g/d precomputed once at load time rather than
        # rebuilt on every request.
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
        # most popular first -- used only for cold-start onboarding (manual
        # section 5: "pre-choose from the artists with the highest total
        # track_pop across their tracks").
        artist_total_pop = np.zeros(len(self.artist_enc.classes_))
        for aidx, tids in by_artist.items():
            artist_total_pop[aidx] = sum(self.track_pop[self.track_id_to_idx[t]] for t in tids)
        self._artists_by_popularity = list(np.argsort(artist_total_pop)[::-1])

        # Track ids ordered by raw popularity, most popular first -- the
        # fallback used whenever there's no usable signal at all (brand new
        # user, unknown artists/tracks, or just SUGGESTION_ENGINE_URL being
        # probed with nothing).
        idx_to_track = {idx: tid for tid, idx in self.track_id_to_idx.items()}
        self._tracks_by_popularity = [
            int(idx_to_track[i]) for i in np.argsort(self.track_pop)[::-1]
        ]

    # -- config passthrough (manual.txt section 1) --------------------------
    @property
    def n_artists_rec(self) -> int:
        return self.config.get("n_artists_rec", 5)

    @property
    def tracks_per_artist(self) -> int:
        return self.config.get("tracks_per_artist", 5)

    @property
    def top_k_default(self) -> int:
        return self.config.get("top_k", 10)

    # -- building a user vector (manual.txt section 3) -----------------------
    def user_vector_from_id(self, user_id: int) -> np.ndarray | None:
        """The real trained embedding for a user who was present at training
        time -- always preferred over an averaged vector when available."""
        idx = self._user_id_to_idx.get(int(user_id))
        return None if idx is None else self.user_emb[idx]

    def user_vector_from_artists(self, artist_ids: list[int]) -> np.ndarray | None:
        """Average of the given artists' embeddings -- used for a user the
        engine has no trained embedding for, given the artists they've
        positively reacted to (directly, or via one of their tracks)."""
        idxs = [self._artist_id_to_idx[int(a)] for a in artist_ids if int(a) in self._artist_id_to_idx]
        if not idxs:
            return None
        return self.artist_emb[idxs].mean(axis=0)

    def user_vector_from_tracks(self, track_ids: list[int]) -> np.ndarray | None:
        """Cold-start path (manual.txt section 5): derive each onboarding
        track's primary artist via track_to_artist, then average those."""
        artist_ids = [
            self.track_to_artist[int(tid)] for tid in track_ids if int(tid) in self.track_to_artist
        ]
        return self.user_vector_from_artists(artist_ids) if artist_ids else None

    # -- the actual pipeline (manual.txt section 4) --------------------------
    def recommend_from_vector(
        self,
        user_vector: np.ndarray,
        exclude: set[int] | None = None,
        top_k: int | None = None,
        n_artists: int | None = None,
        tracks_per_artist: int | None = None,
    ) -> list[int]:
        top_k = top_k or self.top_k_default
        n_artists = min(n_artists or self.n_artists_rec, len(self.artist_enc.classes_))
        tracks_per_artist = tracks_per_artist or self.tracks_per_artist
        exclude = exclude or set()

        scores = user_vector @ self.artist_emb.T
        top_artist_idxs = np.argpartition(scores, -n_artists)[-n_artists:]
        top_artist_idxs = top_artist_idxs[np.argsort(scores[top_artist_idxs])[::-1]]

        candidates: dict[int, float] = {}
        for aidx in top_artist_idxs:
            for tid in self._artist_to_tracks.get(int(aidx), [])[:tracks_per_artist]:
                if tid in exclude:
                    continue
                candidates[tid] = self.track_pop[self.track_id_to_idx[tid]]

        ranked = sorted(candidates.items(), key=lambda kv: kv[1], reverse=True)
        return [int(tid) for tid, _ in ranked[:top_k]]

    def popular_tracks(self, exclude: set[int] | None = None, top_k: int = 10) -> list[int]:
        """Last-resort fallback: no usable vector at all (brand new user,
        nothing recognized) -- just the most popular tracks overall."""
        exclude = exclude or set()
        out = [tid for tid in self._tracks_by_popularity if tid not in exclude]
        return out[:top_k]

    # -- cold-start onboarding (manual.txt section 5) ------------------------
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
