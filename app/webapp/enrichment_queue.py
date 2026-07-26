"""
Central place for the app's background enrichment queues.

Cover/description policy for this app, end to end:

  1. A router/serializer needs a cover or a description for something it's
     about to return to the user. It checks the DB (the row it already has
     in hand) -- nothing else, no network call, no waiting.
  2. Found it there -> return it. Done, the external API is never involved.
  3. Not there -> the response still goes out immediately (the field is
     null and a `..._pending: true` flag is set alongside it) and a job is
     dropped on a queue in this module. The page/template is never held up
     waiting on an external API.
  4. A small pool of background workers (started once, at app startup --
     see webapp/main.py) drains that queue one job at a time per worker.
  5. Whatever a worker finds gets persisted straight onto the track/artist
     row (see repository._fetch_and_cache_track_lastfm /
     enrich_artist_with_lastfm).
  6. The frontend polls the same endpoint again a little later. Once a
     worker has landed, step 1's DB check now succeeds and the pending
     flag clears -- the cover/description just fades in.

Two independent queues, not one shared one:

  Tracks and artists are enriched from different external APIs with very
  different rate/latency profiles -- tracks go through Last.fm alone
  (~5 req/s, one call, see webapp/lastfm.py); artists go through Last.fm
  *and* MusicBrainz+fanart.tv (MusicBrainz capped at 1 req/s, and
  fanart.tv's 429 handling can sleep a worker for several seconds per
  retry, see webapp/fanart.py). A single artist job can therefore tie up
  a worker for a lot longer than a track job ever does.

  If both job types drained from one shared queue/worker pool, a burst of
  new artists (e.g. a cold home-feed load) could occupy every worker for
  many seconds each, and fast track jobs queued behind them would sit
  waiting even though Last.fm itself would've served them almost
  instantly -- head-of-line blocking one API's slowness onto the other's
  covers. Giving each its own EnrichmentQueue (own asyncio.Queue, own
  worker pool, own dedupe set) keeps the concept identical for both while
  making sure a slow artist lookup can never delay a track cover, or vice
  versa.

This module owns *scheduling and dispatch* only. It doesn't know anything
about Last.fm, tracks, or artists -- callers pass in the coroutine to run
(a closure over repository.py's own enrichment functions) and a dedupe key
so the same job never gets queued twice while one copy is still in flight.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

# Track enrichment is a single, fast (~5 req/s) Last.fm call per job -- 2
# workers comfortably keep up with it.
NUM_TRACK_WORKERS = 2

# Artist enrichment can involve a 1 req/s MusicBrainz lookup plus fanart.tv
# retry-after sleeps of several seconds each -- a few extra workers let
# other artists' MusicBrainz/Last.fm calls keep moving while one worker is
# stuck sleeping through a fanart.tv retry.
NUM_ARTIST_WORKERS = 3


@dataclass
class _Job:
    key: str
    coro_factory: Callable[[], Awaitable[Any]]


class EnrichmentQueue:
    """One independent queue + worker pool + dedupe set. Track and artist
    enrichment each get their own instance (see `track_queue` /
    `artist_queue` below) so neither's external-API latency can block the
    other's jobs -- see this module's docstring for why that matters."""

    def __init__(self, name: str, num_workers: int):
        self.name = name
        self.num_workers = num_workers
        self._queue: "asyncio.Queue[_Job] | None" = None
        self._workers: list[asyncio.Task] = []
        self._pending: set[str] = set()  # dedupe key -> queued or currently being processed

    def _get_queue(self) -> asyncio.Queue:
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue

    def is_pending(self, key: str) -> bool:
        """True if a job with this dedupe key is queued or currently running."""
        return key in self._pending

    def enqueue(self, key: str, coro_factory: Callable[[], Awaitable[Any]]) -> bool:
        """Schedules background work for `key` unless a job with the same key
        is already queued/running. `coro_factory` is called (to produce the
        actual coroutine) only if the job is accepted, so callers can pass a
        plain lambda without worrying about "coroutine was never awaited"
        warnings on the skipped/deduped path.

        Returns True if a new job was scheduled, False if it was deduped or
        if there's no running event loop to schedule onto (e.g. called from
        a script/test outside the app)."""
        if key in self._pending:
            return False
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        self._pending.add(key)
        self._get_queue().put_nowait(_Job(key, coro_factory))
        return True

    async def _worker(self, worker_id: int) -> None:
        queue = self._get_queue()
        while True:
            job = await queue.get()
            try:
                await job.coro_factory()
            except Exception as e:  # best-effort background work -- never crash the worker
                print(f"[⚠️ {self.name} enrichment worker {worker_id}] job '{job.key}' failed: {e}")
            finally:
                self._pending.discard(job.key)
                queue.task_done()

    def start_workers(self) -> None:
        """Starts this queue's background worker pool. Call once, at app
        startup (see webapp/main.py's lifespan) -- safe to call more than
        once, later calls are no-ops as long as the workers from the first
        call are still alive."""
        if self._workers:
            return
        loop = asyncio.get_event_loop()
        for i in range(self.num_workers):
            self._workers.append(loop.create_task(self._worker(i)))

    async def stop_workers(self) -> None:
        """Cancels all workers and clears queue/dedupe state. Call at app
        shutdown; mainly useful so tests/reloads don't accumulate zombie
        tasks."""
        for task in self._workers:
            task.cancel()
        self._workers.clear()
        self._pending.clear()


# One queue per enrichment kind -- see this module's docstring for why they
# aren't shared.
track_queue = EnrichmentQueue("track", NUM_TRACK_WORKERS)
artist_queue = EnrichmentQueue("artist", NUM_ARTIST_WORKERS)

_all_queues = (track_queue, artist_queue)


def start_workers() -> None:
    """Starts every queue's worker pool. Call once, at app startup (see
    webapp/main.py's lifespan)."""
    for q in _all_queues:
        q.start_workers()


async def stop_workers() -> None:
    """Stops every queue's worker pool. Call at app shutdown."""
    for q in _all_queues:
        await q.stop_workers()
