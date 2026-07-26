import { useEffect, useRef, useState, useCallback } from "react";

// Lightweight pub/sub so any module can call showToast(...) without needing
// to sit inside a React tree -- mirrors how lib/telegram.js's showAlert
// could be called from anywhere. <ToastHost/> (mounted once, in App.jsx)
// is the only subscriber and does the actual rendering.
let listeners = [];
let idCounter = 0;

const DEFAULT_DURATION = 3200; // ms visible before auto-fade starts
const FADE_MS = 250; // must match the CSS transition duration below
const SWIPE_DISMISS_PX = 40; // drag distance (either axis) that counts as a dismiss swipe

export function showToast(message, { duration = DEFAULT_DURATION } = {}) {
  const toast = { id: ++idCounter, message, duration };
  listeners.forEach((fn) => fn(toast));
  return toast.id;
}

// Mount once near the root (see App.jsx) -- renders whatever's currently
// queued as a stack of self-dismissing toasts. Replaces the old
// tg.showAlert(...) modal: this never blocks input, fades out on its own,
// and can be swiped away early.
export function ToastHost() {
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    const onToast = (toast) => setToasts((prev) => [...prev, { ...toast, leaving: false }]);
    listeners.push(onToast);
    return () => {
      listeners = listeners.filter((fn) => fn !== onToast);
    };
  }, []);

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.map((t) => (t.id === id ? { ...t, leaving: true } : t)));
    // Give the fade-out transition time to finish before actually removing
    // it, so it never just pops out of existence.
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, FADE_MS);
  }, []);

  if (!toasts.length) return null;

  return (
    <div className="fixed top-3 inset-x-0 z-50 flex flex-col items-center gap-2 px-6 pointer-events-none">
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onDismiss }) {
  const dragStart = useRef(null);
  // Which axis is currently driving the drag, and by how much -- a swipe up
  // and a swipe sideways should both be able to dismiss the toast.
  const [drag, setDrag] = useState({ axis: "y", offset: 0 });
  const [dragging, setDragging] = useState(false);

  // Auto-fade after `duration` -- the whole point is the user never has to
  // tap anything for this to go away.
  useEffect(() => {
    const timer = setTimeout(onDismiss, toast.duration);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast.id]);

  const onTouchStart = (e) => {
    dragStart.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
    setDragging(true);
  };

  const onTouchMove = (e) => {
    if (!dragStart.current) return;
    const dx = e.touches[0].clientX - dragStart.current.x;
    const dy = e.touches[0].clientY - dragStart.current.y;
    setDrag(Math.abs(dx) > Math.abs(dy) ? { axis: "x", offset: dx } : { axis: "y", offset: dy });
  };

  const onTouchEnd = () => {
    setDragging(false);
    dragStart.current = null;
    if (Math.abs(drag.offset) > SWIPE_DISMISS_PX) {
      onDismiss();
    } else {
      setDrag({ axis: drag.axis, offset: 0 });
    }
  };

  const translateX = drag.axis === "x" ? drag.offset : 0;
  const translateY = drag.axis === "y" ? drag.offset : 0;

  return (
    <div
      onTouchStart={onTouchStart}
      onTouchMove={onTouchMove}
      onTouchEnd={onTouchEnd}
      style={{
        transform: `translate(${translateX}px, ${translateY}px)`,
        opacity: toast.leaving ? 0 : Math.max(0, 1 - Math.abs(drag.offset) / 120),
        transition: dragging ? "none" : `opacity ${FADE_MS}ms ease, transform ${FADE_MS}ms ease`,
      }}
      className="pointer-events-auto max-w-xs w-full rounded-2xl bg-surface/95 backdrop-blur-md border border-line/60 px-4 py-3 text-sm text-paper text-center shadow-lg"
    >
      {toast.message}
    </div>
  );
}
