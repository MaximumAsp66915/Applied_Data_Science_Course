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
