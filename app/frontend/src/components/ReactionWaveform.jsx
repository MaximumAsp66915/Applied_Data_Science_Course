import { useMemo, useRef, useState } from "react";

// The signature element of SUT Music: a seek bar built from bars whose
// height is a deterministic pseudo-waveform (seeded from the track id, since
// we don't have real amplitude data), and whose color encodes the group's
// collective sentiment split (amber = likes, raspberry = dislikes) up to the
// played position. It's simultaneously a scrubber and a tiny data-viz of how
// the group reacted to the track.
function seededBars(seed, count) {
  let x = seed || 1;
  const rand = () => {
    x = (x * 9301 + 49297) % 233280;
    return x / 233280;
  };
  return Array.from({ length: count }, (_, i) => {
    const base = 0.35 + rand() * 0.65;
    const wobble = Math.sin(i * 0.7 + seed) * 0.15;
    return Math.max(0.18, Math.min(1, base + wobble));
  });
}

export default function ReactionWaveform({
  progress,
  duration,
  likes = 0,
  dislikes = 0,
  seed = 1,
  onSeek,
  barCount = 56,
}) {
  const trackRef = useRef(null);
  const [hoverPct, setHoverPct] = useState(null);

  const bars = useMemo(() => seededBars(seed, barCount), [seed, barCount]);
  const total = likes + dislikes;
  const likeRatio = total > 0 ? likes / total : 0.5;

  const playedPct = duration > 0 ? Math.min(1, progress / duration) : 0;

  const pctFromEvent = (clientX) => {
    const el = trackRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    return Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
  };

  const handleSeek = (clientX) => {
    const pct = pctFromEvent(clientX);
    onSeek?.(pct * duration);
  };

  return (
    <div className="w-full select-none">
      <div
        ref={trackRef}
        className="relative h-14 flex items-end gap-[3px] cursor-pointer touch-none"
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          handleSeek(e.clientX);
        }}
        onPointerMove={(e) => {
          setHoverPct(pctFromEvent(e.clientX));
          if (e.buttons === 1) handleSeek(e.clientX);
        }}
        onPointerLeave={() => setHoverPct(null)}
        role="slider"
        aria-label="Seek"
        aria-valuemin={0}
        aria-valuemax={duration}
        aria-valuenow={progress}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "ArrowRight") onSeek?.(Math.min(duration, progress + 5));
          if (e.key === "ArrowLeft") onSeek?.(Math.max(0, progress - 5));
        }}
      >
        {bars.map((h, i) => {
          const barPct = i / bars.length;
          const played = barPct <= playedPct;
          const color = played ? (barPct <= playedPct * likeRatio ? "bg-pulse" : "bg-rasp") : "bg-line";
          return (
            <span
              key={i}
              className={`flex-1 rounded-full transition-colors duration-150 ${color}`}
              style={{ height: `${h * 100}%`, opacity: played ? 1 : 0.55 }}
            />
          );
        })}

        {hoverPct != null && (
          <div
            className="absolute top-0 bottom-0 w-px bg-paper/40"
            style={{ left: `${hoverPct * 100}%` }}
          />
        )}
      </div>

      <div className="mt-2 flex items-center justify-between text-[11px] font-mono text-muted">
        <span>{formatTime(progress)}</span>
        <span className="flex items-center gap-2">
          <span className="text-pulse">{Math.round(likeRatio * 100)}% liked</span>
        </span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  );
}

function formatTime(s) {
  if (!Number.isFinite(s) || s < 0) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60)
    .toString()
    .padStart(2, "0");
  return `${m}:${sec}`;
}
