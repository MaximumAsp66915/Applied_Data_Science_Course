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
        'sut_music_chat_id': os.getenv('SUT_MUSIC_CHAT_ID')
    }
