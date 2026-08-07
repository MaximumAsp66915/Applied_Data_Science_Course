"""Behavioural A/B between engine_v2's serving logic and this one.

    python tools/benchmark.py

No ground-truth labels are involved, and that is deliberate. The interaction
CSVs are not in the repository, and the accuracy numbers engine_v2 published
are not trustworthy anyway (see ``evaluation.py``'s docstring). What *can* be
measured from the shipped artifacts alone is how the two serving algorithms
behave -- and the problems found in engine_v2 are behavioural, so this is the
measurement that matters:

* **exhaustion** -- how often a request falls all the way through to global
  popularity because the candidate pool came up empty,
* **artist concentration** -- how many distinct artists a user sees over a
  session of consecutive picks,
* **catalogue coverage** -- what share of the 14,843 tracks the engine is
  capable of ever returning,
* **latency** -- per-request wall time.

``V2Baseline`` below is a faithful reimplementation of
``engine_v2/recommender.py``'s ``recommend_from_profile`` -- same truncate-
then-exclude order, same drop of candidates without a track embedding, same
absence of widening, bias and diversity. It exists so the comparison is
against what v2 actually does, not against a straw man.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from artifacts import Params, load_params, resolve_params_dir  # noqa: E402
from config import ServingConfig, load_config  # noqa: E402
from evaluation import gini  # noqa: E402
from recommender import Recommender, UserProfile  # noqa: E402


class V2Baseline:
    """engine_v2/recommender.py's ranking, reimplemented over the same Params."""

    def __init__(self, params: Params, n_artists: int = 20, tracks_per_artist: int = 10):
        self.p = params
        self.n_artists = n_artists
        self.tracks_per_artist = tracks_per_artist
        # v2 only ever indexed tracks that appear in track_pop.
        self.artist_tracks = {
            row: [int(t) for t in tracks if int(t) in params.track_row]
            for row, tracks in params.artist_tracks.items()
        }
        self.tracks_by_pop = [
            int(t) for t in params.tracks_by_popularity if int(t) in params.track_row
        ]

    def recommend(self, profile: UserProfile, exclude: set[int], top_k: int) -> tuple[list[int], str]:
        # Stage 1: dot product only, no artist bias.
        scores = profile.artist_vec @ self.p.artist_item_emb.T
        n = min(self.n_artists, len(scores))
        rows = np.argpartition(scores, -n)[-n:]
        rows = rows[np.argsort(scores[rows])[::-1]]

        # Stage 2a: truncate to tracks_per_artist FIRST, then drop excluded.
        candidates: set[int] = set()
        for row in rows:
            for track_id in self.artist_tracks.get(int(row), [])[: self.tracks_per_artist]:
                if track_id not in exclude:
                    candidates.add(track_id)

        if not candidates:
            return self._popular(exclude, top_k), "popular_fallback"

        if profile.track_vec is not None:
            scored = []
            for track_id in candidates:
                row = self.p.track_row.get(track_id)
                if row is not None:  # candidates without an embedding are dropped
                    scored.append((track_id, float(profile.track_vec @ self.p.track_item_emb[row])))
            scored.sort(key=lambda kv: kv[1], reverse=True)
            ranked = [t for t, _ in scored]
        else:
            ranked = sorted(candidates, key=lambda t: self.p.pop_by_track.get(t, 0.0), reverse=True)

        return [int(t) for t in ranked[:top_k]], profile.source

    def _popular(self, exclude: set[int], top_k: int) -> list[int]:
        return [t for t in self.tracks_by_pop if t not in exclude][:top_k]


def _session(engine, params: Params, user_id: int, length: int, is_v2: bool, rng=None):
    """Simulate `length` consecutive one-track requests for one user.

    Each engine is driven through the code path its own ``/suggest`` endpoint
    uses -- ``recommend_from_profile(top_k=1)`` for v2, ``suggest_one`` for the
    R&D engine -- so the numbers describe the endpoints as deployed, not an
    idealised inner function.
    """
    profile = (
        engine.profile_from_user_id(user_id)
        if not is_v2
        else _v2_profile(params, user_id)
    )
    if profile is None:
        return None

    seen: set[int] = set()
    picks: list[int] = []
    fallbacks = 0
    latencies: list[float] = []

    for _ in range(length):
        started = time.perf_counter()
        if is_v2:
            ranked, source = engine.recommend(profile, seen, 1)
        else:
            result = engine.suggest_one(profile, exclude=seen, rng=rng)
            ranked, source = result.track_ids, result.source
        latencies.append((time.perf_counter() - started) * 1000)

        if source == "popular_fallback":
            fallbacks += 1
        if not ranked:
            break
        picks.append(ranked[0])
        seen.add(ranked[0])

    artists = {params.track_artist.get(t, -1) for t in picks}
    return {
        "picks": picks,
        "distinct_artists": len(artists),
        "fallbacks": fallbacks,
        "latencies": latencies,
    }


