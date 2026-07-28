import axios from "axios";
import { getInitData } from "./telegram";

// Base URL of the FastAPI backend (see /backend). Set VITE_API_URL at build
// time, e.g. VITE_API_URL=https://api.sutmusic.app/api
const BASE_URL = import.meta.env.VITE_API_URL || "/api";

export const client = axios.create({ baseURL: BASE_URL, timeout: 15000 });

client.interceptors.request.use((config) => {
  const initData = getInitData();
  if (initData) config.headers["X-Telegram-Init-Data"] = initData;
  return config;
});

// ---- Every backend call the frontend needs, in one place -------------------
// Each function is documented with the endpoint it hits; see /backend and
// API_REFERENCE.md for the full contract (params, response shape, tables).

export const api = {
  // Auth / session
  login: () => client.post("/auth/telegram"), // -> { user, is_new }

  // Home feed
  getFeed: () =>
    client.get("/home/feed"), // -> { latest_tracks, latest_artists, top_artists }

  // Search (songs / artists / users, tabbed)
  search: (q, scope = "all", { limit = 20, offset = 0 } = {}) =>
    client.get("/search", { params: { q, scope, limit, offset } }),

  // Tracks / player
  getTrack: (trackId) => client.get(`/tracks/${trackId}`),
  getTrackQueue: (trackId, context = "home", { lastTrackId, lastOutcome } = {}) => {
    // -> { prev, next, next_is_suggestion }
    // lastTrackId/lastOutcome ("completed" | "skipped") are an optional,
    // purely behavioral hint about whatever was playing right before this
    // -- see PlayerContext.jsx. Omitted entirely (not sent as null/undefined)
    // when there's nothing to report, e.g. the very first track of a session.
    const params = { context };
    if (lastTrackId != null) params.last_track_id = lastTrackId;
    if (lastOutcome != null) params.last_outcome = lastOutcome;
    return client.get(`/tracks/${trackId}/queue`, { params });
  },
  getTrackDetails: (trackId) => client.get(`/tracks/${trackId}/details`), // -> swipe-up sheet data
  streamUrl: (trackId) => `${BASE_URL}/tracks/${trackId}/stream`,
  reactToTrack: (trackId, reaction) =>
    client.post(`/tracks/${trackId}/reactions`, { reaction }), // reaction: "like" | "dislike" | null
  downloadTrack: (trackId) =>
    client.post(`/tracks/${trackId}/download`), // -> { sent: true } | { sent: false, reason: "not_started" }

  // Artists
  getArtist: (artistId) => client.get(`/artists/${artistId}`),
  getArtistTracks: (artistId, { limit = 20, offset = 0 } = {}) =>
    client.get(`/artists/${artistId}/tracks`, { params: { limit, offset } }),

  // Users / profile
  getUser: (userId) => client.get(`/users/${userId}`),
  getMe: () => client.get("/users/me"),
  setVisibility: (isPublic) => client.patch("/users/me/visibility", { is_public: isPublic }),
  getUserTracks: (userId, { limit = 20, offset = 0 } = {}) =>
    client.get(`/users/${userId}/tracks`, { params: { limit, offset } }),
  getUserLikedTracks: (userId, { limit = 20, offset = 0 } = {}) =>
    client.get(`/users/${userId}/liked-tracks`, { params: { limit, offset } }),
  getUserStats: (userId) => client.get(`/users/${userId}/stats`), // scores, ranks, trophies
  getUserRelations: (userId) => client.get(`/users/${userId}/relations`), // correlation, top given/received

  // Ranks / leaderboards
  getRanks: (scope = "users") => client.get("/ranks", { params: { scope } }), // scope: users | tracks | artists

  // Suggestion engine (built by the other team; this is the integration point)
  getSuggestion: () => client.get("/suggestions/next"),
};
