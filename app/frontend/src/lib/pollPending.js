// The backend never fetches covers/descriptions from Last.fm ahead of a
// request -- a page loads immediately with whatever's already in the DB,
// and anything missing comes back as null plus a `..._pending: true` flag
// while a background job goes to fetch it (see webapp/enrichment_queue.py).
// This helper re-polls a "fetch" call every `interval` ms, for as long as
// `hasPending(data)` says something's still missing, so the UI can just
// re-render with each successive response and watch covers/text fade in.
//
// Returns a `stop()` function -- call it on unmount/param change to cancel
// any polling still in flight.
export function pollPending(fetchFn, hasPending, onUpdate, { interval = 1500, maxAttempts = 20 } = {}) {
  let cancelled = false;
  let attempts = 0;

  const tick = async () => {
    if (cancelled || attempts >= maxAttempts) return;
    attempts += 1;
    try {
      const data = await fetchFn();
      if (cancelled) return;
      onUpdate(data);
      if (hasPending(data)) {
        setTimeout(tick, interval);
      }
    } catch {
      // Transient failure -- just try again on the next tick rather than
      // giving up on filling in the cover/description for this session.
      setTimeout(tick, interval);
    }
  };

  setTimeout(tick, interval);

  return () => {
    cancelled = true;
  };
}
