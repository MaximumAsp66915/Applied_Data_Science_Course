from .base_config import BaseConfig


class DevConfig(BaseConfig):
    """Development environment."""
    DEBUG = True
    LOG_LEVEL = "DEBUG"
    API_KEY = "dev-key"
