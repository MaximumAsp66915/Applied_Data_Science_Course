"""The feedback log: what the engine chose, and what happened next.

Nothing in this package can learn anything without this file. An engine that
does not record *which decision it made* cannot be told afterwards whether the
decision was good -- and `engine_v2` recorded nothing at all, which is the
deepest reason it could never improve from use.

Two record types, deliberately separate:

**Impression** -- written synchronously when the engine answers a request.
It captures the decision: which policy arm was chosen, the context features
that led to that choice, the propensity it was chosen with, and the track that
was actually served. Written *before* the outcome is known, because that is the
only order in which an honest log can be kept.

**Outcome** -- written when the app tells us what the listener did. Carries an
`impression_id`, so credit assignment is exact rather than inferred from
timing.

The store is an append-only JSONL file with size-based rotation. That choice is
worth defending: the engine answers a request in under a millisecond, so the
logging path has to be cheap and must never lose the last few seconds of
history to a crash (a database round trip per impression would cost more than
the recommendation itself). JSONL append is one `write` plus one `flush`, is
trivially inspectable with `tail`, replays deterministically, and survives
`kill -9` with at most a partial final line -- which the reader skips.

Privacy: an event holds internal integer ids and derived numeric features
only. No names, no Telegram ids, no message content, nothing about *what* a
track is.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

# Outcome kinds the app can report. The first two arrive with no integration
# work at all -- they are already in the parameters the app sends today (see
# README, "Closing the loop with no app changes"). The rest need a call to
# POST /feedback, and are supported so that richer signal can be adopted
# incrementally rather than all at once.
OUTCOME_COMPLETED = "completed"  # played to its natural end
OUTCOME_SKIPPED = "skipped"  # user pressed next/prev/try-another
OUTCOME_LIKED = "liked"  # explicit positive reaction
OUTCOME_DISLIKED = "disliked"  # explicit negative reaction
OUTCOME_DOWNLOADED = "downloaded"  # sent to their own chat: strongest signal
OUTCOME_IGNORED = "ignored"  # served, never played

OUTCOME_KINDS = frozenset({
    OUTCOME_COMPLETED,
    OUTCOME_SKIPPED,
    OUTCOME_LIKED,
    OUTCOME_DISLIKED,
    OUTCOME_DOWNLOADED,
    OUTCOME_IGNORED,
})

EVENT_IMPRESSION = "impression"
EVENT_OUTCOME = "outcome"


def new_impression_id() -> str:
    """Short, collision-free id. uuid4's first 16 hex digits give 64 bits,
    which is ample for a log that rotates long before birthday effects."""
    return uuid.uuid4().hex[:16]


@dataclass
class Impression:
    """One served recommendation, with the decision that produced it."""

    impression_id: str
    user_id: int | None
    track_id: int
    artist_id: int
    arm: str
    """Name of the policy arm the bandit selected."""
    propensity: float
    """Probability this arm was chosen, in [0, 1]. Recorded so that off-policy
    evaluation can reweight honestly (see offline_eval.py). A deterministic
    (greedy) choice logs 1.0 and is only usable by the replay estimator."""
    context: list[float]
    """The bandit's context feature vector at decision time."""
    source: str
    """The engine's own provenance label: trained_embedding, blended_profile,
    reacted_artists, reacted_tracks, popular_fallback."""
    rank: int = 0
    """Position in the response, 0 for a single /suggest pick."""
    endpoint: str = "suggest"
    created_at: float = field(default_factory=time.time)
    event: str = EVENT_IMPRESSION

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


@dataclass
class Outcome:
    """What the listener did with a served recommendation."""

    impression_id: str
    kind: str
    user_id: int | None = None
    track_id: int | None = None
    strength: float | None = None
    """Signed reaction strength on the reaction_types scale (-5..+5), when the
    caller has it. The Mini App only knows like/dislike; the Telegram group bot
    knows the full emoji scale (Chapter 3, A.8), so both are accepted."""
    created_at: float = field(default_factory=time.time)
    event: str = EVENT_OUTCOME

    def __post_init__(self):
        if self.kind not in OUTCOME_KINDS:
            raise ValueError(
                f"unknown outcome kind {self.kind!r}; expected one of {sorted(OUTCOME_KINDS)}"
            )

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