def _v2_profile(params: Params, user_id: int) -> UserProfile | None:
    row = params.user_row_artist.get(int(user_id))
    if row is None:
        return None
    track_row = params.user_row_track.get(int(user_id))
    return UserProfile(
        params.artist_user_emb[row],
        params.track_user_emb[track_row] if track_row is not None else None,
        "trained_embedding",
    )


def run(params: Params, config: ServingConfig, n_users: int, session_length: int, seed: int):
    rng = np.random.default_rng(seed)
    user_pool = params.user_ids_artist
    sample = rng.choice(user_pool, size=min(n_users, len(user_pool)), replace=False)

    engines = {
        "engine_v2": (V2Baseline(params, config.n_artist_candidates, config.tracks_per_artist), True),
        "engine_rnd": (Recommender(params, config), False),
    }

    report = {}
    for name, (engine, is_v2) in engines.items():
        distinct, fallbacks, latencies = [], [], []
        exposure: dict[int, int] = {}
        short_sessions = 0

        session_rng = np.random.default_rng(seed)
        for user_id in sample:
            outcome = _session(engine, params, int(user_id), session_length, is_v2, session_rng)
            if outcome is None:
                continue
            distinct.append(outcome["distinct_artists"])
            fallbacks.append(outcome["fallbacks"])
            latencies.extend(outcome["latencies"])
            if len(outcome["picks"]) < session_length:
                short_sessions += 1
            for track in outcome["picks"]:
                exposure[track] = exposure.get(track, 0) + 1

        # A single top-10 batch, which is what /recommend serves: how many
        # different artists does one response contain? This is the number
        # engine_v2's own notebook failed, handing one user five Eminem
        # tracks in a row.
        batch_artists = []
        for user_id in sample:
            profile = (
                _v2_profile(params, int(user_id))
                if is_v2
                else engine.profile_from_user_id(int(user_id))
            )
            if profile is None:
                continue
            ranked = (
                engine.recommend(profile, set(), 10)[0]
                if is_v2
                else engine.recommend(profile, exclude=set(), top_k=10).track_ids
            )
            if ranked:
                batch_artists.append(len({params.track_artist.get(t, -1) for t in ranked}))

        report[name] = {
            "users": len(distinct),
            "session_length": session_length,
            "distinct_artists_in_top10": round(statistics.mean(batch_artists), 2)
            if batch_artists
            else 0,
            "top10_responses_from_one_artist": sum(1 for n in batch_artists if n == 1),
            "distinct_artists_per_session": round(statistics.mean(distinct), 2) if distinct else 0,
            "fallback_requests_pct": round(100 * sum(fallbacks) / max(1, len(fallbacks) * session_length), 2),
            "sessions_that_ran_short": short_sessions,
            "distinct_tracks_served": len(exposure),
            "catalogue_coverage_pct": round(
                100 * len(exposure) / len(params.catalogue_track_ids), 2
            ),
            "exposure_gini": round(gini(list(exposure.values())), 3) if exposure else 0.0,
            "latency_p50_ms": round(statistics.median(latencies), 3) if latencies else 0,
            "latency_p95_ms": round(
                statistics.quantiles(latencies, n=20)[-1], 3
            ) if len(latencies) > 20 else 0,
        }

    # Reachability is a property of the algorithm, not of any one session.
    v2_reachable = {
        int(t)
        for row, tracks in params.artist_tracks.items()
        for t in tracks
        if int(t) in params.track_row
    }
    rnd_reachable = {int(t) for tracks in params.artist_tracks.values() for t in tracks}
    report["reachability"] = {
        "catalogue": int(len(params.catalogue_track_ids)),
        "reachable_engine_v2": len(v2_reachable),
        "reachable_engine_rnd": len(rnd_reachable),
        "unreachable_engine_v2": int(len(params.catalogue_track_ids) - len(v2_reachable)),
        "unreachable_engine_rnd": int(len(params.catalogue_track_ids) - len(rnd_reachable)),
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--params-dir", default=None)
    parser.add_argument("--users", type=int, default=300, help="how many users to simulate")
    parser.add_argument("--session-length", type=int, default=20, help="picks per user")
    parser.add_argument("--seed", type=int, default=43)
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parent.parent
    params = load_params(resolve_params_dir(base, args.params_dir))
    config = load_config(params.manifest.get("serving"))
    report = run(params, config, args.users, args.session_length, args.seed)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
