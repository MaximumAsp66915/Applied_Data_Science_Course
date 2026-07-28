import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ThumbsUp, ThumbsDown } from "lucide-react";
import { api } from "../lib/api";
import { pollPending } from "../lib/pollPending";
import { Cover } from "../components/TrackCard";
import { RankBadge } from "../components/Trophy";
import RollableRail from "../components/RollableRail";
import TrackCard from "../components/TrackCard";
import { whenIdle } from "../lib/idle";

const PAGE_SIZE = 20;
// How many extra pages beyond the first screenful to quietly warm up in the
// background -- enough that scrolling through the whole rail rarely hits a
// live network request, without turning every artist page visit into an
// unbounded background crawl of their entire discography.
const MAX_BACKGROUND_PAGES = 3;

export default function ArtistPage() {
  const { artistId } = useParams();
  const navigate = useNavigate();
  const [artist, setArtist] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    let stopArtistPolling = () => {};
    let stopTrackPolling = () => {};
    setLoading(true);
    setTracks([]);
    (async () => {
      const [artistRes, tracksRes] = await Promise.all([
        api.getArtist(artistId),
        api.getArtistTracks(artistId, { limit: PAGE_SIZE, offset: 0 }),
      ]);
      if (cancelled) return;
      setArtist(artistRes.data);
      const firstPage = tracksRes.data.items ?? [];
      setTracks(firstPage);
      setLoading(false);

      // The artist page (name, stats) is already fully renderable from
      // what came back above. If the bio/cover weren't in the DB yet, this
      // response has them as null with `..._pending: true`, and a
      // background job is already queued to fetch them (see
      // webapp/enrichment_queue.py). Poll the same endpoint again until
      // both land, instead of leaving the bio/photo blank forever.
      if (artistRes.data?.description_pending || artistRes.data?.cover_pending) {
        stopArtistPolling = pollPending(
          () => api.getArtist(artistId).then((res) => res.data),
          (a) => a?.description_pending || a?.cover_pending,
          (updated) => {
            if (!cancelled) setArtist(updated);
          }
        );
      }

      // Covers for the tracks just loaded may still be pending (see
      // webapp/enrichment_queue.py) -- poll for them too, merging updates
      // into whichever rows have since resolved.
      if (firstPage.some((t) => t.cover_pending)) {
        stopTrackPolling = pollPending(
          () => api.getArtistTracks(artistId, { limit: PAGE_SIZE, offset: 0 }).then((res) => res.data.items ?? []),
          (items) => items.some((t) => t.cover_pending),
          (updatedItems) => {
            if (cancelled) return;
            const byId = new Map(updatedItems.map((t) => [t.id, t]));
            setTracks((prev) => prev.map((t) => byId.get(t.id) ?? t));
          }
        );
      }

      // The first page is enough to render immediately; everything after
      // that trickles in during idle time in the background, exactly the
      // "gradually load in the background, ready before it's asked for"
      // behavior requested for artist/track pages, without blocking the
      // page or competing with anything the user is actively doing.
      if (firstPage.length === PAGE_SIZE) {
        let cancelledBackground = false;
        const stopHandles = [];
        (async () => {
          let offset = PAGE_SIZE;
          for (let page = 0; page < MAX_BACKGROUND_PAGES; page++) {
            const gotMore = await new Promise((resolve) => {
              const stop = whenIdle(async () => {
                if (cancelled || cancelledBackground) return resolve(false);
                try {
                  const { data } = await api.getArtistTracks(artistId, {
                    limit: PAGE_SIZE,
                    offset,
                  });
                  const nextItems = data.items ?? [];
                  if (cancelled || cancelledBackground) return resolve(false);
                  if (nextItems.length === 0) return resolve(false);
                  setTracks((prev) => [...prev, ...nextItems]);
                  offset += PAGE_SIZE;
                  resolve(nextItems.length === PAGE_SIZE);
                } catch {
                  resolve(false);
                }
              });
              stopHandles.push(stop);
            });
            if (!gotMore) break;
          }
        })();
        return () => {
          cancelledBackground = true;
          stopHandles.forEach((stop) => stop());
        };
      }
    })();
    return () => {
      cancelled = true;
      stopArtistPolling();
      stopTrackPolling();
    };
  }, [artistId]);

  return (
    <div className="pb-16">
      <header className="sticky top-0 z-20 bg-ink/85 backdrop-blur-md px-5 pt-4 pb-3 flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="w-9 h-9 rounded-full bg-surface flex items-center justify-center tap" aria-label="Back">
          <ArrowLeft size={16} className="text-muted" />
        </button>
        <h1 className="font-display text-lg text-paper">Artist</h1>
      </header>

      <section className="px-5 flex items-center gap-4 mt-2">
        <Cover url={artist?.cover_url} size={72} rounded="rounded-full" />
        <div className="min-w-0">
          <h1 className="font-display text-xl text-paper truncate">{loading ? "…" : artist?.name}</h1>
          <div className="mt-1.5"><RankBadge rank={artist?.rank} /></div>
        </div>
      </section>

      {artist?.description && (
        <p className="px-5 mt-4 text-sm text-muted leading-relaxed">{artist.description}</p>
      )}

      <section className="px-5 mt-5 grid grid-cols-3 gap-2">
        <Stat label="Score" value={artist?.score ?? "—"} />
        <Stat label="Likes" value={artist?.likes_count ?? 0} icon={ThumbsUp} tone="text-pulse" />
        <Stat label="Dislikes" value={artist?.dislikes_count ?? 0} icon={ThumbsDown} tone="text-rasp" />
      </section>

      <RollableRail
        eyebrow="Discography"
        title="Tracks in the group"
        empty={!loading && "No tracks indexed for this artist yet."}
      >
        {tracks.map((t) => (
          <TrackCard key={t.id} track={t} context="artist" />
        ))}
      </RollableRail>
    </div>
  );
}

function Stat({ label, value, icon: Icon, tone = "text-paper" }) {
  return (
    <div className="card p-3">
      <div className={`flex items-center gap-1.5 font-mono text-lg ${tone}`}>
        {Icon && <Icon size={14} />}
        {value}
      </div>
      <p className="text-[11px] text-muted mt-0.5">{label}</p>
    </div>
  );
}
