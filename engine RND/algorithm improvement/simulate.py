"""End-to-end validation: does the loop actually learn anything?

    python "algorithm improvement/simulate.py" --users 200 --rounds 40

A learning system that is never shown to learn is an elaborate way to add
latency. This runs the real components -- the real `Learner`, the real bandit,
the real `Recommender` over the real trained artifacts -- against simulated
listeners, and reports whether mean reward rises over time and whether the arm
distribution shifts towards arms that suit each listener.

## What is simulated, and what is not

Simulated: **the listener**. Each has a latent taste vector drawn from the real
artist embedding space, a patience parameter, and an appetite for novelty. Their
probability of finishing a track is

    P(complete) = sigmoid(k * (taste . artist_hat - threshold) + novelty_bonus)

with a repetition penalty that grows as they are served the same artist again.
That last term is what makes the exercise meaningful: it creates a population
for whom `deep_cut` is right and another for whom `diversify` is right, so
there is genuinely something for a contextual bandit to discover.

Not simulated: everything else. The engine, the bandit, the reward model, the
attribution path and the persistence layer are the production objects.

## What this does and does not prove

It proves the machinery is wired correctly: rewards flow back, attribution
matches, the bandit's estimates move in the right direction, per-user deltas
change what gets served, and the whole thing survives a save/load cycle.

It does **not** prove the engine will improve for real listeners. The simulator
generates data from the same embeddings the engine ranks with, so it is a
friendlier world than reality -- a point worth keeping in mind, given that
overstating an evaluation is precisely the failure this project already
documented once (ANALYSIS.md, E-4). Real evidence needs `offline_eval.py` on
production logs.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

ENGINE_DIR = Path(__file__).resolve().parent.parent
for path in (str(ENGINE_DIR), str(ENGINE_DIR / "algorithm improvement")):
    if path not in sys.path:
        sys.path.insert(0, path)

from artifacts import load_params, resolve_params_dir  # noqa: E402
from config import load_config  # noqa: E402
from recommender import Recommender  # noqa: E402
from learner import LearnerConfig  # noqa: E402
from service import ImprovementLayer  # noqa: E402


class SimulatedListener:
    """A synthetic user with a taste, a tolerance for repetition, and a mood.

    `drift` is the most important parameter here and the easiest to get wrong.
    The first version of this simulator set each listener's true taste equal to
    their trained embedding -- which quietly made the exercise unwinnable: the
    engine's stored profile was already ground truth, so *any* online
    personalisation could only move it away from the right answer, and the
    measurement showed learning losing to no-learning by construction.

    That is not the situation in production. A user's trained vector is a
    point estimate fitted on a sparse snapshot, and it is up to a week stale by
    the time it serves. `drift` models both errors: the true taste is the
    trained vector pushed a fraction of the way toward a random direction. At
    `drift = 0` there is nothing for online learning to find; at `drift = 1`
    the stored profile is worthless. The default sits between, which is the
    regime the whole feature exists for.
    """

    def __init__(
        self,
        user_id: int,
        taste: np.ndarray,
        rng: np.random.Generator,
        drift: float = 0.5,
    ):
        self.user_id = user_id
        base = taste / (np.linalg.norm(taste) or 1.0)
        if drift > 0:
            direction = rng.normal(size=base.shape)
            direction /= np.linalg.norm(direction) or 1.0
            base = (1.0 - drift) * base + drift * direction
        self.taste = base / (np.linalg.norm(base) or 1.0)
        # Two dispositions the arms differ on. `variety_seeking` decides whether
        # hearing the same artist again is a bonus or a penalty, which is what
        # makes deep_cut and diversify genuinely different answers.
        self.variety_seeking = float(rng.uniform(0.0, 1.0))
        self.patience = float(rng.uniform(0.5, 2.5))
        self.seen: set[int] = set()
        self.artist_counts: dict[int, int] = {}

    def react(self, track_id: int, artist_vec: np.ndarray | None, artist_id: int,
              rng: np.random.Generator) -> str:
        affinity = float(self.taste @ (artist_vec / (np.linalg.norm(artist_vec) or 1.0))) \
            if artist_vec is not None else 0.0

        repeats = self.artist_counts.get(artist_id, 0)
        # A variety seeker tires of an artist quickly; a completist does not.
        fatigue = self.variety_seeking * min(repeats, 6) * 0.25
        novelty = (1.0 - self.variety_seeking) * (0.15 if repeats > 0 else 0.0)

        logit = self.patience * (affinity * 3.0 - 0.35) - fatigue + novelty
        probability = 1.0 / (1.0 + np.exp(-logit))

        self.seen.add(track_id)
        self.artist_counts[artist_id] = repeats + 1
        return "completed" if rng.random() < probability else "skipped"


def run(
    users: int = 200,
    rounds: int = 40,
    seed: int = 43,
    params_dir: str | None = None,
    state_dir: str | None = None,
    learn: bool = True,
    stochastic: bool = False,
    drift: float = 0.5,
) -> dict:
    rng = np.random.default_rng(seed)
    params = load_params(resolve_params_dir(ENGINE_DIR, params_dir))
    config = load_config(params.manifest.get("serving"))
    recommender = Recommender(params, config)

    temporary = state_dir is None
    state_path = Path(state_dir or tempfile.mkdtemp(prefix="engine-sim-"))
    layer = ImprovementLayer(
        recommender=recommender,
        params=params,
        base_config=config,
        state_dir=state_path,
        learner_config=LearnerConfig(
            enabled=learn,
            stochastic_arms=stochastic,
            snapshot_every=10_000,  # snapshot at the end, not mid-run
        ),
    )

    # Listeners are built from real trained user vectors where possible, so the
    # taste distribution matches the population the engine was fitted on.
    pool = params.user_ids_artist
    chosen = rng.choice(len(pool), size=min(users, len(pool)), replace=False)
    listeners = [
        SimulatedListener(
            int(pool[i]), params.artist_user_emb[i].astype(np.float64), rng, drift=drift
        )
        for i in chosen
    ]

    history: list[dict] = []
    arm_counts: dict[str, int] = {}

    for round_index in range(rounds):
        rewards, completions = [], []
        for listener in listeners:
            profile = recommender.profile_from_user_id(listener.user_id)
            result, decision = layer.suggest(
                profile,
                exclude=set(listener.seen),
                user_id=listener.user_id,
                history_size=len(listener.seen),
                rng=rng,
            )
            arm_counts[decision.arm] = arm_counts.get(decision.arm, 0) + 1
            if not result.track_ids:
                continue

            track_id = result.track_ids[0]
            artist_id = params.track_artist.get(track_id, -1)
            row = params.artist_row.get(artist_id)
            artist_vec = params.artist_item_emb[row] if row is not None else None

            outcome = listener.react(track_id, artist_vec, artist_id, rng)
            report = layer.report(listener.user_id, track_id, outcome)
            completions.append(outcome == "completed")
            rewards.append(report.get("reward", 0.0) if report.get("attributed") else 0.0)

        history.append(
            {
                "round": round_index,
                "mean_reward": float(np.mean(rewards)) if rewards else 0.0,
                "completion_rate": float(np.mean(completions)) if completions else 0.0,
            }
        )

    stats = layer.stats
    layer.close()
    if temporary:
        shutil.rmtree(state_path, ignore_errors=True)

    window = max(1, rounds // 5)
    first = float(np.mean([h["completion_rate"] for h in history[:window]]))
    last = float(np.mean([h["completion_rate"] for h in history[-window:]]))
    first_reward = float(np.mean([h["mean_reward"] for h in history[:window]]))
    last_reward = float(np.mean([h["mean_reward"] for h in history[-window:]]))

    return {
        "learning_enabled": learn,
        "drift": drift,
        "users": len(listeners),
        "rounds": rounds,
        "completion_rate_first": round(first, 4),
        "completion_rate_last": round(last, 4),
        "completion_rate_lift": round(last - first, 4),
        "mean_reward_first": round(first_reward, 4),
        "mean_reward_last": round(last_reward, 4),
        "attribution_rate": stats["attribution_rate"],
        "arm_usage": arm_counts,
        "bandit": stats["bandit"]["arms"],
        "users_with_delta": stats["users"]["users_with_delta"],
        "tracks_observed": stats["items"]["tracks_observed"],
        "history": history,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--users", type=int, default=200)
    parser.add_argument("--rounds", type=int, default=40)
    parser.add_argument("--seed", type=int, default=43)
    parser.add_argument(
        "--drift",
        type=float,
        default=0.5,
        help="how far each listener's true taste sits from their trained profile (0-1)",
    )
    parser.add_argument("--params-dir", default=None)
    parser.add_argument(
        "--stochastic",
        action="store_true",
        help="sample arms and log true propensities, so the run's log is usable by IPS",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="also run with learning disabled, as a control",
    )
    parser.add_argument("--quiet", action="store_true", help="omit the per-round history")
    args = parser.parse_args(argv)

    result = run(
        args.users, args.rounds, args.seed, args.params_dir,
        learn=True, stochastic=args.stochastic, drift=args.drift,
    )
    output = {"learning": _trim(result, args.quiet)}

    if args.compare:
        control = run(
            args.users, args.rounds, args.seed, args.params_dir,
            learn=False, stochastic=args.stochastic, drift=args.drift,
        )
        output["control"] = _trim(control, args.quiet)
        output["delta_completion_rate"] = round(
            result["completion_rate_last"] - control["completion_rate_last"], 4
        )
    print(json.dumps(output, indent=2))


def _trim(result: dict, quiet: bool) -> dict:
    if quiet:
        return {k: v for k, v in result.items() if k != "history"}
    return result


if __name__ == "__main__":
    main()
