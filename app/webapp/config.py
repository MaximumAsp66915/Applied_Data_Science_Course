from pathlib import Path

from dotenv import dotenv_values
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = ""
    suggestion_engine_url: str = ""
    cors_origins: str = "http://localhost:5173"

    # Base URL of a self-hosted Local Bot API Server
    # (https://github.com/tdlib/telegram-bot-api), used ONLY as a fallback
    # for files that exceed the standard Bot API's 20MB getFile/download
    # limit (see webapp/media.py's TelegramFileTooBigError). A local server
    # run with --local raises that limit to 2000MB. Point this at it, e.g.
    # "http://127.0.0.1:8081" -- same BOT_TOKEN, different base URL, no
    # other code changes needed. Leave empty to skip the fallback entirely
    # (oversized tracks then fail cleanly with a 413, as before).
    telegram_local_api_base: str = ""

    # @BotFather username (no @, no https://t.me/), e.g. "SUT_Music_bot" --
    # used to build the "via ..." deep link in download captions
    # (https://t.me/{bot_username}?startapp=track_{id}), see
    # routers/tracks.py's build_share_caption().
    bot_username: str = ""

    # Last.fm API credentials (webapp/lastfm.py) -- used to enrich artists
    # and tracks with genre tags, bios/descriptions, cover art, and related
    # artists. Get a free key at https://www.last.fm/api/account/create.
    # Leave empty to disable Last.fm enrichment entirely (the app falls back
    # to whatever's already in our own DB).
    lastfm_api_key: str = ""
    lastfm_api_secret: str = ""

    # fanart.tv project API key (webapp/fanart.py) -- used ONLY to fetch
    # artist cover art (via a MusicBrainz name->MBID lookup), since Last.fm's
    # own artist images are frequently missing. Get a free project key at
    # https://fanart.tv/get-an-api-key/. Leave empty to skip fanart.tv
    # entirely -- artist covers then fall back to Last.fm's image list (if
    # any) same as before.
    fanart_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",       # <-- ignore unrelated keys in .env
    )


settings = Settings()

# Path to the same .env file `settings` above loads from -- resolved once,
# read fresh on every get_public_domain() call (see below).
_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def get_public_domain() -> str:
    """Base URL this deployment is currently reachable at (used to build the
    song-page link in download captions -- see routers/tracks.py's
    build_share_caption()), e.g. "https://random-words.trycloudflare.com".

    Deliberately NOT a field on `Settings` above: pydantic-settings reads
    .env exactly once, at import time, and this process is typically already
    running (uvicorn started) by the time deploy/update_domain.sh discovers
    the quick tunnel's URL and writes PUBLIC_DOMAIN into .env a few seconds
    later -- a cached value would sit empty/stale until the next full
    process restart. Since trycloudflare.com URLs are re-issued on every
    restart (there's no static domain for now, see deploy/update_domain.sh),
    this instead re-reads the .env file fresh every time it's called -- a
    cheap disk read, and always current. Once a real static domain is in
    place, just set PUBLIC_DOMAIN once and this still works unchanged.
    """
    value = dotenv_values(_ENV_PATH).get("PUBLIC_DOMAIN") or ""
    return value.strip().rstrip("/")