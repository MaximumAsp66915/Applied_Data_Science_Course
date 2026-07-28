import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ChevronDown, Download, SkipBack, SkipForward, Play, Pause, ThumbsUp, ThumbsDown, User } from "lucide-react";
import { api } from "../lib/api";
import { pollPending } from "../lib/pollPending";
import { usePlayer } from "../context/PlayerContext";
import { useUser } from "../context/UserContext";
import { Cover } from "../components/TrackCard";
import ReactionWaveform from "../components/ReactionWaveform";
import TrackDetailsSheet from "../components/TrackDetailsSheet";
import useSwipeUp from "../lib/useSwipeUp";
import { hapticImpact } from "../lib/telegram";
import { showToast } from "../components/Toast";

// "Shared by" can list an arbitrary number of uploaders -- past this many
// names we collapse the rest into "+N more" instead of letting the line
// wrap indefinitely and push the rest of the layout around.
const MAX_UPLOADERS_SHOWN = 3;

export default function SongPage() {
  const { trackId } = useParams();
  const navigate = useNavigate();
  const {
    track,
    isPlaying,
    progress,
    duration,
    myReaction,
    queue,
    queueLoading,
    playTrack,
    togglePlay,
    seekTo,
    playNext,
    playPrev,
    react,
  } = usePlayer();
  const { profile } = useUser();
  const [showAllUploaders, setShowAllUploaders] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [details, setDetails] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const swipe = useSwipeUp(detailsOpen, setDetailsOpen);

  const handleDownload = async () => {
    if (downloading || !track?.id) return;
    hapticImpact("light");
    setDownloading(true);
    try {
      const { data } = await api.downloadTrack(track.id);
      if (data?.sent) {
        showToast("Sent! Check your chat with the bot.");
      } else if (data?.reason === "not_started") {
        showToast("Please exit the mini app, press Start in your chat with the bot, then try again.");
      } else {
        showToast("Couldn't send the track. Please try again.");
      }
    } catch {
      showToast("Couldn't send the track. Please try again.");
    } finally {
      setDownloading(false);
    }
  };

  // If the page is opened directly (deep link / refresh) rather than via a
  // card tap, fetch the track and start it.
  useEffect(() => {
    if (track?.id === Number(trackId)) return;
    (async () => {
      const { data } = await api.getTrack(trackId);
      playTrack(data);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trackId]);

  useEffect(() => {
    setShowAllUploaders(false);
    setDetailsOpen(false);
  }, [trackId]);

  // Pre-load the swipe-up sheet's data in the background as soon as the
  // track is known, so it's already sitting there ready the moment someone
  // actually swipes up -- same "prepare the next thing before it's asked
  // for" idea used for queue prefetching in PlayerContext.
  useEffect(() => {
    let cancelled = false;
    let stopPolling = () => {};
    setDetails(null);
    if (!track?.id) return;
    setDetailsLoading(true);
    (async () => {
      try {
        const { data } = await api.getTrackDetails(track.id);
        if (cancelled) return;
        setDetails(data);
        // The sheet (and the cover above it) is already rendered from
        // whatever was in the DB. If the description/cover weren't synced
        // from Last.fm yet, `data` says so via the `..._pending` flags and
        // a background job is already queued (see
        // webapp/enrichment_queue.py) -- poll the same endpoint again
        // until both land, rather than leaving them blank for the rest of
        // this visit.
        if (data?.description_pending || data?.cover_pending) {
          stopPolling = pollPending(
            () => api.getTrackDetails(track.id).then((res) => res.data),
            (d) => d?.description_pending || d?.cover_pending,
            (updated) => {
              if (!cancelled) setDetails(updated);
            }
          );
        }
      } catch {
        // swipe-up sheet just shows "no description available" -- fine to ignore
      } finally {
        if (!cancelled) setDetailsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [track?.id]);

  // `details.reactions` is a snapshot from the one-time getTrackDetails
  // fetch above, so on its own it goes stale the moment you tap like/dislike
  // -- the count next to it updates instantly (it reads track.likes_count
  // from PlayerContext), but your own avatar in the list below wouldn't
  // move until the track changed and details got refetched. Patching the
  // current user's row into the fetched list here keeps the two in sync
  // without waiting on a round trip.
  const detailsWithMyReaction = useMemo(() => {
    if (!details || !profile?.user_id) return details;
    const others = (details.reactions || []).filter((r) => r.user_id !== profile.user_id);
    if (!myReaction) return { ...details, reactions: others };
    const mine = {
      user_id: profile.user_id,
      first_name: profile.first_name,
      username: profile.username,
      profile_photo: profile.profile_photo,
      sentiment: myReaction,
    };
    return { ...details, reactions: [mine, ...others] };
  }, [details, myReaction, profile]);

  if (!track) {
    return (
      <div className="h-screen flex items-center justify-center text-muted text-sm">Loading track…</div>
    );
  }

  const uploaders = track.uploaders || [];
  const artists = track.artists || [];
  const visibleUploaders = showAllUploaders ? uploaders : uploaders.slice(0, MAX_UPLOADERS_SHOWN);
  const hiddenUploaderCount = uploaders.length - visibleUploaders.length;

  return (
    <div className="min-h-dvh flex flex-col pb-8">
      <div className="sticky top-0 z-20 bg-ink/85 backdrop-blur-md px-6 pt-4 pb-2 flex items-center justify-between">
        <button onClick={() => navigate(-1)} className="w-9 h-9 rounded-full bg-surface flex items-center justify-center tap" aria-label="Close">
          <ChevronDown size={18} className="text-muted" />
        </button>
        <p className="eyebrow">{queue.next_source_label || "Now playing"}</p>
        <button
          onClick={handleDownload}
          disabled={downloading}
          className="w-9 h-9 rounded-full bg-surface flex items-center justify-center tap disabled:opacity-40"
          aria-label="Download"
        >
          {downloading ? (
            <span className="block w-[15px] h-[15px] rounded-full border-2 border-muted/40 border-t-paper animate-spin" />
          ) : (
            <Download size={15} className="text-muted" />
          )}
        </button>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center px-6 mt-2" {...swipe.bind}>
        <div className="w-full max-w-xs">
          <div className="aspect-square w-full max-h-[34vh] mx-auto" style={{ maxWidth: "min(100%, 34vh)" }}>
            <Cover url={details?.cover_url || track.cover_url} size="100%" rounded="rounded-xl2" />
          </div>
        </div>

        <div className="mt-5 sm:mt-8 w-full max-w-xs text-center">
          <h1 className="font-display text-xl sm:text-2xl text-paper leading-tight">{track.title || "Untitled track"}</h1>
          <div className="mt-2 flex items-center justify-center gap-1.5 flex-wrap text-sm text-muted">
            {artists.length ? (
              artists.map((a, i) => (
                <span key={a.id}>
                  <button onClick={() => navigate(`/artist/${a.id}`)} className="text-brand-glow hover:underline">
                    {a.name}
                  </button>
                  {i < artists.length - 1 && ","}
                </span>
              ))
            ) : (
              <span>{track.performer || "Unknown artist"}</span>
            )}
          </div>

          {uploaders.length > 0 && (
            <p className="mt-1 text-xs text-muted flex items-center justify-center gap-1 flex-wrap px-2">
              <User size={11} className="shrink-0" />
              <span>Shared by</span>
              {visibleUploaders.map((u, i) => (
                <span key={u.user_id}>
                  <button onClick={() => navigate(`/user/${u.user_id}`)} className="text-paper hover:underline">
                    {u.first_name || u.username}
                  </button>
                  {i < visibleUploaders.length - 1 && ", "}
                </span>
              ))}
              {hiddenUploaderCount > 0 && (
                <button
                  onClick={() => setShowAllUploaders(true)}
                  className="text-brand-glow hover:underline"
                >
                  +{hiddenUploaderCount} more
                </button>
              )}
            </p>
          )}
        </div>

        <div className="w-full max-w-xs mt-6 sm:mt-8">
          <ReactionWaveform
            progress={progress}
            duration={duration}
            likes={track.likes_count}
            dislikes={track.dislikes_count}
            seed={track.id}
            onSeek={seekTo}
          />
        </div>

        <div className="w-full max-w-xs mt-5 sm:mt-6 flex items-center justify-between">
          <ReactionButton
            active={myReaction === "dislike"}
            onClick={() => {
              hapticImpact("light");
              react("dislike");
            }}
            icon={ThumbsDown}
            count={track.dislikes_count}
            tone="rasp"
          />

          <div className="flex items-center gap-5">
            <button onClick={playPrev} disabled={!queue.prev} className="text-paper disabled:opacity-30 tap" aria-label="Previous">
              <SkipBack size={22} fill="currentColor" />
            </button>
            <button
              onClick={togglePlay}
              className="w-16 h-16 rounded-full bg-brand flex items-center justify-center shadow-glow tap"
              aria-label={isPlaying ? "Pause" : "Play"}
            >
              {isPlaying ? <Pause size={24} fill="white" /> : <Play size={24} fill="white" className="ml-1" />}
            </button>
            <button
              onClick={playNext}
              disabled={!queue.next}
              className="text-paper disabled:opacity-30 tap relative"
              aria-label="Next"
            >
              {queueLoading ? (
                <span className="block w-[22px] h-[22px] rounded-full border-2 border-muted/40 border-t-paper animate-spin" />
              ) : (
                <SkipForward size={22} fill="currentColor" />
              )}
            </button>
          </div>

          <ReactionButton
            active={myReaction === "like"}
            onClick={() => {
              hapticImpact("light");
              react("like");
            }}
            icon={ThumbsUp}
            count={track.likes_count}
            tone="pulse"
          />
        </div>

        {queueLoading ? (
          <p className="mt-2 text-[11px] text-muted">Finding what's next…</p>
        ) : (
          queue.next_is_suggestion && (
            <p className="mt-2 text-[11px] text-muted">Suggested for you</p>
          )
        )}
      </div>

      <TrackDetailsSheet
        open={detailsOpen}
        onOpenChange={setDetailsOpen}
        details={detailsWithMyReaction}
        loading={detailsLoading}
        track={track}
        dragY={swipe.dragY}
        dragging={swipe.dragging}
        bind={swipe.bind}
      />
    </div>
  );
}

function ReactionButton({ active, onClick, icon: Icon, count, tone }) {
  // Tailwind's JIT scanner needs full static class names, so the two tones
  // are spelled out rather than interpolated into a template literal.
  const activeClasses =
    tone === "pulse" ? "bg-pulse/15 border-pulse/40 text-pulse" : "bg-rasp/15 border-rasp/40 text-rasp";
  return (
    <button onClick={onClick} className="flex flex-col items-center gap-1 tap" aria-pressed={active}>
      <span
        className={`w-11 h-11 rounded-full flex items-center justify-center border ${
          active ? activeClasses : "bg-surface border-line/60 text-muted"
        }`}
      >
        <Icon size={18} fill={active ? "currentColor" : "none"} />
      </span>
      <span className="text-[11px] font-mono text-muted">{count}</span>
    </button>
  );
}
