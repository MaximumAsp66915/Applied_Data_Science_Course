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

  // Kept current via a ref so the observer below (attached once, via a
  // ref callback) always calls the latest version without needing to be
  // re-created/re-attached every time hasMore/loadingMore change.
  const loadMoreRef = useRef(async () => {});
  loadMoreRef.current = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    const rows = await fetchPageRef.current(offsetRef.current, PAGE_SIZE);
    setItems((prev) => [...prev, ...rows]);
    offsetRef.current += rows.length;
    setHasMore(rows.length === PAGE_SIZE);
    setLoadingMore(false);
  };

  const observerInstanceRef = useRef(null);

  // A ref *callback* instead of a plain useRef: React invokes this the
  // instant the sentinel <div> actually mounts (or unmounts), so the
  // IntersectionObserver is guaranteed to attach to the real node --
  // unlike a plain useRef + useEffect pair, which only re-runs when its
  // own dependencies change and can miss the node appearing later (e.g.
  // once the initial "loading" page finishes and the sentinel first
  // renders), which was exactly why "load more" stopped after page one.
  const sentinelRef = useCallback((node) => {
    if (observerInstanceRef.current) {
      observerInstanceRef.current.disconnect();
      observerInstanceRef.current = null;
    }
    if (!node) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) loadMoreRef.current();
      },
      { rootMargin: "600px" }
    );
    observer.observe(node);
    observerInstanceRef.current = observer;
  }, []);

  useEffect(() => {
    return () => {
      if (observerInstanceRef.current) observerInstanceRef.current.disconnect();
    };
  }, []);

  return { items, loading, loadingMore, hasMore, sentinelRef };
}
