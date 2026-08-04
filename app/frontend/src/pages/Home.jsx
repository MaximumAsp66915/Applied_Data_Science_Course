import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Sparkles, Trophy, Flame, Music2, Mic2, ChevronRight } from "lucide-react";
import { api } from "../lib/api";
import { pollPending } from "../lib/pollPending";
import TopBar from "../components/TopBar";
import RollableRail from "../components/RollableRail";
import TrackCard from "../components/TrackCard";
import { ArtistRailCard, ArtistGridTile } from "../components/ArtistCard";
import SearchSheet from "../components/SearchSheet";
import EmptyState from "../components/EmptyState";
import { usePlayer } from "../context/PlayerContext";

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
  const { track: nowPlaying, isPlaying } = usePlayer();
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

      {/* Header menu: the signature soundwave-pulse mark (now a real "now
          playing" shortcut) + the primary actions, right under the top bar */}
      <section className="px-5 mt-2">
        <div className="flex items-center gap-2">
          <button
            onClick={() => nowPlaying && navigate(`/song/${nowPlaying.id}`)}
            disabled={!nowPlaying}
            aria-label={nowPlaying ? `Now playing: ${nowPlaying.title || "current track"}` : "Nothing playing right now"}
            className={`shrink-0 bg-raised border border-line/60 rounded-xl2 px-3 h-11 flex items-center justify-center tap ${
              nowPlaying ? "" : "opacity-40"
            }`}
          >
            <div className="wavebars text-brand/70">
              {[6, 10, 14, 9, 16, 7, 12, 5, 11].map((h, i) => (
                <span
                  key={i}
                  style={{ height: `${h}px`, animationDelay: `${i * 0.08}s` }}
                  className={nowPlaying && isPlaying ? "animate-pulseBar" : ""}
                />
              ))}
            </div>
          </button>
          <button
            onClick={() => navigate("/suggest")}
            className="flex-1 min-w-0 flex items-center justify-center gap-1.5 bg-brand text-white font-semibold text-sm min-h-11 px-3 py-2 rounded-xl2 tap text-center leading-tight"
          >
            <Sparkles size={16} className="shrink-0" />
            <span>Suggest me a song</span>
          </button>
        </div>

        <div className="mt-2 flex items-center gap-2">
          <button
            onClick={() => navigate("/ranks")}
            className="flex-1 min-w-0 flex items-center justify-center gap-1.5 bg-raised text-paper font-semibold text-sm min-h-11 px-3 py-2 rounded-xl2 border border-line/60 tap text-center leading-tight"
          >
            <Trophy size={16} className="text-pulse shrink-0" />
            <span>Ranks</span>
          </button>
          <button
            onClick={() => navigate("/latest")}
            className="flex-1 min-w-0 flex items-center justify-center gap-1.5 bg-raised text-paper font-semibold text-sm min-h-11 px-3 py-2 rounded-xl2 border border-line/60 tap text-center leading-tight"
          >
            <Flame size={16} className="text-pulse shrink-0" />
            <span>Latest</span>
          </button>
        </div>
      </section>

      <RollableRail eyebrow="Fresh drops" title="Latest songs" onSeeAll={() => navigate("/latest?scope=tracks")} empty={!loading && "No tracks shared yet."}>
        {feed?.latest_tracks?.map((t) => <TrackCard key={t.id} track={t} context="feed" />)}
      </RollableRail>

      <RollableRail eyebrow="New in the mix" title="Latest artists" onSeeAll={() => navigate("/latest?scope=artists")} empty={!loading && "No artists indexed yet."}>
        {feed?.latest_artists?.map((a) => <ArtistRailCard key={a.id} artist={a} />)}
      </RollableRail>

      <section className="mt-8 px-5">
        <div className="flex items-end justify-between mb-3">
          <div>
            <p className="eyebrow mb-1">Crowd favorites</p>
            <h2 className="font-display text-lg text-paper">Top artists</h2>
          </div>
          <button
            onClick={() => navigate("/ranks?scope=artists")}
            className="flex items-center gap-0.5 text-xs font-semibold text-muted hover:text-brand-glow tap"
          >
            See all <ChevronRight size={14} />
          </button>
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
