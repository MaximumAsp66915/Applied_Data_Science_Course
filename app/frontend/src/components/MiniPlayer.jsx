import { useNavigate, useLocation } from "react-router-dom";
import { Play, Pause, SkipForward } from "lucide-react";
import { usePlayer } from "../context/PlayerContext";
import { Cover } from "./TrackCard";

export default function MiniPlayer() {
  const { track, isPlaying, togglePlay, playNext, queue, progress, duration } = usePlayer();
  const navigate = useNavigate();
  const location = useLocation();

  if (!track || location.pathname === `/song/${track.id}`) return null;

  const pct = duration > 0 ? (progress / duration) * 100 : 0;

  return (
    <button
      onClick={() => navigate(`/song/${track.id}`)}
      className="fixed left-3 right-3 bottom-3 z-30 card shadow-soft px-3 py-2.5 flex items-center gap-3 tap overflow-hidden"
    >
      <div className="absolute left-0 bottom-0 h-0.5 bg-brand" style={{ width: `${pct}%` }} />
      <Cover url={track.cover_url} size={38} />
      <div className="min-w-0 flex-1 text-left">
        <p className="truncate text-sm font-medium text-paper">{track.title || "Untitled track"}</p>
        <p className="truncate text-xs text-muted">{track.performer || "Unknown artist"}</p>
      </div>
      <span
        onClick={(e) => {
          e.stopPropagation();
          togglePlay();
        }}
        className="w-9 h-9 rounded-full bg-brand flex items-center justify-center shrink-0"
      >
        {isPlaying ? <Pause size={16} fill="white" /> : <Play size={16} fill="white" className="ml-0.5" />}
      </span>
      {track && (
        <span
          onClick={(e) => {
            e.stopPropagation();
            playNext();
          }}
          className="w-9 h-9 rounded-full bg-raised flex items-center justify-center shrink-0"
        >
          <SkipForward size={15} className="text-muted" />
        </span>
      )}
    </button>
  );
}
