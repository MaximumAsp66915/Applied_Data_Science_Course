"""The two-stage ensemble, rewritten.

The shape of the model is unchanged from engine_v2 and is not up for debate
here: an artist-level hybrid MF shortlists artists, a track-level MF re-ranks
the unseen tracks from those artists. That design is sound, and the reasoning
behind it (artist-level signal is far denser than track-level signal on a
1.7%-dense interaction matrix) still holds.

What changed is the *serving* logic around it. Each departure from
engine_v2's ``recommender.py`` is marked ``[FIX n]`` and written up in full
in ANALYSIS.md:

  [FIX 1] Candidates are filtered against ``exclude`` *before* the
          per-artist cap, not after. engine_v2 truncated first, so a user who
          had already heard an artist's top 10 tracks got zero candidates
          from that artist even when it had 129 of them.
  [FIX 2] The artist shortlist widens (x1, x2, x4, x8) when the pool comes up
          empty, instead of dropping straight to global popularity. This is
          what engine_v2's own Manual.txt section 5 prescribes and its code
          never did.
  [FIX 3] Stage 1 includes the trained per-artist bias, so serving optimises
          the same function training did.
  [FIX 4] Stage 2 is one matmul over the candidate pool instead of a Python
          loop of per-track dot products.
  [FIX 5] Candidates with no track embedding are scored by popularity prior
          instead of being silently dropped from the pool.
  [FIX 6] Tracks with no reactions yet are eligible candidates. In engine_v2
          they were unreachable: 2,410 of 14,843 tracks, permanently.
  [FIX 7] A diversity cap limits how many tracks by one artist can appear in
          a single response. engine_v2's own notebook shows a user being
          handed five consecutive Eminem tracks.
  [FIX 8] A known user's live reactions still move their profile, per
          Manual.txt section 7, instead of being ignored because a stale
          trained vector exists.
  [FIX 9] Centroid-built (cold-start) profiles are rescaled to the trained
          user vectors' norm, so the popularity prior and the model score are
          combined on the same scale for warm and cold users alike.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from artifacts import Params
from config import ServingConfig

# Ranked-list provenance, surfaced as the ``source`` field of the API
# response. Values are unchanged from engine_v2 so the app's existing
# handling keeps working; "blended" is new and additive.
SOURCE_TRAINED = "trained_embedding"
SOURCE_BLENDED = "blended_profile"
SOURCE_ARTISTS = "reacted_artists"
SOURCE_TRACKS = "reacted_tracks"
SOURCE_POPULAR = "popular_fallback"


@dataclass
class UserProfile:
    """A user's position in the two embedding spaces the ensemble uses.

    ``artist_vec`` drives stage 1 and is always present. ``track_vec`` drives
    stage 2 and is optional: a user who has reactions but was not in the track
    model's training snapshot has no track-space vector, and their candidates
    get ranked by the popularity prior alone.
    """

    artist_vec: np.ndarray
    track_vec: np.ndarray | None
    source: str


@dataclass
class Recommendation:
    """One ranked response, with enough context to explain itself."""

    track_ids: list[int]
    source: str
    pool_size: int
    widen_steps: int
    reranked: bool


class Recommender:
    def __init__(self, params: Params, config: ServingConfig):
        self.params = params
        self.config = config

        # Stage-1 scoring operand, assembled once. Folding the bias in as an
        # extra dimension turns "dot product plus bias" into a single matmul
        # and keeps the hot path free of branches. [FIX 3]
        bias = params.artist_bias.astype(np.float32) * np.float32(config.artist_bias_weight)
        self._artist_matrix = np.ascontiguousarray(
            np.hstack([params.artist_item_emb, bias.reshape(-1, 1)]).T
        )  # (d_a + 1, n_artists)

        # Popularity prior, precomputed on the log scale and squashed to
        # [0, 1] so `pop_prior_weight` means the same thing across retrains
        # regardless of how large raw reaction counts have grown.
        pop = params.catalogue_pop.astype(np.float32)
        log_pop = np.log1p(pop)
        span = float(log_pop.max()) or 1.0
        self._pop_prior = {
            int(t): float(p / span) for t, p in zip(params.catalogue_track_ids, log_pop)
        }

    # ------------------------------------------------------------- profiles
    def profile_from_user_id(self, user_id: int) -> UserProfile | None:
        """The trained profile for a user present in the artist model."""
        row = self.params.user_row_artist.get(int(user_id))
        if row is None:
            return None
        track_row = self.params.user_row_track.get(int(user_id))
        track_vec = self.params.track_user_emb[track_row] if track_row is not None else None
        return UserProfile(self.params.artist_user_emb[row], track_vec, SOURCE_TRAINED)

    def profile_from_artists(self, artist_ids: list[int]) -> UserProfile | None:
        """Centroid of the given artists' embeddings.

        The standard cold-start trick: an item centroid stands in for a user
        vector. It only works if the scales match, which is why the result is
        renormalised to the trained users' average norm. [FIX 9]
        """
        rows = [self.params.artist_row[int(a)] for a in artist_ids if int(a) in self.params.artist_row]
        if not rows:
            return None
        vec = self.params.artist_item_emb[rows].mean(axis=0)
        return UserProfile(self._rescale(vec), None, SOURCE_ARTISTS)

    def profile_from_tracks(self, track_ids: list[int]) -> UserProfile | None:
        """Cold start from reacted tracks: resolve each to its primary artist,
        then take the artist centroid. Also builds a track-space vector from
        the tracks that have embeddings, which engine_v2 never did even though
        Manual.txt section 7 describes exactly this."""
        artist_ids = [
            self.params.track_artist[int(t)]
            for t in track_ids
            if self.params.track_artist.get(int(t), -1) != -1
        ]
        profile = self.profile_from_artists(artist_ids) if artist_ids else None
        track_vec = self._track_centroid(track_ids)
        if profile is None:
            if track_vec is None:
                return None
            # No usable artist signal, but the tracks themselves are known:
            # fall back to an all-zero artist vector, which makes stage 1 rank
            # purely on artist bias (i.e. popularity), and let stage 2 do the
            # real work.
            zero = np.zeros(self.params.artist_item_emb.shape[1], dtype=np.float32)
            return UserProfile(zero, track_vec, SOURCE_TRACKS)
        return UserProfile(profile.artist_vec, track_vec, SOURCE_TRACKS)

    def build_profile(
        self,
        user_id: int | None = None,
        reacted_artist_ids: list[int] | None = None,
        reacted_track_ids: list[int] | None = None,
    ) -> UserProfile | None:
        """Best available signal, with the live signal folded in. [FIX 8]

        engine_v2 stopped at the first source that produced anything, so a
        known user's trained vector -- up to a week stale -- shadowed the
        reactions they had left five minutes ago. Here the trained vector is
        still the backbone, but fresh reactions pull it, weighted by
        ``fresh_signal_weight``.
        """
        reacted_artist_ids = reacted_artist_ids or []
        reacted_track_ids = reacted_track_ids or []

        trained = self.profile_from_user_id(user_id) if user_id is not None else None
        fresh_artists = list(reacted_artist_ids)
        fresh_artists += [
            self.params.track_artist[int(t)]
            for t in reacted_track_ids
            if self.params.track_artist.get(int(t), -1) != -1
        ]
        fresh = self.profile_from_artists(fresh_artists) if fresh_artists else None

        if trained is None:
            if fresh is not None:
                source = SOURCE_ARTISTS if reacted_artist_ids else SOURCE_TRACKS
                track_vec = self._track_centroid(reacted_track_ids)
                return UserProfile(fresh.artist_vec, track_vec, source)
            return self.profile_from_tracks(reacted_track_ids) if reacted_track_ids else None

        if fresh is None or self.config.fresh_signal_weight <= 0:
            return trained

        w = np.float32(self.config.fresh_signal_weight)
        blended = (1 - w) * trained.artist_vec + w * fresh.artist_vec
        return UserProfile(blended, trained.track_vec, SOURCE_BLENDED)

    def nudge(
        self,
        profile: UserProfile,
        liked_track_id: int | None = None,
        disliked_track_id: int | None = None,
    ) -> UserProfile:
        """One-request-only implicit-feedback tilt (played to the end vs.
        skipped). Never persisted anywhere.

        engine_v2 applied ``v = (1-a)*v +/- a*e`` per signal, which shrinks the
        profile's norm on every dislike and drifts it toward the origin when
        both signals fire. Here the positive step interpolates and the negative
        step subtracts only the component along the disliked artist, which
        leaves the rest of the taste vector untouched.
        """
        vec = profile.artist_vec.astype(np.float32, copy=True)
        alpha = np.float32(self.config.nudge_weight)

        liked = self._artist_vec_for_track(liked_track_id)
        if liked is not None:
            vec = (1 - alpha) * vec + alpha * liked

        disliked = self._artist_vec_for_track(disliked_track_id)
        if disliked is not None:
            unit = disliked / (np.linalg.norm(disliked) or 1.0)
            vec = vec - alpha * float(vec @ unit) * unit

        return replace(profile, artist_vec=vec)

    # -------------------------------------------------------------- ranking
    def recommend(
        self,
        profile: UserProfile | None,
        exclude: set[int] | None = None,
        top_k: int | None = None,
        n_artists: int | None = None,
    ) -> Recommendation:
        """Run the full pipeline and return a ranked list of track ids."""
        cfg = self.config
        top_k = int(top_k or cfg.top_k_default)
        exclude = exclude or set()

        if profile is None:
            return Recommendation(
                self.popular_tracks(exclude, top_k), SOURCE_POPULAR, 0, 0, False
            )

        base_n = int(n_artists or cfg.n_artist_candidates)
        scores = self._artist_scores(profile.artist_vec)
        scores = self._damp_seen_artists(scores, exclude)

        # [FIX 2] widen the shortlist until the pool can actually fill the
        # request, rather than bailing to global popularity on the first miss.
        candidates: np.ndarray = np.empty(0, dtype=np.int64)
        widen_steps = 0
        for step, factor in enumerate(cfg.widen_factors):
            widen_steps = step
            n = min(base_n * factor, len(self.params.artist_ids))
            candidates = self._collect_candidates(scores, n, exclude)
            if len(candidates) >= top_k:
                break

        if len(candidates) == 0:
            return Recommendation(
                self.popular_tracks(exclude, top_k), SOURCE_POPULAR, 0, widen_steps, False
            )

        ranked, reranked = self._rank_candidates(candidates, profile.track_vec)
        ranked = self._diversify(ranked, top_k)

        # A widened search can still fall short of top_k on a small catalogue;
        # top up from global popularity rather than returning a short list.
        if len(ranked) < top_k:
            seen = set(ranked) | exclude
            ranked += [t for t in self.popular_tracks(seen, top_k - len(ranked))]

        return Recommendation(
            [int(t) for t in ranked[:top_k]],
            profile.source,
            int(len(candidates)),
            widen_steps,
            reranked,
        )

    def suggest_one(
        self,
        profile: UserProfile | None,
        exclude: set[int] | None = None,
        rng: np.random.Generator | None = None,
    ) -> Recommendation:
        """A single next-track pick.

        With ``explore_temperature`` at 0 this is just the head of
        ``recommend``. Above 0 it samples from a softmax over the top of the
        ranked list, so a caller that asks the same question twice in a row
        does not necessarily get the same answer -- engine_v2's ``/suggest``
        was fully deterministic, which put a user with no ``exclude`` list in
        a one-track loop.
        """
        depth = max(1, self.config.top_k_default)
        result = self.recommend(profile, exclude=exclude, top_k=depth)
        if not result.track_ids:
            return replace(result, track_ids=[])

        temperature = self.config.explore_temperature
        if temperature <= 0 or len(result.track_ids) == 1:
            return replace(result, track_ids=result.track_ids[:1])

        rng = rng or np.random.default_rng()
        ranks = np.arange(len(result.track_ids), dtype=np.float32)
        weights = np.exp(-ranks / np.float32(temperature))
        weights /= weights.sum()
        pick = int(rng.choice(len(result.track_ids), p=weights))
        return replace(result, track_ids=[result.track_ids[pick]])

    def popular_tracks(self, exclude: set[int] | None = None, top_k: int = 10) -> list[int]:
        """Last-resort fallback: no usable profile, or nothing survived the
        candidate stage."""
        exclude = exclude or set()
        out: list[int] = []
        for track_id in self.params.tracks_by_popularity:
            tid = int(track_id)
            if tid in exclude:
                continue
            out.append(tid)
            if len(out) >= top_k:
                break
        return out

    def onboarding_tracks(self, count: int = 5, exclude: set[int] | None = None) -> list[int]:
        """First-session picks: `count` tracks from `count` different artists.

        engine_v2 walked artists by the *sum* of their tracks' popularity,
        which ranks by catalogue size as much as by appeal, and applied no
        diversity constraint at all -- so the five picks tended to be five
        neighbours in one corner of the embedding space. Here artists are
        walked by their best track's popularity, and a candidate artist is
        skipped if it is too close to one already chosen.
        """
        exclude = exclude or set()
        emb = self.params.artist_item_emb

        def walk(similarity_cutoff: float, picked: list[int], used_rows: set[int]) -> None:
            chosen_vecs = [emb[r] for r in used_rows]
            for row in self.params.artists_by_reach:
                if len(picked) >= count:
                    return
                row = int(row)
                if row in used_rows:
                    continue
                tracks = self.params.artist_tracks.get(row)
                if tracks is None or len(tracks) == 0:
                    continue
                track_id = next((int(t) for t in tracks if int(t) not in exclude), None)
                if track_id is None:
                    continue

                vec = emb[row]
                norm = float(np.linalg.norm(vec)) or 1.0
                too_close = any(
                    float(vec @ other) / (norm * (float(np.linalg.norm(other)) or 1.0))
                    > similarity_cutoff
                    for other in chosen_vecs
                )
                if too_close:
                    continue

                picked.append(track_id)
                used_rows.add(row)
                chosen_vecs.append(vec)

        picked: list[int] = []
        used_rows: set[int] = set()
        walk(0.6, picked, used_rows)
        if len(picked) < count:
            # The similarity filter can be too strict on a small catalogue.
            # Relaxing it is fine; returning two tracks by the same artist is
            # not, since "different artists" is the whole point of the
            # onboarding set -- so a short list is the honest outcome.
            walk(1.0, picked, used_rows)
        return picked

    # -------------------------------------------------------------- internals
    def _artist_scores(self, artist_vec: np.ndarray) -> np.ndarray:
        """user . artist + artist_bias, for every artist, in one matmul."""
        query = np.append(artist_vec.astype(np.float32), np.float32(1.0))
        return query @ self._artist_matrix

    def _damp_seen_artists(self, scores: np.ndarray, exclude: set[int]) -> np.ndarray:
        """Push down artists the caller has already been served a lot of.

        The engine holds no session state, but ``exclude_track_ids`` carries
        the same information: an artist with many excluded tracks has had its
        turn. Without this, one deep catalogue can own an entire listening
        session -- the failure engine_v2's own notebook output shows.
        """
        damping = self.config.session_damping
        if damping <= 0 or not exclude:
            return scores

        counts: dict[int, int] = {}
        for track_id in exclude:
            row = self.params.artist_row.get(self.params.track_artist.get(int(track_id), -1))
            if row is not None:
                counts[row] = counts.get(row, 0) + 1
        if not counts:
            return scores

        scores = scores.copy()
        rows = np.fromiter(counts.keys(), dtype=np.int64, count=len(counts))
        seen = np.fromiter(counts.values(), dtype=np.float32, count=len(counts))
        scores[rows] -= np.float32(damping) * np.log1p(seen)
        return scores

    def _collect_candidates(
        self, scores: np.ndarray, n_artists: int, exclude: set[int]
    ) -> np.ndarray:
        n_artists = max(1, min(n_artists, len(scores)))
        if n_artists >= len(scores):
            top_rows = np.argsort(-scores, kind="stable")
        else:
            top_rows = np.argpartition(-scores, n_artists - 1)[:n_artists]
            top_rows = top_rows[np.argsort(-scores[top_rows], kind="stable")]

        cap = self.config.tracks_per_artist
        keep_unscored = self.config.include_unscored_tracks
        seen: set[int] = set()
        pool: list[int] = []
        for row in top_rows:
            tracks = self.params.artist_tracks.get(int(row))
            if tracks is None:
                continue
            taken = 0
            # [FIX 1] exclusion happens inside the loop, before the cap bites.
            for track_id in tracks:
                tid = int(track_id)
                if tid in exclude or tid in seen:
                    continue
                # [FIX 6] a zero-reaction track is a legitimate candidate.
                if not keep_unscored and tid not in self.params.track_row:
                    continue
                pool.append(tid)
                seen.add(tid)
                taken += 1
                if taken >= cap:
                    break
        return np.array(pool, dtype=np.int64)

    def _rank_candidates(
        self, candidates: np.ndarray, track_vec: np.ndarray | None
    ) -> tuple[list[int], bool]:
        """Score the pool and sort it. Returns (ranked ids, used_track_model)."""
        prior = np.array(
            [self._pop_prior.get(int(t), 0.0) for t in candidates], dtype=np.float32
        )

        if track_vec is None:
            order = np.argsort(-prior, kind="stable")
            return [int(candidates[i]) for i in order], False

        # [FIX 4] one matmul for the whole pool.
        rows = np.array([self.params.track_row.get(int(t), -1) for t in candidates])
        has_emb = rows >= 0
        model = np.zeros(len(candidates), dtype=np.float32)
        if has_emb.any():
            model[has_emb] = self.params.track_item_emb[rows[has_emb]] @ track_vec.astype(np.float32)
            # Standardise within the pool so the popularity prior's weight is
            # interpretable regardless of embedding scale.
            sub = model[has_emb]
            std = float(sub.std()) or 1.0
            model[has_emb] = (sub - float(sub.mean())) / std
        # [FIX 5] no embedding is not a reason to drop a candidate: park it at
        # the pool mean and let the popularity prior break the tie.
        model[~has_emb] = 0.0

        score = model + np.float32(self.config.pop_prior_weight) * prior
        order = np.argsort(-score, kind="stable")
        return [int(candidates[i]) for i in order], bool(has_emb.any())

    def _diversify(self, ranked: list[int], top_k: int) -> list[int]:
        """[FIX 7] Cap how many tracks by one artist reach the response."""
        cap = self.config.max_tracks_per_artist_in_result
        if cap <= 0:
            return ranked

        counts: dict[int, int] = {}
        kept, overflow = [], []
        for track_id in ranked:
            artist = self.params.track_artist.get(track_id, -1)
            if artist != -1 and counts.get(artist, 0) >= cap:
                overflow.append(track_id)
                continue
            counts[artist] = counts.get(artist, 0) + 1
            kept.append(track_id)
            if len(kept) >= top_k:
                return kept
        # Only relax the cap if honouring it would return a short list.
        return kept + overflow

    def _track_centroid(self, track_ids: list[int]) -> np.ndarray | None:
        rows = [self.params.track_row[int(t)] for t in track_ids if int(t) in self.params.track_row]
        if not rows:
            return None
        return self.params.track_item_emb[rows].mean(axis=0).astype(np.float32)

    def _artist_vec_for_track(self, track_id: int | None) -> np.ndarray | None:
        if track_id is None:
            return None
        artist_id = self.params.track_artist.get(int(track_id), -1)
        row = self.params.artist_row.get(artist_id) if artist_id != -1 else None
        return self.params.artist_item_emb[row] if row is not None else None

    def _rescale(self, vec: np.ndarray) -> np.ndarray:
        vec = vec.astype(np.float32, copy=False)
        if not self.config.scale_cold_start_profile:
            return vec
        norm = float(np.linalg.norm(vec))
        if norm == 0:
            return vec
        return vec * np.float32(self.params.mean_user_norm / norm)
