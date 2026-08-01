import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles, Trophy, Music2, Mic2 } from "lucide-react";
import { api } from "../lib/api";
import { pollPending } from "../lib/pollPending";
import TopBar from "../components/TopBar";
import RollableRail from "../components/RollableRail";
import TrackCard from "../components/TrackCard";
import { ArtistRailCard, ArtistGridTile } from "../components/ArtistCard";
import SearchSheet from "../components/SearchSheet";
import EmptyState from "../components/EmptyState";

// True while anything in the feed is still waiting on a background
// cover lookup (see webapp/enrichment_queue.py) -- drives whether Home
// keeps re-polling /home/feed to pick covers up as they land.
function feedHasPending(feed) {
  if (!feed) return false;
  const lists = [feed.latest_tracks, feed.latest_artists, feed.top_artists];
  return lists.some((list) => list?.some((item) => item.cover_pending));
}

export default function Home() {
  const navigate = useNavigate();
  const [searchOpen, setSearchOpen] = useState(false);
  const [feed, setFeed] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let stopPolling = () => {};
    (async () => {
      try {
        const { data } = await api.getFeed();
        if (cancelled) return;
        setFeed(data);
        // The page is already rendered with whatever covers were in the DB
        // at request time. Anything still missing gets filled in on this
        // page without a reload, as the background enrichment queue works
        // through it -- no re-fetch is triggered unless something's
        // actually pending.
        if (feedHasPending(data)) {
          stopPolling = pollPending(
            () => api.getFeed().then((res) => res.data),
            feedHasPending,
            (updated) => {
              if (!cancelled) setFeed(updated);
            }
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, []);

  return (
    <div className="pb-28">
      <TopBar onSearchClick={() => setSearchOpen(true)} />

      {/* Header menu: the signature soundwave-pulse mark + the two primary
          actions, sitting as a single row right under the top bar */}
      <section className="px-5 mt-2">
        <div className="flex items-center gap-2">
          <div className="shrink-0 bg-raised border border-line/60 rounded-xl2 px-3 h-11 flex items-center justify-center">
            <div className="wavebars text-brand/70">
              {[6, 10, 14, 9, 16, 7, 12, 5, 11].map((h, i) => (
                <span
                  key={i}
                  style={{ height: `${h}px`, animationDelay: `${i * 0.08}s` }}
                  className="animate-pulseBar"
                />
              ))}
            </div>
          </div>
          <button
            onClick={() => navigate("/suggest")}
            className="flex-1 min-w-0 flex items-center justify-center gap-1.5 bg-brand text-white font-semibold text-sm h-11 px-2 rounded-xl2 tap"
          >
            <Sparkles size={16} className="shrink-0" />
            <span className="truncate">Suggest me a song</span>
          </button>
          <button
            onClick={() => navigate("/ranks")}
            className="flex-1 min-w-0 flex items-center justify-center gap-1.5 bg-raised text-paper font-semibold text-sm h-11 px-2 rounded-xl2 border border-line/60 tap"
          >
            <Trophy size={16} className="text-pulse shrink-0" />
            <span className="truncate">Ranks</span>
          </button>
        </div>
      </section>

      <RollableRail eyebrow="Fresh drops" title="Latest songs" onSeeAll={() => navigate("/ranks?scope=tracks")} empty={!loading && "No tracks shared yet."}>
        {feed?.latest_tracks?.map((t) => <TrackCard key={t.id} track={t} context="feed" />)}
      </RollableRail>

      <RollableRail eyebrow="New in the mix" title="Latest artists" onSeeAll={() => navigate("/ranks?scope=artists")} empty={!loading && "No artists indexed yet."}>
        {feed?.latest_artists?.map((a) => <ArtistRailCard key={a.id} artist={a} />)}
      </RollableRail>

      <section className="mt-8 px-5">
        <div className="flex items-end justify-between mb-3">
          <div>
            <p className="eyebrow mb-1">Crowd favorites</p>
            <h2 className="font-display text-lg text-paper">Top artists</h2>
          </div>
        </div>
        {feed?.top_artists?.length ? (
          <div className="grid grid-cols-1 gap-2">
            {feed.top_artists.map((a, i) => (
              <ArtistGridTile key={a.id} artist={a} place={i + 1} />
            ))}
          </div>
        ) : (
          !loading && <EmptyState icon={Mic2} title="No ranked artists yet" hint="Reactions will populate this once the group gets going." />
        )}
      </section>

      {!loading && !feed?.latest_tracks?.length && (
        <div className="mt-6">
          <EmptyState icon={Music2} title="It's quiet in here" hint="Once songs start landing in the group, they'll show up here." />
        </div>
      )}

      <SearchSheet open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  );
}
