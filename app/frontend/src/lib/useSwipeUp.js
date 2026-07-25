import { useCallback, useRef, useState } from "react";

const OPEN_THRESHOLD = 70; // px of vertical drag before a release counts as a toggle

/**
 * Shared drag state for the Spotify-style "swipe up on the now-playing view
 * for track details" gesture. Returns `dragY` (live finger offset while
 * dragging, 0 otherwise) and `bind` -- spread onto any element that should
 * respond to the swipe (the whole now-playing content area, and the sheet's
 * own handle) so both trigger the exact same open/close behavior.
 */
export default function useSwipeUp(open, onOpenChange) {
  const [dragY, setDragY] = useState(0);
  const dragState = useRef(null);

  const onTouchStart = useCallback((e) => {
    dragState.current = { startY: e.touches[0].clientY };
  }, []);

  const onTouchMove = useCallback(
    (e) => {
      if (!dragState.current) return;
      const delta = e.touches[0].clientY - dragState.current.startY;
      // Closed: only upward drags matter. Open: only downward drags matter.
      setDragY(open ? Math.max(0, delta) : Math.min(0, delta));
    },
    [open]
  );

  const onTouchEnd = useCallback(() => {
    if (!dragState.current) return;
    dragState.current = null;
    setDragY((delta) => {
      if (!open && delta < -OPEN_THRESHOLD) onOpenChange(true);
      else if (open && delta > OPEN_THRESHOLD) onOpenChange(false);
      return 0;
    });
  }, [open, onOpenChange]);

  return {
    dragY,
    dragging: dragState.current != null,
    bind: { onTouchStart, onTouchMove, onTouchEnd },
  };
}
