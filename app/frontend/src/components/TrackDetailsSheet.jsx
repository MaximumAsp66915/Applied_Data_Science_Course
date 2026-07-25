import { useNavigate } from "react-router-dom";
import { ChevronUp, ThumbsUp, ThumbsDown, Music2 } from "lucide-react";
import { Avatar } from "./UserCard";

// Spotify-style "swipe up for details" sheet. Drag state (`dragY`/`dragging`)
// and the `bind` touch handlers come from a single useSwipeUp() instance
// owned by SongPage, so the whole now-playing view, the collapsed handle,
// and this sheet's own header strip all share one continuous gesture.
export default function TrackDetailsSheet({ open, onOpenChange, details, loading, track, dragY, dragging, bind }) {
  const navigate = useNavigate();

  // translateY as a percentage of the sheet's own height: 0 = fully open,
  // 100 = fully closed (tucked below the viewport, just the handle showing).
  const dragPercent = dragY ? (dragY / (window.innerHeight * 0.7)) * 100 : 0;
  const basePercent = open ? 0 : 100;
  const translatePercent = Math.min(100, Math.max(0, basePercent + dragPercent));

  return (
    <>
      {/* Backdrop: fades in as the sheet opens, tap to dismiss */}
      <div
        onClick={() => onOpenChange(false)}
        className="fixed inset-0 z-30 bg-ink/70 backdrop-blur-sm transition-opacity duration-300"
        style={{
          opacity: open ? 1 : 0,
          pointerEvents: open ? "auto" : "none",
        }}
      />

      {/* Drag handle -- always present at the bottom of the now-playing
          view so there's something to grab even before the sheet has ever
          been opened. */}
      {!open && (
        <button
          {...bind}
          onClick={() => onOpenChange(true)}
          className="fixed left-1/2 -translate-x-1/2 z-30 flex flex-col items-center gap-0.5 text-muted tap"
          style={{ bottom: "max(env(safe-area-inset-bottom), 14px)" }}
          aria-label="Show track details"
        >
          <ChevronUp size={16} />
          <span className="w-10 h-1 rounded-full bg-line/70" />
        </button>
      )}

      <div
        className="fixed inset-x-0 bottom-0 z-40 h-[85vh] max-h-[85vh] rounded-t-3xl bg-surface border-t border-line/60 flex flex-col"
        style={{
          transform: `translateY(${translatePercent}%)`,
          transition: dragging ? "none" : "transform 280ms cubic-bezier(0.22, 1, 0.36, 1)",
        }}
      >
        <div
          {...bind}
          onClick={() => onOpenChange(false)}
          className="pt-3 pb-2 flex flex-col items-center gap-2 shrink-0 tap"
        >
          <span className="w-10 h-1 rounded-full bg-line/70" />
          <p className="text-xs text-muted">Track details</p>
        </div>

        <div className="flex-1 overflow-y-auto px-5 pb-10">
          {loading && !details ? (
            <p className="text-sm text-muted text-center mt-10">Loading details…</p>
          ) : (
            <>
              <section className="mt-2">
                <p className="eyebrow mb-1.5">About this track</p>
                <p className="text-sm text-paper/90 leading-relaxed">
                  {details?.description || "No description available for this track yet."}
                </p>
              </section>

              {details?.artists?.length > 0 && (
                <section className="mt-6">
                  <p className="eyebrow mb-2">Artists</p>
                  <div className="flex flex-wrap gap-2">
                    {details.artists.map((a) => (
                      <button
                        key={a.id}
                        onClick={() => {
                          onOpenChange(false);
                          navigate(`/artist/${a.id}`);
                        }}
                        className="flex items-center gap-2 pl-1 pr-3 py-1 rounded-full bg-raised border border-line/60 tap"
                      >
                        <Avatar url={a.cover_url} size={26} />
                        <span className="text-sm text-paper">{a.name}</span>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              {details?.uploaders?.length > 0 && (
                <section className="mt-6">
                  <p className="eyebrow mb-2">Shared by</p>
                  <div className="flex flex-wrap gap-2">
                    {details.uploaders.map((u) => (
                      <button
                        key={u.user_id}
                        onClick={() => {
                          onOpenChange(false);
                          navigate(`/user/${u.user_id}`);
                        }}
                        className="flex items-center gap-2 pl-1 pr-3 py-1 rounded-full bg-raised border border-line/60 tap"
                      >
                        <Avatar url={u.profile_photo} size={26} />
                        <span className="text-sm text-paper">{u.first_name || u.username || "Listener"}</span>
                      </button>
                    ))}
                  </div>
                </section>
              )}

              <section className="mt-6">
                <p className="eyebrow mb-2 flex items-center gap-3">
                  <span>Reactions</span>
                  <span className="flex items-center gap-1 text-pulse font-mono text-[11px]">
                    <ThumbsUp size={11} />
                    {track?.likes_count ?? 0}
                  </span>
                  <span className="flex items-center gap-1 text-rasp font-mono text-[11px]">
                    <ThumbsDown size={11} />
                    {track?.dislikes_count ?? 0}
                  </span>
                </p>
                {details?.reactions?.length > 0 ? (
                  <div className="flex flex-col gap-1">
                    {details.reactions.map((r, i) => (
                      <button
                        key={`${r.user_id}-${i}`}
                        onClick={() => {
                          onOpenChange(false);
                          navigate(`/user/${r.user_id}`);
                        }}
                        className="w-full flex items-center gap-3 px-2 py-2 hover:bg-raised/60 rounded-xl2 tap text-left"
                      >
                        <Avatar url={r.profile_photo} size={32} />
                        <span className="text-sm text-paper flex-1 truncate">
                          {r.first_name || r.username || "Listener"}
                        </span>
                        <span className="text-base shrink-0">
                          {r.emoji || (r.sentiment === "like" ? "👍" : r.sentiment === "dislike" ? "👎" : "•")}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-sm text-muted py-3">
                    <Music2 size={14} />
                    No reactions yet -- be the first.
                  </div>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </>
  );
}
