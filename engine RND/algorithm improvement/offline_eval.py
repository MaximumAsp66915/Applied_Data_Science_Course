"""Evaluating a policy from logged feedback, without shipping it.

The whole reason this file exists is the lesson from ANALYSIS.md, findings E-1
to E-4: engine_v2 published numbers that could not support the conclusions
drawn from them, because the evaluation leaked and the metric was misread. A
system that now *changes itself* from live feedback makes that failure mode
considerably more dangerous -- there would be no fixed model to go back and
re-measure.

So: before any change to arms, reward weights or hyperparameters goes live, it
should be estimated from the log. Two estimators, with different trade-offs.

## Replay (Li et al., 2011)

Walk the logged events. Whenever the candidate policy would have chosen the arm
that was actually logged, keep that event; otherwise discard it. Average the
reward over kept events.

Unbiased whenever the logging policy chose uniformly at random among arms, and
close enough to unbiased when it explored broadly. Its weakness is sample
efficiency: with five arms, a policy that disagrees with the log most of the
time keeps a small fraction of the data, so the estimate gets noisy fast.
`effective_sample_size` is reported for exactly this reason -- an estimate over
40 kept events is not evidence, and the caller needs to be able to see that.

## Inverse propensity scoring

Keep every event, weight each by `1 / p_logged` when the candidate policy
agrees. Uses all the data, but the variance explodes when a logged propensity
was small: one event logged at p = 0.01 contributes a hundred times its own
reward. `weight_cap` clips that, trading a little bias for a usable estimate --
the standard capped-IPS compromise.

IPS needs real propensities, which means the logging policy has to have been
stochastic. `LinUCB` is greedy by default and logs 1.0, so IPS is only
meaningful over a window run with `ENGINE_LEARN_STOCHASTIC=1`. `evaluate`
detects that and says so rather than returning a confident-looking number
computed from constants.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from events import EVENT_IMPRESSION, EventLog
from rewards import DEFAULT_REWARD_MODEL, RewardModel


@dataclass
class PolicyEstimate:
    """What one candidate policy would have scored on the logged traffic."""

    policy: str
    estimator: str
    mean_reward: float
    effective_sample_size: float
    events_considered: int
    events_matched: int
    std_error: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "policy": self.policy,
            "estimator": self.estimator,
            "mean_reward": round(self.mean_reward, 4),
            "effective_sample_size": round(self.effective_sample_size, 1),
            "events_considered": self.events_considered,
            "events_matched": self.events_matched,
            "std_error": round(self.std_error, 4),
            "warnings": self.warnings,
        }


def load_dataset(log: EventLog, reward_model: RewardModel | None = None) -> list[dict]:
    """Flatten the event log into `(context, arm, propensity, reward)` rows.

    Impressions with no outcome are kept, with reward 0. Dropping them would
    bias every estimate upward, because a recommendation nobody engaged with is
    a real result -- and the most common one.
    """
    reward_model = reward_model or DEFAULT_REWARD_MODEL
    rows = []
    for impression, outcomes in log.read_pairs():
        if impression.get("event") != EVENT_IMPRESSION:
            continue
        rows.append(
            {
                "context": np.asarray(impression.get("context", []), dtype=np.float64),
                "arm": impression.get("arm"),
                "propensity": float(impression.get("propensity", 1.0)),
                "reward": reward_model.score(outcomes),
                "user_id": impression.get("user_id"),
                "track_id": impression.get("track_id"),
                "observed": bool(outcomes),
            }
        )
    return rows


def replay_estimate(rows: list[dict], policy_fn, name: str = "candidate") -> PolicyEstimate:
    """Rejection-sampling ("replay") estimate of a candidate policy."""
    matched_rewards = []
    for row in rows:
        if policy_fn(row["context"]) == row["arm"]:
            matched_rewards.append(row["reward"])

    warnings = []
    if not matched_rewards:
        warnings.append("policy never agreed with the log; no estimate possible")
        return PolicyEstimate(name, "replay", 0.0, 0.0, len(rows), 0, 0.0, warnings)

    rewards = np.asarray(matched_rewards)
    if len(rewards) < 100:
        warnings.append(
            f"only {len(rewards)} matched events; treat this as a smoke test, not evidence"
        )
    return PolicyEstimate(
        policy=name,
        estimator="replay",
        mean_reward=float(rewards.mean()),
        effective_sample_size=float(len(rewards)),
        events_considered=len(rows),
        events_matched=len(rewards),
        std_error=float(rewards.std(ddof=1) / np.sqrt(len(rewards))) if len(rewards) > 1 else 0.0,
        warnings=warnings,
    )


def ips_estimate(
    rows: list[dict], policy_fn, name: str = "candidate", weight_cap: float = 20.0
) -> PolicyEstimate:
    """Capped inverse-propensity-scoring estimate."""
    warnings = []
    propensities = np.array([r["propensity"] for r in rows]) if rows else np.zeros(0)
    if rows and np.allclose(propensities, 1.0):
        warnings.append(
            "every logged propensity is 1.0, so the logging policy was deterministic -- "
            "IPS is not identifiable here. Re-run the window with "
            "ENGINE_LEARN_STOCHASTIC=1, or use the replay estimator."
        )

    weights, weighted = [], []
    matched = 0
    for row in rows:
        if policy_fn(row["context"]) != row["arm"]:
            weights.append(0.0)
            weighted.append(0.0)
            continue
        matched += 1
        propensity = max(row["propensity"], 1e-6)
        weight = min(1.0 / propensity, weight_cap)
        weights.append(weight)
        weighted.append(weight * row["reward"])

    if not matched:
        warnings.append("policy never agreed with the log")
        return PolicyEstimate(name, "ips", 0.0, 0.0, len(rows), 0, 0.0, warnings)

    w = np.asarray(weights)
    v = np.asarray(weighted)
    total_weight = w.sum()
    mean = float(v.sum() / total_weight) if total_weight > 0 else 0.0
    # Kish's effective sample size: how many equally-weighted observations this
    # weighted sample is worth. The number that says whether to believe it.
    ess = float((w.sum() ** 2) / (np.square(w).sum())) if np.square(w).sum() > 0 else 0.0
    if ess < 100:
        warnings.append(f"effective sample size {ess:.0f} is small; the estimate is noisy")

    return PolicyEstimate(
        policy=name,
        estimator="ips",
        mean_reward=mean,
        effective_sample_size=ess,
        events_considered=len(rows),
        events_matched=matched,
        std_error=float(np.std(v[w > 0], ddof=1) / np.sqrt(matched)) if matched > 1 else 0.0,
        warnings=warnings,
    )


def evaluate(
    rows: list[dict], policies: dict, weight_cap: float = 20.0
) -> dict:
    """Score several candidate policies at once.

    `policies` maps a name to a callable `context -> arm name`. Both estimators
    run for each; disagreement between them is itself informative, and usually
    means the effective sample size is too small to trust either.
    """
    out = {"events": len(rows), "policies": {}}
    for name, policy_fn in policies.items():
        out["policies"][name] = {
            "replay": replay_estimate(rows, policy_fn, name).as_dict(),
            "ips": ips_estimate(rows, policy_fn, name, weight_cap).as_dict(),
        }
    out["logged"] = logged_summary(rows)
    return out


def logged_summary(rows: list[dict]) -> dict:
    """What the log itself says: per-arm counts and mean reward.

    The baseline every candidate has to beat, and a sanity check on the loop.
    A `feedback_coverage` near zero means outcomes are not reaching the engine,
    which invalidates everything else on the page.
    """
    per_arm = defaultdict(list)
    observed = 0
    for row in rows:
        per_arm[row["arm"]].append(row["reward"])
        observed += bool(row["observed"])
    return {
        "feedback_coverage": round(observed / len(rows), 3) if rows else 0.0,
        "overall_mean_reward": (
            round(float(np.mean([r["reward"] for r in rows])), 4) if rows else 0.0
        ),
        "arms": {
            arm: {
                "impressions": len(rewards),
                "mean_reward": round(float(np.mean(rewards)), 4),
            }
            for arm, rewards in sorted(per_arm.items())
        },
    }


def fixed_policy(arm: str):
    """`context -> arm`, always. The 'what if we just always did X' baseline."""
    return lambda _context: arm


def bandit_policy(bandit):
    """Wrap a trained bandit as a candidate policy for evaluation."""
    return lambda context: bandit.select(context)[0]
