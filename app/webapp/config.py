from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    bot_token: str = ""
    suggestion_engine_url: str = ""
    cors_origins: str = "http://localhost:5173"

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