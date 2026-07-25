// requestIdleCallback isn't available in every WebView the Mini App gets
// embedded in (notably Safari), so this falls back to a short setTimeout --
// still yields to the current render/interaction instead of firing inline,
// which is all the "don't overwhelm the system" background-prefetch code in
// this app actually needs.
export function whenIdle(fn, { timeout = 1500 } = {}) {
  if (typeof window !== "undefined" && "requestIdleCallback" in window) {
    const handle = window.requestIdleCallback(fn, { timeout });
    return () => window.cancelIdleCallback(handle);
  }
  const handle = setTimeout(fn, 200);
  return () => clearTimeout(handle);
}
