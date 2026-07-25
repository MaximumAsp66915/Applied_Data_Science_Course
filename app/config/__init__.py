import os
from dotenv import load_dotenv
from .base_config import BaseConfig
from .dev_config import DevConfig
from .prod_config import ProdConfig

# Load environment variables from .env
load_dotenv()


def get_config():
    """Return the correct config class based on ENVIRONMENT."""
    env = os.getenv("ENVIRONMENT", "dev").lower()

    if env == "prod":
        return ProdConfig()
    elif env == "dev":
        return DevConfig()
    else:
        print(f"⚠️ Unknown ENVIRONMENT '{env}', defaulting to BaseConfig.")
        return BaseConfig()
