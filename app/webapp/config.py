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

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",       # <-- ignore unrelated keys in .env
    )


settings = Settings()