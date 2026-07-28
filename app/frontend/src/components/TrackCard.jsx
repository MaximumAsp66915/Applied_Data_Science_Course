import { useNavigate } from "react-router-dom";
import { ThumbsUp, ThumbsDown, Music2 } from "lucide-react";
import { usePlayer } from "../context/PlayerContext";

// variant "rail": fixed-width card for horizontal rails
// variant "row": full-width row for lists (search results, ranks)
// `context`: where this track is being played FROM (see PlayerContext.jsx /
// api.getTrackQueue) -- "artist", "top", "feed", "profile_sent:<id>",
// "profile_liked:<id>", etc. Determines what plays next once the user
// reaches the live edge of their history. Left undefined defaults to the
// artist-cascade program on the backend.
export default function TrackCard({ track, variant = "rail", rank, context }) {
  const navigate = useNavigate();
  const { playTrack } = usePlayer();

  const open = () => {
    playTrack(track, context);
    navigate(`/song/${track.id}`);
  };

  if (variant === "row") {
    return (
      <button
        onClick={open}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-raised/60 rounded-xl2 tap text-left"
      >
        {rank && (
          <span className="w-5 shrink-0 font-mono text-sm text-muted text-center">{rank}</span>
        )}
        <Cover url={track.cover_url} size={46} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-paper text-sm">{track.title || "Untitled track"}</p>
          <p className="truncate text-xs text-muted">{track.performer || "Unknown artist"}</p>
        </div>
        <div className="flex items-center gap-2 text-xs font-mono text-muted shrink-0">
          <span className="flex items-center gap-1 text-pulse"><ThumbsUp size={12} />{track.likes_count}</span>
          <span className="flex items-center gap-1 text-rasp"><ThumbsDown size={12} />{track.dislikes_count}</span>
        </div>
      </button>
    );
  }

  return (
    <button
      onClick={open}
      className="snap-start shrink-0 w-36 text-left tap"
    >
      <Cover url={track.cover_url} size={144} rounded="rounded-xl2" />
      <p className="mt-2 truncate font-medium text-sm text-paper">{track.title || "Untitled track"}</p>
      <p className="truncate text-xs text-muted">{track.performer || "Unknown artist"}</p>
      <div className="mt-1 flex items-center gap-2 text-[11px] font-mono text-muted">
        <span className="flex items-center gap-1 text-pulse"><ThumbsUp size={11} />{track.likes_count}</span>
        <span className="flex items-center gap-1 text-rasp"><ThumbsDown size={11} />{track.dislikes_count}</span>
      </div>
    </button>
  );
}

export function Cover({ url, size = 60, rounded = "rounded-lg" }) {
  return (
    <div
      className={`bg-raised ${rounded} overflow-hidden shrink-0 flex items-center justify-center border border-line/60`}
      style={{ width: size, height: size }}
    >
      {url ? (
        <img key={url} src={url} alt="" className="w-full h-full object-cover" loading="lazy" />
      ) : (
        <Music2 className="text-muted" size={size * 0.4} />
      )}
    </div>
  );
}
