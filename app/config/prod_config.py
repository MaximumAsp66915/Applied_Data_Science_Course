from .base_config import BaseConfig

class ProdConfig(BaseConfig):
    """Production environment (your Ubuntu server)."""
    DEBUG = False
    LOG_LEVEL = "INFO"
    API_KEY = "prod-key"
