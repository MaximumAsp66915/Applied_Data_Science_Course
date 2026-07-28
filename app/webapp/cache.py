"""
Central place for the webapp's read-through caches.

Everything in here uses the AutoExpiringDict helper from
utils/schedule/dict_helper.py (already used by the model layer for
per-object parameter caching) -- this module is for the *list-shaped*,
"almost never changes within an hour" queries that the model layer's
per-object cache doesn't help with: home feed, leaderboards, and the
Last.fm lookups.

Why a real TTL cache instead of "cache forever + invalidate on write":
top artists / latest songs / leaderboards are read constantly (every
Home load, every Ranks load) but only actually reorder themselves over
minutes-to-hours of accumulated likes -- so a short-lived cache cuts
the DB hit rate on the hottest endpoints in the app to ~1 query per TTL
window instead of 1 per request, without ever risking stale data for
longer than the TTL.
"""

from utils.schedule.dict_helper import AutoExpiringDict

# Home feed / leaderboards / "top X" lists -- these are read on nearly every
# page load but backed by data that (per the product ask) "would certainly
# not change in one hour and might not even change in a day". 1 hour TTL,
# small key space (a handful of (kind, limit) combinations), so max_keys is
# generous but purely defensive.
top_lists_cache = AutoExpiringDict(ttl_seconds=3600, cleanup_interval=300, max_keys=512)

# Last.fm responses (artist/track info, related artists). Rate-limited to
# 5 req/s upstream (see webapp/lastfm.py) and genre/bio/cover-art data for a
# given artist or track basically never changes, so this can live far longer
# than the top-lists cache -- 6 hours -- to keep us well under Last.fm's
# limits even under heavy concurrent traffic.
lastfm_cache = AutoExpiringDict(ttl_seconds=6 * 3600, cleanup_interval=600, max_keys=20000)

# MusicBrainz artist-name -> MBID lookups (webapp/fanart.py). Rate-limited
# to a hard 1 req/s upstream, and an artist's MBID never changes once
# resolved, so this is cached far longer than anything else here -- 7 days
# -- purely to keep the (already one-time-per-artist, thanks to the
# enrichment queue's lastfm_synced flag) lookup from ever being repeated
# for the same artist within a reasonable span.
mbid_cache = AutoExpiringDict(ttl_seconds=7 * 24 * 3600, cleanup_interval=3600, max_keys=20000)

# fanart.tv artist cover-art lookups (webapp/fanart.py), keyed by artist
# name. Same 6-hour TTL reasoning as lastfm_cache -- cover art for a given
# artist doesn't change on any timescale this app cares about.
fanart_cache = AutoExpiringDict(ttl_seconds=6 * 3600, cleanup_interval=600, max_keys=20000)

# Per-user "already shown as a /suggestions/next pick recently" tracker.
# Neither the external engine's /suggest (a deterministic top-1 pick) nor
# our own reacted-tracks exclude list know anything about a track the user
# was just shown but hasn't reacted to -- so without this, hitting "try
# another", or simply closing and reopening the app, returns the exact same
# pick every time (nothing about the request changes). Also doubles as the
# general "don't repeat a track the *suggestion system* already surfaced
# this session" set for the player's own next-track logic (see
# repository._get_next_for_active_program) -- an artist/related-artist
# cascade or an engine reseed both add their picks here too, on top of the
# reacted-tracks/recent-history excludes those call sites already have.
# 24 hours is the product's definition of "session" for this: long enough
# that nothing already surfaced comes back around within the same sitting
# (even one that spans a full day), while still naturally letting a track
# come back into rotation eventually rather than excluding it forever.
# max_keys is generous since this is one small list per active user, not
# per-request data.
recently_suggested_cache = AutoExpiringDict(ttl_seconds=24 * 3600, cleanup_interval=1800, max_keys=20000)

# Per-user "which listening program is currently active" tracker --
# whichever of artist/related-artist cascade, a profile's shared/liked
# tracks in order, the latest-tracks feed, top tracks, or the suggestion
# engine is driving what plays next (see repository._get_next_for_active_program
# and PlayerContext.jsx/api.getTrackQueue's `context`). Set fresh whenever
# the user starts listening from a specific origin (an artist page, a
# profile's track list, etc.) and read back on every subsequent Prev/Next
# within that same sitting so the *same* program keeps driving without the
# frontend needing to keep re-stating it. Same 24h session window as
# recently_suggested_cache, for the same reason.
playback_mode_cache = AutoExpiringDict(ttl_seconds=24 * 3600, cleanup_interval=1800, max_keys=20000)

# Per-user "artists liked in this session" tracker. Product intent: liking
# an artist is a fresh, deliberate signal that should immediately reopen
# that artist's catalog to suggestions -- even for a track sitting in the
# user's last-100 listening history from days ago (see
# repository.get_recent_history_exclude_ids, which takes this set as the
# "don't exclude these artists' history tracks" list). It's intentionally
# session-scoped (same 30-minute TTL as recently_suggested_cache) rather
# than "ever liked" -- get_liked_artist_ids already covers all-time likes
# for the engine's personalization signal; this is specifically the
# short-lived "just happened" signal the exclude-list carve-out cares
# about. set_reaction adds an artist here on a fresh like, and removes it
# again if the user changes their mind (dislikes or clears the reaction)
# before the window lapses.
recently_liked_artists_cache = AutoExpiringDict(ttl_seconds=1800, cleanup_interval=300, max_keys=20000)
