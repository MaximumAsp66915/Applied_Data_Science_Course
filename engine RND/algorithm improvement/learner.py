"""The orchestrator: decide, observe, persist.

Everything else in this package is a component with one job. This is the object
that owns them, routes a request through them, and routes feedback back.

## The loop

    decide(request)  -> context features -> bandit picks an arm
                     -> arm's config + user's delta + item signals
                     -> engine ranks -> impression logged
                        |
                        v
    observe(outcome) -> claim the matching impression
                     -> reward model scores it
                     -> bandit update (which strategy worked)
                     -> user delta update (what this person likes)
                     -> item posterior update (what the group likes)

## Attribution

The hard part is not learning, it is knowing *what to learn from*. The app
reports "track X finished" without saying which recommendation that answers, so
`observe` only credits an outcome when `PendingImpressions` confirms that this
engine served X to this user and has not already credited it. A track the user
found through search produces no update, and a replay from history produces no
second update.

## Failure policy

Every public method is wrapped so that a failure in the learning layer degrades
the engine to its unlearned behaviour rather than failing the request. A
recommender that returns a slightly worse track is a product with a rough edge;
a recommender that returns a 500 because a background learner hit an unexpected
state is an outage. The failure is counted and surfaced in `stats`, so
degrading silently is not the same as degrading invisibly.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from artifacts import Params
from config import ServingConfig
from events import (
    OUTCOME_COMPLETED,
    OUTCOME_SKIPPED,
    EventLog,
    Impression,
    Outcome,
    PendingImpressions,
    atomic_write_bytes,
    new_impression_id,
)
from bandit import FEATURE_DIM, LinUCB, build_context
from item_model import EngagementModel
from policies import DEFAULT_POLICY, POLICY_NAMES, get_policy
from rewards import DEFAULT_REWARD_MODEL, RewardModel
from user_model import UserDeltaStore

log = logging.getLogger(__name__)

STATE_VERSION = 1


@dataclass
class LearnerConfig:
    """Everything about the learning layer that is worth tuning without a code
    change. Read from `ENGINE_LEARN_*` environment variables by `from_env`."""

    enabled: bool = True
    stochastic_arms: bool = False
    """Sample arms from a softmax and log true propensities. Off by default:
    greedy selection makes a served recommendation reproducible from the log.
    Turn it on for an evaluation window, when inverse-propensity scoring is
    wanted (see offline_eval.py)."""

    alpha: float = 0.6
    """LinUCB exploration coefficient: the price of curiosity."""

    exploration_share: float = 0.10
    """Share of requests on which the bandit is allowed to explore rather than
    serve its current best estimate. Bounds worst-case regret at
    `share x (best arm - worst arm)`. 1.0 is textbook LinUCB; 0.0 freezes the
    bandit into pure exploitation of whatever it already believes."""

    min_pulls_to_trust: int = 150
    """Observations a challenger arm needs before it may displace the incumbent
    on an exploitation request."""

    deviation_margin: float = 0.02
    """Predicted-reward margin a challenger must clear to displace the
    incumbent. Together with `min_pulls_to_trust`, this is what keeps early
    learning from making the product worse."""

    trust_learned_policy: bool = False
    """Whether the bandit's learned choice is allowed to steer traffic.

    **Off by default, on purpose.** The bandit trains from day one and its
    estimates are visible on `GET /learning`, but until an off-policy estimate
    on real logged traffic (`offline_eval.py`) shows a candidate policy beating
    the incumbent with an adequate effective sample size, the incumbent keeps
    serving. Flipping this on before that evidence exists is how a learning
    system quietly makes a product worse -- and measurement in the simulator
    showed exactly that happening. See `bandit.LinUCB.select`."""

    item_signal_weight: float = 0.25
    """How much live engagement moves a candidate's final score.

    On by default: it is the one learner that measured as a clear (if small)
    improvement, +0.16 points of completion rate in simulation, and it is the
    only mechanism by which a track with no reactions can ever earn its way up
    a candidate pool."""

    user_delta_enabled: bool = False
    """Per-user online preference learning. **Off by default, on measured
    evidence, and this is the most interesting result in the package.**

    The mechanism works exactly as designed -- deltas stay inside their trust
    region, decay correctly, and change what gets served. It also makes the
    recommendations *worse* in simulation: -0.44 points of completion rate at
    the default learning rate, and -1.85 at 0.25. The monotonicity in learning
    rate is what makes it a finding rather than noise.

    The reason is a genuine limitation rather than a bug. The engine only ever
    serves items it already ranks highly, so nearly all feedback concerns
    artists already near the top of the current profile. A negative reward
    pushes the profile away from those artists -- but in a 200-dimensional
    space, "away from wrong" is not "toward right": there are vastly more wrong
    directions than right ones. Learning a taste vector from feedback on items
    chosen by the current estimate of that same taste vector needs exploration
    in *item* space, not just in policy space, and in shadow mode only about a
    tenth of traffic explores.

    So this is premature rather than mistaken. It becomes viable with a much
    larger exploration budget in item space, or with far more observations per
    listener than a 40-round simulation provides. Until one of those is true,
    the incumbent profile serves. Turn it on with
    `ENGINE_LEARN_USER_DELTA=1` to experiment, and watch `/learning`."""

    learning_rate: float = 0.08
    delta_decay: float = 0.02
    max_delta_ratio: float = 0.5

    snapshot_every: int = 200
    """Updates between state snapshots. Bounds how much learning a hard kill
    can cost; the event log survives regardless, so a snapshot is a cache of
    replayable history rather than the only copy."""

    log_events: bool = True
    max_log_bytes: int = 32 * 1024 * 1024

    @classmethod
    def from_env(cls, env=None) -> "LearnerConfig":
        import os

        env = env if env is not None else os.environ
        config = cls()
        mapping = {
            "enabled": ("ENGINE_LEARN_ENABLED", _as_bool),
            "stochastic_arms": ("ENGINE_LEARN_STOCHASTIC", _as_bool),
            "alpha": ("ENGINE_LEARN_ALPHA", float),
            "exploration_share": ("ENGINE_LEARN_EXPLORE_SHARE", float),
            "min_pulls_to_trust": ("ENGINE_LEARN_MIN_PULLS", int),
            "deviation_margin": ("ENGINE_LEARN_MARGIN", float),
            "trust_learned_policy": ("ENGINE_LEARN_TRUST_POLICY", _as_bool),
            "item_signal_weight": ("ENGINE_LEARN_ITEM_WEIGHT", float),
            "user_delta_enabled": ("ENGINE_LEARN_USER_DELTA", _as_bool),
            "learning_rate": ("ENGINE_LEARN_RATE", float),
            "delta_decay": ("ENGINE_LEARN_DECAY", float),
            "max_delta_ratio": ("ENGINE_LEARN_MAX_DELTA", float),
            "snapshot_every": ("ENGINE_LEARN_SNAPSHOT_EVERY", int),
            "log_events": ("ENGINE_LEARN_LOG_EVENTS", _as_bool),
        }
        overrides = {}
        for field_name, (var, cast) in mapping.items():
            raw = env.get(var)
            if raw not in (None, ""):
                try:
                    overrides[field_name] = cast(raw)
                except ValueError:
                    log.warning("ignoring malformed %s=%r", var, raw)
        return cls(**{**config.__dict__, **overrides})


def _as_bool(raw: str) -> bool:
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Decision:
    """What `decide` resolved for one request."""

    arm: str
    propensity: float
    context: np.ndarray
    config: ServingConfig
    artist_delta: np.ndarray | None = None
    track_delta: np.ndarray | None = None


class Learner:
    """Owns the bandit, the per-user deltas, the item posteriors and the log."""

    def __init__(
        self,
        params: Params,
        base_config: ServingConfig,
        state_dir: str | Path,
        config: LearnerConfig | None = None,
        reward_model: RewardModel | None = None,
    ):
        self.params = params
        self.base_config = base_config
        self.config = config or LearnerConfig()
        self.rewards = reward_model or DEFAULT_REWARD_MODEL
        self.state_dir = Path(state_dir)

        self.bandit = LinUCB(
            list(POLICY_NAMES),
            dim=FEATURE_DIM,
            alpha=self.config.alpha,
            exploration_share=self.config.exploration_share,
            default_arm=DEFAULT_POLICY,
            min_pulls_to_trust=self.config.min_pulls_to_trust,
            deviation_margin=self.config.deviation_margin,
            trust_learned_policy=self.config.trust_learned_policy,
        )
        self.users = UserDeltaStore(
            artist_dim=params.artist_item_emb.shape[1],
            track_dim=params.track_item_emb.shape[1],
            mean_user_norm=params.mean_user_norm,
            learning_rate=self.config.learning_rate,
            decay=self.config.delta_decay,
            max_norm_ratio=self.config.max_delta_ratio,
        )
        self.items = EngagementModel()
        self.pending = PendingImpressions()
        self.events = (
            EventLog(self.state_dir / "events.jsonl", max_bytes=self.config.max_log_bytes)
            if self.config.log_events
            else None
        )

        self._lock = threading.Lock()
        self._updates_since_snapshot = 0
        self.counters = {
            "decisions": 0,
            "outcomes_reported": 0,
            "outcomes_attributed": 0,
            "outcomes_unmatched": 0,
            "errors": 0,
        }
        self._started = time.time()
        self.load()

    # ---------------------------------------------------------------- decide
    def decide(
        self,
        user_id: int | None,
        source: str,
        history_size: int = 0,
        session_depth: int = 0,
        has_track_vector: bool = False,
        artist_concentration: float = 0.0,
        rng: np.random.Generator | None = None,
        allow_exploration: bool = True,
    ) -> Decision:
        """Pick a serving strategy for this request.

        `allow_exploration=False` suppresses the random exploration slice and
        returns the arm the bandit would serve on an exploitation request. That
        is what `/explain` needs: a debugging endpoint should describe the
        engine's considered choice, not whichever arm a coin flip produced --
        while the caller stays aware that roughly `exploration_share` of live
        requests do take a different arm on purpose.
        """
        if not self.config.enabled:
            return Decision(
                arm=DEFAULT_POLICY,
                propensity=1.0,
                context=np.zeros(FEATURE_DIM),
                config=self.base_config,
            )
        try:
            context = build_context(
                history_size=history_size,
                has_track_vector=has_track_vector,
                session_depth=session_depth,
                catalogue_size=len(self.params.catalogue_track_ids),
                source=source,
                recent_reward=self.users.recent_reward(user_id),
                artist_concentration=artist_concentration,
                repeat_affinity=self.users.repeat_affinity(user_id),
            )
            arm, propensity = self.bandit.select(
                context,
                stochastic=self.config.stochastic_arms and allow_exploration,
                rng=rng,
                exploration_share=None if allow_exploration else 0.0,
            )
            config = get_policy(arm).apply(self.base_config)

            artist_delta = track_delta = None
            if self.config.user_delta_enabled:
                artist_delta = self.users.artist_delta(user_id)
                track_delta = self.users.track_delta(user_id)

            with self._lock:
                self.counters["decisions"] += 1
            return Decision(arm, propensity, context, config, artist_delta, track_delta)
        except Exception:  # noqa: BLE001 - the request must still be answered
            log.exception("learner.decide failed; falling back to base config")
            with self._lock:
                self.counters["errors"] += 1
            return Decision(DEFAULT_POLICY, 1.0, np.zeros(FEATURE_DIM), self.base_config)

    def item_signals(self, track_ids) -> np.ndarray | None:
        """Live engagement adjustment for a candidate pool, or None if off."""
        if not self.config.enabled or self.config.item_signal_weight <= 0:
            return None
        try:
            signals = self.items.track_signals(track_ids)
            return signals * np.float32(self.config.item_signal_weight)
        except Exception:  # noqa: BLE001
            log.exception("learner.item_signals failed")
            with self._lock:
                self.counters["errors"] += 1
            return None

    def record_impression(
        self,
        decision: Decision,
        user_id: int | None,
        track_ids: list[int],
        source: str,
        endpoint: str = "suggest",
    ) -> list[str]:
        """Log what was served, so an outcome can be credited to it later."""
        if not self.config.enabled or not track_ids:
            return []
        ids = []
        try:
            for rank, track_id in enumerate(track_ids):
                artist_id = int(self.params.track_artist.get(int(track_id), -1))
                repeat = self.pending.is_repeat_artist(user_id, artist_id)
                impression = Impression(
                    impression_id=new_impression_id(),
                    user_id=user_id,
                    track_id=int(track_id),
                    artist_id=artist_id,
                    arm=decision.arm,
                    propensity=float(decision.propensity),
                    context=[float(v) for v in decision.context],
                    source=source,
                    rank=rank,
                    endpoint=endpoint,
                )
                self.pending.remember(impression)
                # Stashed on the pending record rather than in the event, so
                # credit assignment can use it without a second lookup.
                pending = self.pending.peek(user_id, int(track_id))
                if pending is not None:
                    pending["repeat_artist"] = repeat
                if self.events is not None:
                    self.events.append(impression)
                ids.append(impression.impression_id)
        except Exception:  # noqa: BLE001
            log.exception("learner.record_impression failed")
            with self._lock:
                self.counters["errors"] += 1
        return ids

    # --------------------------------------------------------------- observe
    def observe(
        self,
        user_id: int | None,
        track_id: int,
        kind: str,
        strength: float | None = None,
        impression_id: str | None = None,
    ) -> dict:
        """Report an outcome and fold it into every model.

        Returns a small report -- attributed or not, the reward, the arm
        credited -- which `POST /feedback` hands back so an integrator can see
        immediately whether their calls are landing, rather than discovering
        weeks later that nothing was ever attributed.
        """
        with self._lock:
            self.counters["outcomes_reported"] += 1

        if not self.config.enabled:
            return {"attributed": False, "reason": "learner disabled"}

        try:
            claimed = self.pending.claim(user_id, int(track_id))
            if claimed is None:
                # Not ours: the user reached this track some other way, or we
                # already credited it. Either way, inventing a reward here
                # would teach the engine about decisions it never made.
                with self._lock:
                    self.counters["outcomes_unmatched"] += 1
                if self.events is not None and impression_id:
                    self.events.append(
                        Outcome(
                            impression_id=impression_id,
                            kind=kind,
                            user_id=user_id,
                            track_id=int(track_id),
                            strength=strength,
                        )
                    )
                return {"attributed": False, "reason": "no matching impression"}

            outcome = Outcome(
                impression_id=impression_id or claimed["impression_id"],
                kind=kind,
                user_id=user_id,
                track_id=int(track_id),
                strength=strength,
            )
            reward = self.rewards.single(outcome)
            if self.events is not None:
                self.events.append(outcome)

            self._apply(claimed, user_id, int(track_id), reward)

            with self._lock:
                self.counters["outcomes_attributed"] += 1
                self._updates_since_snapshot += 1
                due = self._updates_since_snapshot >= self.config.snapshot_every
            if due:
                self.save()

            return {
                "attributed": True,
                "reward": round(reward, 4),
                "arm": claimed["arm"],
                "impression_id": outcome.impression_id,
            }
        except Exception:  # noqa: BLE001
            log.exception("learner.observe failed")
            with self._lock:
                self.counters["errors"] += 1
            return {"attributed": False, "reason": "internal error"}

    def observe_implicit(
        self,
        user_id: int | None,
        liked_track_id: int | None,
        disliked_track_id: int | None,
    ) -> list[dict]:
        """Harvest the implicit hints the app already sends.

        `/suggest` accepts `implicit_liked_track_id` and
        `implicit_disliked_track_id`, which the webapp fills from the frontend's
        "completed"/"skipped" report about whatever was playing before this
        request (see `repository.record_play_and_get_queue`). Those are exactly
        the outcomes this learner needs, and they arrive today, on the existing
        contract, with no change to the app -- which is the difference between
        a feature that learns in production and one that waits on an
        integration ticket.
        """
        reports = []
        if liked_track_id is not None:
            reports.append(self.observe(user_id, liked_track_id, OUTCOME_COMPLETED))
        if disliked_track_id is not None:
            reports.append(self.observe(user_id, disliked_track_id, OUTCOME_SKIPPED))
        return reports

    def _apply(self, claimed: dict, user_id: int | None, track_id: int, reward: float) -> None:
        """Route one reward to the three learners."""
        if reward == 0.0:
            return

        # 1. Which strategy worked, in this context.
        self.bandit.update(claimed["arm"], np.asarray(claimed["context"]), reward)

        # 2. What this listener likes.
        if self.config.user_delta_enabled and user_id is not None:
            artist_row = self.params.artist_row.get(int(claimed.get("artist_id", -1)))
            track_row = self.params.track_row.get(int(track_id))
            self.users.update(
                user_id,
                reward,
                artist_embedding=(
                    self.params.artist_item_emb[artist_row] if artist_row is not None else None
                ),
                track_embedding=(
                    self.params.track_item_emb[track_row] if track_row is not None else None
                ),
                was_repeat_artist=bool(claimed.get("repeat_artist", False)),
            )

        # 3. What the group thinks of this track.
        self.items.observe(track_id, claimed.get("artist_id"), reward)

    # ----------------------------------------------------------- persistence
    def save(self) -> bool:
        """Snapshot every model. Atomic, so a crash mid-write cannot leave a
        state file that fails to load on the next start."""
        try:
            import io

            payload = {}
            for prefix, arrays in (
                ("bandit", self.bandit.to_arrays()),
                ("users", self.users.to_arrays()),
                ("items", self.items.to_arrays()),
            ):
                for key, value in arrays.items():
                    payload[f"{prefix}__{key}"] = value
            payload["version"] = np.array([STATE_VERSION])
            payload["saved_at"] = np.array([time.time()])

            buffer = io.BytesIO()
            np.savez_compressed(buffer, **payload)
            atomic_write_bytes(self.state_dir / "learner_state.npz", buffer.getvalue())

            with self._lock:
                self._updates_since_snapshot = 0
            return True
        except Exception:  # noqa: BLE001
            log.exception("learner.save failed")
            with self._lock:
                self.counters["errors"] += 1
            return False

    def load(self) -> bool:
        """Restore a snapshot if one is there. A missing or unreadable file is
        not an error -- it is the first start."""
        path = self.state_dir / "learner_state.npz"
        if not path.exists():
            return False
        try:
            with np.load(path, allow_pickle=True) as payload:
                version = int(payload["version"][0]) if "version" in payload else 0
                if version != STATE_VERSION:
                    log.warning(
                        "learner state version %s != %s; starting fresh", version, STATE_VERSION
                    )
                    return False

                def group(prefix):
                    return {
                        key[len(prefix) + 2 :]: payload[key]
                        for key in payload.files
                        if key.startswith(prefix + "__")
                    }

                restored = LinUCB.from_arrays(group("bandit"), list(POLICY_NAMES))
                if restored.dim != FEATURE_DIM:
                    # The context vector gained or lost a feature since this
                    # snapshot was written, so its weights no longer mean what
                    # they used to. Starting the bandit fresh is the only safe
                    # option; the per-user and item models are unaffected.
                    log.warning(
                        "bandit snapshot has %d features, expected %d -- retraining the "
                        "bandit from scratch and keeping user/item state",
                        restored.dim,
                        FEATURE_DIM,
                    )
                else:
                    self.bandit = restored
                    self.bandit.alpha = self.config.alpha
                    self.bandit.exploration_share = self.config.exploration_share
                    self.bandit.default_arm = DEFAULT_POLICY
                    self.bandit.min_pulls_to_trust = self.config.min_pulls_to_trust
                    self.bandit.deviation_margin = self.config.deviation_margin
                    self.bandit.trust_learned_policy = self.config.trust_learned_policy
                self.users.load_arrays(group("users"))
                self.items.load_arrays(group("items"))
            log.info("restored learner state from %s", path)
            return True
        except Exception:  # noqa: BLE001
            log.exception("learner.load failed; starting fresh")
            return False

    def close(self) -> None:
        self.save()
        if self.events is not None:
            self.events.close()

    # -------------------------------------------------------------- reporting
    @property
    def stats(self) -> dict:
        """Learner state for `GET /learning`.

        Every component is read defensively. This endpoint exists so that a
        system which changes its own behaviour can be inspected, and it is most
        needed precisely when something has gone wrong -- so it must report a
        broken component rather than raising on it.
        """
        with self._lock:
            counters = dict(self.counters)
        reported = counters["outcomes_reported"]

        def safely(component, attribute="stats"):
            try:
                return getattr(component, attribute)
            except Exception:  # noqa: BLE001
                return {"error": "unavailable"}

        return {
            "enabled": self.config.enabled,
            "uptime_seconds": round(time.time() - self._started, 1),
            "counters": counters,
            "attribution_rate": (
                round(counters["outcomes_attributed"] / reported, 3) if reported else 0.0
            ),
            "bandit": safely(self.bandit),
            "users": safely(self.users),
            "items": safely(self.items),
            "pending": safely(self.pending),
            "event_log_bytes": self.events.size_bytes if self.events else 0,
        }
