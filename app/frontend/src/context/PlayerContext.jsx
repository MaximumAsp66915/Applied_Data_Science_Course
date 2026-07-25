import { createContext, useContext, useEffect, useRef, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { whenIdle } from "../lib/idle";

const PlayerContext = createContext(null);

// How many upcoming tracks' audio we keep warm at once. Prefetching further
// than "the very next one" starts costing real bandwidth for something that
// might never get played, so this stays small on purpose.
const PREFETCH_AUDIO_POOL_SIZE = 2;

export function PlayerProvider({ children }) {
  const audioRef = useRef(new Audio());
  const [track, setTrack] = useState(null); // current track object
  const [queue, setQueue] = useState({ prev: null, next: null, next_is_suggestion: false });
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0); // seconds
  const [duration, setDuration] = useState(0);
  const [myReaction, setMyReaction] = useState(null); // "like" | "dislike" | null
  const location = useLocation();
  const navigate = useNavigate();
  const locationRef = useRef(location);
  locationRef.current = location;

  // Hidden <audio> elements quietly buffering the next couple of tracks so
  // hitting "skip" feels instant instead of waiting on a fresh network
  // request -- the same "get the next thing ready before it's asked for"
  // idea the product ask described for song data in general, applied to the
  // audio stream itself. Keyed by track id so the same track never gets
  // fetched twice, and capped/cleaned up so this never turns into an
  // unbounded pile of hidden <audio> elements.
  const prefetchPoolRef = useRef(new Map()); // track_id -> HTMLAudioElement

  const prefetchTrackAudio = useCallback((trackData) => {
    if (!trackData?.id) return;
    const pool = prefetchPoolRef.current;
    if (pool.has(trackData.id)) return;

    whenIdle(() => {
      const el = new Audio();
      el.preload = "auto";
      el.src = api.streamUrl(trackData.id);
      pool.set(trackData.id, el);

      while (pool.size > PREFETCH_AUDIO_POOL_SIZE) {
        const oldestId = pool.keys().next().value;
        const oldest = pool.get(oldestId);
        oldest?.pause();
        if (oldest) oldest.src = "";
        pool.delete(oldestId);
      }
    });
  }, []);

  const [queueLoading, setQueueLoading] = useState(false);
  // Tags each playTrack call so that if the user skips again before a
  // getTrackQueue fetch resolves, the older (now-stale) response gets
  // dropped instead of overwriting the queue for whatever track is
  // actually playing now -- this was the root cause of prev/next getting
  // out of sync when skipping through several tracks quickly.
  const playRequestIdRef = useRef(0);

  const playTrack = useCallback(async (trackData, context = "home") => {
    const requestId = ++playRequestIdRef.current;
    setTrack(trackData);
    setMyReaction(trackData.my_reaction ?? null);
    const audio = audioRef.current;
    audio.src = api.streamUrl(trackData.id);
    audio.play().catch(() => {});
    setIsPlaying(true);

    if (locationRef.current.pathname.startsWith("/song/")) {
      navigate(`/song/${trackData.id}`, { replace: true });
    }

    // Clear the old queue right away rather than leaving the previous
    // track's prev/next sitting there -- that stale pair is what let a
    // fast double-click on Next/Prev act on the wrong neighbor.
    setQueue({ prev: null, next: null, next_is_suggestion: false });
    setQueueLoading(true);

    try {
      const { data } = await api.getTrackQueue(trackData.id, context);
      if (playRequestIdRef.current !== requestId) return; // superseded by a newer skip
      setQueue(data);
      // Warm the audio for whatever's up next (and, lightly, prev) in the
      // background -- see prefetchTrackAudio above.
      if (data.next) prefetchTrackAudio(data.next);
      if (data.prev) prefetchTrackAudio(data.prev);
    } catch {
      if (playRequestIdRef.current !== requestId) return;
      setQueue({ prev: null, next: null, next_is_suggestion: false });
    } finally {
      if (playRequestIdRef.current === requestId) setQueueLoading(false);
    }
  }, [prefetchTrackAudio, navigate]);

  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (audio.paused) {
      audio.play().catch(() => {});
      setIsPlaying(true);
    } else {
      audio.pause();
      setIsPlaying(false);
    }
  }, []);

  const seekTo = useCallback((seconds) => {
    audioRef.current.currentTime = seconds;
    setProgress(seconds);
  }, []);

  const playNext = useCallback(() => {
    if (queue.next) playTrack(queue.next, "queue");
  }, [queue, playTrack]);

  const playPrev = useCallback(() => {
    if (queue.prev) playTrack(queue.prev, "queue");
  }, [queue, playTrack]);

  useEffect(() => {
    const audio = audioRef.current;
    const onTime = () => setProgress(audio.currentTime);
    const onLoaded = () => setDuration(audio.duration || 0);
    const onEnd = () => playNext();
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onLoaded);
    audio.addEventListener("ended", onEnd);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("ended", onEnd);
    };
  }, [playNext]);

  const react = useCallback(
    async (reaction) => {
      if (!track) return;
      const next = myReaction === reaction ? null : reaction; // toggling clears it
      setMyReaction(next);
      setTrack((t) => {
        if (!t) return t;
        const likes = t.likes_count + (next === "like" ? 1 : 0) - (myReaction === "like" ? 1 : 0);
        const dislikes = t.dislikes_count + (next === "dislike" ? 1 : 0) - (myReaction === "dislike" ? 1 : 0);
        return { ...t, likes_count: likes, dislikes_count: dislikes };
      });
      try {
        await api.reactToTrack(track.id, next);
      } catch {
        // optimistic update stands; a toast/retry could go here
      }
    },
    [track, myReaction]
  );

  return (
    <PlayerContext.Provider
      value={{
        track,
        queue,
        queueLoading,
        isPlaying,
        progress,
        duration,
        myReaction,
        playTrack,
        togglePlay,
        seekTo,
        playNext,
        playPrev,
        react,
      }}
    >
      {children}
    </PlayerContext.Provider>
  );
}

export function usePlayer() {
  const ctx = useContext(PlayerContext);
  if (!ctx) throw new Error("usePlayer must be used within PlayerProvider");
  return ctx;
}
