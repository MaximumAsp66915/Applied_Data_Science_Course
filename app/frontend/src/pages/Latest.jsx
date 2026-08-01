import { useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Flame, Music2, Mic2 } from "lucide-react";
import { api } from "../lib/api";
import { useInfiniteList } from "../lib/useInfiniteList";
import TrackCard from "../components/TrackCard";
import { ArtistRow } from "../components/ArtistCard";
import EmptyState from "../components/EmptyState";

const TABS = [
  { key: "tracks", label: "Tracks", icon: Music2 },
  { key: "artists", label: "Artists", icon: Mic2 },
];

export default function Latest() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const scope = params.get("scope") === "artists" ? "artists" : "tracks";

  const fetchPage = useCallback(
    (offset, limit) => api.getLatest(scope, { limit, offset }).then((res) => res.data.items ?? []),
    [scope]
  );
  const { items: data, loading, loadingMore, hasMore, sentinelRef } = useInfiniteList(fetchPage, [scope]);

  return (
    <div className="pb-16">
      <header className="sticky top-0 z-20 bg-ink/85 backdrop-blur-md px-5 pt-4 pb-3 flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="w-9 h-9 rounded-full bg-surface flex items-center justify-center tap" aria-label="Back">
          <ArrowLeft size={16} className="text-muted" />
        </button>
        <h1 className="font-display text-lg text-paper flex items-center gap-1.5">
          <Flame size={18} className="text-pulse" />
          Latest
        </h1>
      </header>

      <div className="rail flex gap-2 overflow-x-auto px-5 pb-1 mt-1 snap-x snap-mandatory">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setParams({ scope: key })}
            className={`snap-start shrink-0 flex items-center gap-1.5 px-3.5 py-2 rounded-full text-sm font-medium tap ${
              scope === key ? "bg-brand text-white" : "bg-surface text-muted border border-line/60"
            }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      <p className="px-5 mt-4 mb-2 eyebrow">Newest first</p>

      <div className="flex flex-col">
        {!loading && data?.length === 0 && (
          <EmptyState title="Nothing here yet" hint="Once the group shares more, the newest ones will show up here." />
        )}
        {scope === "tracks" &&
          // context="feed": same "walk from here toward older tracks"
          // program the home feed's own Latest-songs rail uses, so
          // starting playback from, say, the 5th track in this list
          // continues from the 5th-newest down toward the earliest one.
          data?.map((t, i) => <TrackCard key={t.id} track={t} variant="row" rank={i + 1} context="feed" />)}
        {scope === "artists" && data?.map((a, i) => <ArtistRow key={a.id} artist={a} rank={i + 1} />)}
      </div>

      {!loading && hasMore && (
        <div ref={sentinelRef} className="py-6 flex justify-center">
          {loadingMore && <span className="text-xs text-muted">Loading more…</span>}
        </div>
      )}
    </div>
  );
}
