import { createContext, useContext, useEffect, useRef, useState, useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { whenIdle } from "../lib/idle";

const PlayerContext = createContext(null);

// How many upcoming tracks' audio we keep warm at once. Prefetching further
// than "the very next one" starts costing real bandwidth for something that
// might never get played, so this stays small on purpose.
const PREFETCH_AUDIO_POOL_SIZE = 2;

// Spotify-style Previous-button behavior: within the first few seconds of a
// track, Prev walks back to the actual previous track; past that point, Prev
// just restarts the current track from 0 instead of moving anywhere. Without
// this, a stray "back" tap seconds before a song naturally would have ended
// throws away most of what was just heard rather than replaying it.
const BACK_BUTTON_RESTART_THRESHOLD_SECONDS = 5;

function createAudioFor(trackData) {
  const el = new Audio();
  el.preload = "auto";
  el.src = api.streamUrl(trackData.id);
  // Tags the element with the track it belongs to so playTrack can tell
  // "is this already the track I want" apart from "this is some other
  // leftover element" without a second lookup structure.
  el.dataset.trackId = String(trackData.id);
  return el;
}

export function PlayerProvider({ children }) {
  // The <audio> element actually wired up to play/pause/seek right now.
  // Kept as both a ref (for synchronous reads inside callbacks that might
  // fire back-to-back before React re-renders, e.g. a fast double-tap on
  // "next") and state (so the listener-attaching effect below re-runs
  // whenever we swap to a different element).
  const audioElRef = useRef(null);
  if (!audioElRef.current) audioElRef.current = new Audio();
  const [audioEl, setAudioEl] = useState(() => audioElRef.current);

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

  // Synchronous mirrors of `track`/`myReaction`, read inside playTrack right
  // as a new track takes over -- by then setTrack/setMyReaction have already
  // been called for the new track, so the state values themselves would be
  // the *new* track, not the one that just finished. These are the only
  // reliable way to know what was playing a moment ago.
  const trackRef = useRef(null);
  const myReactionRef = useRef(null);
  useEffect(() => { trackRef.current = track; }, [track]);
  useEffect(() => { myReactionRef.current = myReaction; }, [myReaction]);

  // Set right before a track transition to say *why* the previous track
  // stopped: "completed" if it played out naturally, "skipped" if the user
  // jumped away (Next, or Prev before the restart-vs-back threshold below).
  // playTrack reads and clears this once, folding it into the implicit
  // like/dislike hint sent to the suggestion engine (see api.getTrackQueue)
  // -- purely behavioral, never saved anywhere, and only ever used as a
  // fallback when the track had no explicit reaction of its own.
  const pendingOutcomeRef = useRef(null);

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
    if (audioElRef.current?.dataset.trackId === String(trackData.id)) return; // already playing

    whenIdle(() => {
      // Could've already become the active track (or gotten prefetched by
      // an overlapping call) while this was waiting for an idle slot.
      if (pool.has(trackData.id)) return;
      if (audioElRef.current?.dataset.trackId === String(trackData.id)) return;
      const el = createAudioFor(trackData);
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

    // Snapshot whatever was playing right up until now, before it gets
    // overwritten below -- this is the track/outcome the implicit
    // like/dislike hint (if any) is actually about.
    const previousTrackId = trackRef.current?.id ?? null;
    const previousHadExplicitReaction = myReactionRef.current != null;
    const implicitOutcome = pendingOutcomeRef.current;
    pendingOutcomeRef.current = null;

    setTrack(trackData);
    setMyReaction(trackData.my_reaction ?? null);

    const pool = prefetchPoolRef.current;
    const prevAudio = audioElRef.current;
    const trackIdStr = String(trackData.id);

    // Prefer whatever's already warming up in the background pool over
    // starting a fresh request on the old element -- that hand-off is the
    // whole point of prefetching. Falls back to reusing the current
    // element (replaying the same track) or, failing that, a brand new
    // one (cold start / deep link where nothing was prefetched yet).
    let nextAudio;
    if (pool.has(trackData.id)) {
      nextAudio = pool.get(trackData.id);
      pool.delete(trackData.id);
    } else if (prevAudio.dataset.trackId === trackIdStr) {
      nextAudio = prevAudio;
    } else {
      nextAudio = createAudioFor(trackData);
    }

    if (prevAudio !== nextAudio) {
      prevAudio.pause();
    }

    // Update the ref synchronously (not just via setState) so a second
    // playTrack call fired in the same tick -- e.g. a rapid double-tap on
    // skip -- sees the correct "current" element instead of a stale one.
    audioElRef.current = nextAudio;
    setAudioEl(nextAudio);

    setProgress(0);
    setDuration(nextAudio.duration || 0);
    nextAudio.currentTime = 0;
    nextAudio.play().catch(() => {});

    if (locationRef.current.pathname.startsWith("/song/")) {
      navigate(`/song/${trackData.id}`, { replace: true });
    }

    // Clear the old queue right away rather than leaving the previous
    // track's prev/next sitting there -- that stale pair is what let a
    // fast double-click on Next/Prev act on the wrong neighbor.
    setQueue({ prev: null, next: null, next_is_suggestion: false });
    setQueueLoading(true);

    try {
      const { data } = await api.getTrackQueue(trackData.id, context, {
        lastTrackId: previousTrackId,
        // Explicit like/dislike is already a stronger, saved signal -- the
        // implicit hint only fills the gap for a neutral/no-reaction track.
        lastOutcome: previousHadExplicitReaction ? null : implicitOutcome,
      });
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
    const audio = audioElRef.current;
    if (audio.paused) {
      audio.play().catch(() => {});
    } else {
      audio.pause();
    }
  }, []);

  const seekTo = useCallback((seconds) => {
    audioElRef.current.currentTime = seconds;
    setProgress(seconds);
  }, []);

  // `outcome` says why the *current* track is being left: "completed" when
  // the audio element's own 'ended' event fires this (see onEnd below),
  // "skipped" for every other case -- i.e. the user actually pressed Next.
  const playNext = useCallback((outcome = "skipped") => {
    if (!queue.next) return;
    pendingOutcomeRef.current = outcome;
    playTrack(queue.next, "queue");
  }, [queue, playTrack]);

  const playPrev = useCallback(() => {
    const audio = audioElRef.current;
    // Spotify-style threshold: past the first few seconds, Prev restarts
    // the current track instead of actually moving to the previous one.
    if (audio && audio.currentTime >= BACK_BUTTON_RESTART_THRESHOLD_SECONDS) {
      audio.currentTime = 0;
      setProgress(0);
      audio.play().catch(() => {});
      return;
    }
    if (queue.prev) playTrack(queue.prev, "queue");
  }, [queue, playTrack]);

  // Listeners follow whichever element is actually "current" -- re-attached
  // every time playTrack() swaps in a different (pre-warmed) element rather
  // than staying bound to one fixed <audio> for the whole session.
  useEffect(() => {
    const audio = audioEl;
    const onTime = () => setProgress(audio.currentTime);
    const onLoaded = () => setDuration(audio.duration || 0);
    const onEnd = () => playNext("completed");
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);
    audio.addEventListener("timeupdate", onTime);
    audio.addEventListener("loadedmetadata", onLoaded);
    audio.addEventListener("ended", onEnd);
    audio.addEventListener("play", onPlay);
    audio.addEventListener("pause", onPause);
    // A prefetched/pooled element may have already finished loading
    // metadata (or, in principle, already be playing) before it was
    // promoted to "current", in which case the events above already fired
    // and we'd otherwise miss the duration / play state.
    if (audio.duration) setDuration(audio.duration);
    setIsPlaying(!audio.paused);
    return () => {
      audio.removeEventListener("timeupdate", onTime);
      audio.removeEventListener("loadedmetadata", onLoaded);
      audio.removeEventListener("ended", onEnd);
      audio.removeEventListener("play", onPlay);
      audio.removeEventListener("pause", onPause);
    };
  }, [audioEl, playNext]);

  const react = useCallback(
    async (reaction) => {
      if (!track) return;
      const prevReaction = myReaction;
      const next = myReaction === reaction ? null : reaction; // toggling clears it
      setMyReaction(next);
      setTrack((t) => {
        if (!t) return t;
        const likes = t.likes_count + (next === "like" ? 1 : 0) - (prevReaction === "like" ? 1 : 0);
        const dislikes = t.dislikes_count + (next === "dislike" ? 1 : 0) - (prevReaction === "dislike" ? 1 : 0);
        return { ...t, likes_count: likes, dislikes_count: dislikes };
      });
      try {
        await api.reactToTrack(track.id, next);
      } catch {
        // The save actually failed -- put the UI back the way it was
        // rather than showing a reaction that was never persisted.
        setMyReaction(prevReaction);
        setTrack((t) => {
          if (!t) return t;
          const likes = t.likes_count + (prevReaction === "like" ? 1 : 0) - (next === "like" ? 1 : 0);
          const dislikes = t.dislikes_count + (prevReaction === "dislike" ? 1 : 0) - (next === "dislike" ? 1 : 0);
          return { ...t, likes_count: likes, dislikes_count: dislikes };
        });
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
