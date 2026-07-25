import { useNavigate } from "react-router-dom";
import { ThumbsUp } from "lucide-react";
import { Cover } from "./TrackCard";

export function ArtistRailCard({ artist }) {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate(`/artist/${artist.id}`)}
      className="snap-start shrink-0 w-28 text-center tap"
    >
      <Cover url={artist.cover_url} size={112} rounded="rounded-full" />
      <p className="mt-2 truncate text-sm font-medium text-paper">{artist.name}</p>
      <p className="text-[11px] font-mono text-pulse flex items-center justify-center gap-1">
        <ThumbsUp size={10} />
        {artist.likes_count}
      </p>
    </button>
  );
}

// Compact grid tile for "Top artists" grid on Home
export function ArtistGridTile({ artist, place }) {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate(`/artist/${artist.id}`)}
      className="card p-3 flex items-center gap-3 tap text-left"
    >
      <span className="font-display text-base text-muted w-4">{place}</span>
      <Cover url={artist.cover_url} size={44} rounded="rounded-full" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-paper">{artist.name}</p>
        <p className="text-[11px] font-mono text-muted">{artist.reactions_count} reactions</p>
      </div>
    </button>
  );
}

export function ArtistRow({ artist, rank }) {
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate(`/artist/${artist.id}`)}
      className="w-full flex items-center gap-3 px-4 py-3 hover:bg-raised/60 rounded-xl2 tap text-left"
    >
      {rank && <span className="w-5 shrink-0 font-mono text-sm text-muted text-center">{rank}</span>}
      <Cover url={artist.cover_url} size={44} rounded="rounded-full" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-paper">{artist.name}</p>
        <p className="text-[11px] text-muted">{artist.rank}</p>
      </div>
      <span className="flex items-center gap-1 text-xs font-mono text-pulse shrink-0">
        <ThumbsUp size={12} />
        {artist.likes_count}
      </span>
    </button>
  );
}
