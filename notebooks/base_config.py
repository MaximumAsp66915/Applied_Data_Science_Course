import os


class BaseConfig:
    """Common settings for all environments."""
    DEBUG = False
    LOG_LEVEL = "INFO"
    API_KEY = None
    TIMEZONE = "UTC"

    SESSION_DATA = {'internal_db': {
        'conn_params': {'host': os.getenv("INTERNAL_DB_HOST"),
                        'database': os.getenv("INTERNAL_DB_NAME"),
                        'user': os.getenv("INTERNAL_DB_USER"),
                        'password': os.getenv("INTERNAL_DB_PASSWORD"),
                        'port': os.getenv("INTERNAL_DB_PORT"),
                        'min_size': 5,
                        'max_size': 30},
        'verbose': True,
        'expires_at': 1750227330.057813
    },
        'external_db': {
            'conn_params': {'host': os.getenv("EXTERNAL_DB_HOST"),
                            'database': os.getenv("EXTERNAL_DB_NAME"),
                            'user': os.getenv("EXTERNAL_DB_USER"),
                            'password': os.getenv("EXTERNAL_DB_PASSWORD"),
                            'port': os.getenv("EXTERNAL_DB_PORT"),
                            'min_size': 5,
                            'max_size': 30},
            'verbose': True,
            'expires_at': 1750227330.057813}
    }

    TELEGRAM_SUTMusic = {
        'api_id': os.getenv('API_ID'),
        'api_hash': os.getenv('API_HASH'),
        'storage_chat_id': os.getenv('STORAGE_CHAT_ID'),
        'sut_music_chat_id': os.getenv('SUT_MUSIC_CHAT_ID'),
        # Same bot account/token the webapp already uses (see webapp/config.py's
        # `bot_token`, BOT_TOKEN env var) -- needed by SUT_Music_bot.py to
        # resolve a real Bot-API file_id at ingestion time instead of storing
        # the Telethon userbot's internal document id (see
        # SUT_Music_bot._resolve_bot_api_media below, and webapp/media.py's
        # docstring, which documents this exact bug and the reactive
        # self-heal that this scraper-side fix makes unnecessary going
        # forward). Leave unset and ingestion falls back to the old
        # behavior -- nothing breaks, it just keeps relying on that
        # self-heal instead of getting a working file_id from the start.
        'bot_token': os.getenv('BOT_TOKEN'),
    }
