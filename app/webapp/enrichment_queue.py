"""
Central place for the app's Last.fm enrichment queue.

Cover/description policy for this app, end to end:

  1. A router/serializer needs a cover or a description for something it's
     about to return to the user. It checks the DB (the row it already has
     in hand) -- nothing else, no network call, no waiting.
  2. Found it there -> return it. Done, Last.fm is never involved.
  3. Not there -> the response still goes out immediately (the field is
     null and a `..._pending: true` flag is set alongside it) and a job is
     dropped on this module's queue. The page/template is never held up
     waiting on Last.fm.
  4. A small pool of background workers (started once, at app startup --
     see webapp/main.py) drains that queue one job at a time per worker,
     going through the existing Last.fm client (webapp/lastfm.py), which is
     itself rate-limited to Last.fm's ~5 req/s allowance. Queueing jobs
     here (instead of firing them all as loose asyncio tasks) means a page
     with many missing covers produces a bounded number of concurrent
     Last.fm calls, not an unbounded burst that all queue up inside the
     rate limiter at once.
  5. Whatever a worker finds gets persisted straight onto the track/artist
     row (see repository._fetch_and_cache_track_lastfm /
     enrich_artist_with_lastfm -- the same functions the old synchronous
     code path used to call directly).
  6. The frontend polls the same endpoint again a little later. Once a
     worker has landed, step 1's DB check now succeeds and the pending
     flag clears -- the cover/description just fades in.

This module owns *scheduling and dispatch* only. It doesn't know anything
about Last.fm, tracks, or artists -- callers pass in the coroutine to run
(a closure over repository.py's own enrichment functions) and a dedupe key
so the same job never gets queued twice while one copy is still in flight.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

NUM_WORKERS = 2

_queue: "asyncio.Queue[_Job] | None" = None
_workers: list[asyncio.Task] = []
_pending: set[str] = set()  # dedupe key -> queued or currently being processed


@dataclass
class _Job:
    key: str
    coro_factory: Callable[[], Awaitable[Any]]


def _get_queue() -> asyncio.Queue:
    global _queue
    if _queue is None:
        _queue = asyncio.Queue()
    return _queue


def is_pending(key: str) -> bool:
    """True if a job with this dedupe key is queued or currently running."""
    return key in _pending


def enqueue(key: str, coro_factory: Callable[[], Awaitable[Any]]) -> bool:
    """Schedules background work for `key` unless a job with the same key
    is already queued/running. `coro_factory` is called (to produce the
    actual coroutine) only if the job is accepted, so callers can pass a
    plain lambda without worrying about "coroutine was never awaited"
    warnings on the skipped/deduped path.

    Returns True if a new job was scheduled, False if it was deduped or if
    there's no running event loop to schedule onto (e.g. called from a
    script/test outside the app)."""
    if key in _pending:
        return False
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    _pending.add(key)
    _get_queue().put_nowait(_Job(key, coro_factory))
    return True


async def _worker(worker_id: int) -> None:
    queue = _get_queue()
    while True:
        job = await queue.get()
        try:
            await job.coro_factory()
        except Exception as e:  # best-effort background work -- never crash the worker
            print(f"[⚠️ enrichment worker {worker_id}] job '{job.key}' failed: {e}")
        finally:
            _pending.discard(job.key)
            queue.task_done()


def start_workers(num_workers: int = NUM_WORKERS) -> None:
    """Starts the background worker pool. Call once, at app startup (see
    webapp/main.py's lifespan) -- safe to call more than once, later calls
    are no-ops as long as the workers from the first call are still alive."""
    if _workers:
        return
    loop = asyncio.get_event_loop()
    for i in range(num_workers):
        _workers.append(loop.create_task(_worker(i)))


async def stop_workers() -> None:
    """Cancels all workers and clears queue/dedupe state. Call at app
    shutdown; mainly useful so tests/reloads don't accumulate zombie tasks."""
    for task in _workers:
        task.cancel()
    _workers.clear()
    _pending.clear()
