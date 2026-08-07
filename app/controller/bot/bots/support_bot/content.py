"""
Content shown by the Terms & Privacy / Contributors / About menu entries.

Terms & Privacy and About are static (edit the strings below whenever the
product actually changes -- that's simpler and more honest than trying to
infer legal text from code at runtime). What *is* auto-derived here is
grounded in how the rest of this project actually works, read straight out
of model/, db/ and webapp/:

    * Telegram identity fields (user_id, username, first/last name, profile
      photo) are kept as JSONB *history* per model/objects/user.py &
      model/objects/chat.py, and chat_id -> internal user_id is resolved
      through the Chat model -- see the README's "one important discovery"
      section and webapp/repository.py::upsert_user_from_telegram.
    * Track/cover audio is never re-hosted: it stays on Telegram's own
      servers as file_ids, proxied on demand by webapp/media.py.
    * Reactions (likes/dislikes/emoji) on tracks, artists, albums and
      playlists, plus album comments, are what listening/engagement
      features (Ranks, Suggestions) are built from -- see
      db/internal_db/SUTMusic/*_reaction_internal_db.py.
    * Track/artist metadata (titles, performer names -- never anything
      about the user) is sent to Last.fm and fanart.tv for enrichment
      (genres, bios, cover art) -- see webapp/lastfm.py, webapp/fanart.py.

Contributors is fully dynamic: it calls the GitHub API for whatever repo is
configured (SUPPORT_BOT settings' `github_repo`), so it can never go stale
the way a hand-maintained CONTRIBUTORS.md would.
"""

import logging
import time
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

ABOUT_TEXT = (
    "<b>About this bot</b>\n\n"
    "This is the companion chat bot for <b>SUT Music</b> -- a Telegram Mini "
    "App for discovering, sharing and reacting to music, built on top of a "
    "shared bot + Mini App + recommendation-engine stack.\n\n"
    "From here, without ever opening the Mini App, you can:\n"
    "• Search for a track or an artist -- just type a name and send it\n"
    "• Jump straight into the full Mini App\n"
    "• Report a bug or anything wrong with the app\n"
    "• Read the Terms &amp; Privacy notice\n"
    "• See who has contributed to the project\n\n"
    "It's built with <a href=\"https://github.com/aiogram/aiogram\">aiogram</a> "
    "and talks to the same backend the Mini App itself uses, so search "
    "results here always match what you'd see in the app."
)

TERMS_PRIVACY_TEXT = (
    "<b>Terms &amp; Privacy</b>\n\n"
    "<b>What SUT Music is</b>\n"
    "SUT Music is a community music-sharing Mini App and Telegram bot. "
    "Tracks are ingested from Telegram, stored by their Telegram "
    "<code>file_id</code> (never re-uploaded or re-hosted elsewhere), and "
    "shared back out the same way -- through Telegram's own servers.\n\n"
    "<b>What we store about you</b>\n"
    "• Your Telegram user id, username, first/last name and profile photo, "
    "kept as-of-last-seen so your public info stays in sync with Telegram\n"
    "• Tracks you upload, and your reactions (likes/dislikes/emoji) on "
    "tracks, artists, albums and playlists -- this is what powers rankings "
    "and personalised suggestions\n"
    "• Basic app-state bookkeeping needed to make the bot and Mini App work "
    "(e.g. what you're currently doing in the bot)\n\n"
    "<b>What we don't do</b>\n"
    "• We don't sell or share your personal data with third parties\n"
    "• We don't message enrichment services (Last.fm, fanart.tv) with "
    "anything about you -- only track/artist names, to fetch genres, bios "
    "and cover art\n"
    "• We don't re-host your audio files outside of Telegram's own "
    "infrastructure\n\n"
    "<b>Your rights</b>\n"
    "You can ask what data is held about you, or ask for it to be removed, "
    "at any time -- use \"Report a problem\" and describe your request; it "
    "goes straight to the project admin.\n\n"
    "<i>This notice describes current behaviour and may be updated as the "
    "app evolves.</i>"
)

# --- Contributors: pulled live from GitHub, never hand-maintained ---------

_CACHE_TTL_SECONDS = 30 * 60
_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}


async def get_contributors_data() -> dict:
    """Returns everything handlers.py needs to render the Contributors page
    as a photo message:

        {
            "photo_url": str | None,     # GitHub's own repo social-preview image
            "caption": str,                # HTML caption
            "contributors": list[dict],     # [{"login", "url", "contributions"}, ...],
                                              # already in GitHub's own order (most
                                              # contributions first)
            "repo_slug": str,
        }
    """
    repo_slug = settings.repo_slug
    if not repo_slug:
        return {
            "photo_url": None,
            "caption": (
                "<b>Contributors</b>\n\n"
                "The project's GitHub repository isn't configured yet on "
                "this bot (<code>GITHUB_REPO</code> in .env), so "
                "contributors can't be listed here. Ask the admin to set "
                "it -- see \"About this bot\" to reach them."
            ),
            "contributors": [],
            "repo_slug": "",
        }

    # GitHub renders this social-preview card for every public repo (the
    # same image you'd see pasting the repo link into a chat app) -- no
    # auth, no extra API call needed for it.
    photo_url = f"https://github.com/{repo_slug}"

    now = time.time()
    if _cache["data"] is None or (now - _cache["fetched_at"]) > _CACHE_TTL_SECONDS:
        try:
            _cache["data"] = await _fetch_contributors()
            _cache["fetched_at"] = now
        except Exception as exc:  # noqa: BLE001
            logger.warning("GitHub contributors fetch failed: %s", exc)
            if _cache["data"] is None:
                return {
                    "photo_url": photo_url,
                    "caption": (
                        "<b>Contributors</b>\n\n"
                        "Couldn't reach GitHub right now -- please try again "
                        "in a moment."
                    ),
                    "contributors": [],
                    "repo_slug": repo_slug,
                }
            # fall through and show the last good cached list

    raw = _cache["data"] or []
    contributors = [
        {
            "login": c.get("login", "unknown"),
            "url": c.get("html_url", f"https://github.com/{c.get('login', '')}"),
            "contributions": c.get("contributions", 0),
        }
        for c in raw
    ]

    if contributors:
        caption = (
            f"<b>Contributors</b>\n\n"
            f"To <code>{repo_slug}</code> -- tap a name below to open their "
            f"GitHub profile."
        )
    else:
        caption = f"<b>Contributors</b>\n\nNo contributors found for <code>{repo_slug}</code> yet."

    return {"photo_url": photo_url, "caption": caption, "contributors": contributors, "repo_slug": repo_slug}


async def _fetch_contributors() -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{settings.repo_slug}/contributors"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "SUTMusic-support-bot"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params={"per_page": 25, "anon": "0"}, headers=headers)
        resp.raise_for_status()
        return resp.json()