class EventLog:
    """Append-only JSONL event store with size-based rotation.

    Thread-safe: uvicorn may run the endpoint handlers on a worker thread pool,
    so appends take a lock. The lock is held for one `write` of a few hundred
    bytes, which is cheaper than the recommendation it records.
    """

    def __init__(
        self,
        path: str | Path,
        max_bytes: int = 32 * 1024 * 1024,
        keep_rotations: int = 3,
        flush_every: int = 1,
    ):
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.keep_rotations = int(keep_rotations)
        self.flush_every = max(1, int(flush_every))
        self._lock = threading.Lock()
        self._handle = None
        self._since_flush = 0
        self.appended = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ write
    def append(self, record: Impression | Outcome) -> None:
        line = record.to_json()
        with self._lock:
            self._rotate_if_needed(len(line) + 1)
            handle = self._open()
            handle.write(line + "\n")
            self._since_flush += 1
            self.appended += 1
            if self._since_flush >= self.flush_every:
                handle.flush()
                self._since_flush = 0

    def append_many(self, records) -> None:
        for record in records:
            self.append(record)

    def flush(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.flush()
                self._since_flush = 0

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.flush()
                self._handle.close()
                self._handle = None

    def _open(self):
        if self._handle is None:
            self._handle = self.path.open("a", encoding="utf-8")
        return self._handle

    def _rotate_if_needed(self, incoming: int) -> None:
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if size + incoming <= self.max_bytes:
            return

        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
            self._handle = None

        # events.jsonl -> events.jsonl.1 -> .2 -> ... dropping the oldest.
        for index in range(self.keep_rotations, 0, -1):
            older = self.path.with_suffix(self.path.suffix + f".{index}")
            if index == self.keep_rotations and older.exists():
                older.unlink()
                continue
            newer = (
                self.path
                if index == 1
                else self.path.with_suffix(self.path.suffix + f".{index - 1}")
            )
            if newer.exists():
                newer.replace(older)

    # ------------------------------------------------------------------- read
    def read(self, include_rotations: bool = True) -> Iterator[dict]:
        """Yield every event, oldest first. Malformed trailing lines -- the
        signature of a process killed mid-write -- are skipped silently, which
        is the whole reason a line-delimited format was chosen."""
        self.flush()
        paths = []
        if include_rotations:
            paths = sorted(
                self.path.parent.glob(self.path.name + ".*"),
                key=lambda p: int(p.suffix.lstrip(".")),
                reverse=True,
            )
        paths.append(self.path)

        for path in paths:
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def read_pairs(self, include_rotations: bool = True) -> list[tuple[dict, list[dict]]]:
        """Join impressions to their outcomes.

        Returns `[(impression, [outcome, ...]), ...]` in impression order.
        Impressions with no outcome are included with an empty list: "served
        and nothing happened" is data, and dropping it would bias every
        estimate upward.
        """
        impressions: dict[str, dict] = {}
        outcomes: dict[str, list[dict]] = {}
        for event in self.read(include_rotations):
            kind = event.get("event")
            if kind == EVENT_IMPRESSION:
                impressions[event["impression_id"]] = event
            elif kind == EVENT_OUTCOME:
                outcomes.setdefault(event["impression_id"], []).append(event)
        return [(imp, outcomes.get(imp_id, [])) for imp_id, imp in impressions.items()]

    @property
    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except FileNotFoundError:
            return 0


class PendingImpressions:
    """Bounded in-memory index of impressions still awaiting an outcome.

    The attribution problem this solves: the app reports "track X finished" or
    "track X was skipped" without saying which recommendation that answers.
    To assign the reward we need to know whether *we* served X to this user,
    and which arm did it. This holds the last N impressions per user so that
    lookup is O(1) on the request path.

    Bounded on purpose. An unbounded dictionary keyed by user is a slow memory
    leak in a process designed to run for weeks between restarts, and an
    impression nobody reported on within a few dozen tracks is not worth
    crediting anyway.
    """

    def __init__(self, per_user: int = 32, max_users: int = 20_000):
        self.per_user = int(per_user)
        self.max_users = int(max_users)
        self._by_user: dict[int, dict[int, dict]] = {}
        self._recent_artists: dict[int, list[int]] = {}
        self._order: list[int] = []
        self._lock = threading.Lock()

    def remember(self, impression: Impression) -> None:
        if impression.user_id is None:
            return  # anonymous requests cannot be credited to anyone
        with self._lock:
            user = int(impression.user_id)
            served = self._by_user.setdefault(user, {})
            if not served:
                self._order.append(user)
                self._evict_users_locked()
            served[int(impression.track_id)] = {
                "impression_id": impression.impression_id,
                "arm": impression.arm,
                "context": list(impression.context),
                "propensity": float(impression.propensity),
                "artist_id": int(impression.artist_id),
                "created_at": impression.created_at,
            }
            while len(served) > self.per_user:
                oldest = min(served, key=lambda t: served[t]["created_at"])
                del served[oldest]

            # Short ring of recently served artists, used to tell whether an
            # impression was a repeat for this listener -- the observation
            # behind the `repeat_affinity` context feature.
            ring = self._recent_artists.setdefault(user, [])
            ring.append(int(impression.artist_id))
            if len(ring) > self.per_user:
                del ring[0]

    def claim(self, user_id: int | None, track_id: int) -> dict | None:
        """Look up and remove the impression for (user, track).

        Removal is deliberate: a track completed once should be credited once.
        Without it, a user who replays a track from history would keep paying
        reward into the same decision.
        """
        if user_id is None:
            return None
        with self._lock:
            served = self._by_user.get(int(user_id))
            if not served:
                return None
            return served.pop(int(track_id), None)

    def is_repeat_artist(self, user_id: int | None, artist_id: int) -> bool:
        """Has this listener been served this artist recently?

        Checked before the current impression is remembered, so an artist's
        first appearance is not counted as a repeat of itself.
        """
        if user_id is None or int(artist_id) == -1:
            return False
        with self._lock:
            return int(artist_id) in (self._recent_artists.get(int(user_id)) or ())

    def peek(self, user_id: int | None, track_id: int) -> dict | None:
        if user_id is None:
            return None
        with self._lock:
            return (self._by_user.get(int(user_id)) or {}).get(int(track_id))

    def _evict_users_locked(self) -> None:
        while len(self._order) > self.max_users:
            evicted = self._order.pop(0)
            self._by_user.pop(evicted, None)
            self._recent_artists.pop(evicted, None)

    def __len__(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._by_user.values())

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "users_tracked": len(self._by_user),
                "impressions_pending": sum(len(v) for v in self._by_user.values()),
            }


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    """Write via a temp file and rename, so a crash mid-snapshot cannot leave a
    truncated state file that fails to load on the next start."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
