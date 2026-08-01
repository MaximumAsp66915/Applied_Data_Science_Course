import { useCallback, useEffect, useRef, useState } from "react";

const PAGE_SIZE = 50;

// Shared "load 50 more as the user scrolls" behavior for Ranks/Latest.
// `fetchPage(offset, limit)` should resolve to an array of items.
// Resets to page 1 whenever anything in `resetDeps` changes (e.g. the
// active scope tab).
export function useInfiniteList(fetchPage, resetDeps = []) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true); // initial page for this scope
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(true);
  const offsetRef = useRef(0);
  const sentinelRef = useRef(null);
  const fetchPageRef = useRef(fetchPage);
  fetchPageRef.current = fetchPage;

  useEffect(() => {
    let cancelled = false;
    offsetRef.current = 0;
    setItems([]);
    setHasMore(true);
    setLoading(true);
    (async () => {
      const rows = await fetchPageRef.current(0, PAGE_SIZE);
      if (cancelled) return;
      setItems(rows);
      offsetRef.current = rows.length;
      setHasMore(rows.length === PAGE_SIZE);
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, resetDeps);

  const loadMore = useCallback(async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    const rows = await fetchPageRef.current(offsetRef.current, PAGE_SIZE);
    setItems((prev) => [...prev, ...rows]);
    offsetRef.current += rows.length;
    setHasMore(rows.length === PAGE_SIZE);
    setLoadingMore(false);
  }, [hasMore, loadingMore]);

  // Fires loadMore whenever the sentinel div at the bottom of the list
  // scrolls into view -- no manual scroll-position math needed.
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMore();
      },
      { rootMargin: "600px" }
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMore]);

  return { items, loading, loadingMore, hasMore, sentinelRef };
}
