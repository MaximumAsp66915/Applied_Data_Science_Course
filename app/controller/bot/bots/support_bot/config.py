"""
Configuration for the support bot. Kept separate from ``config/base_config.py``
and ``webapp/config.py`` on purpose: this process never opens a database
connection (see ``api_client.py``), so it has no business importing the DB
layer or the webapp's pydantic settings -- it just needs a token, an admin
chat id, and the webapp's own base URL.

All values are read from the project's existing ``app/.env`` (same file
``main.py`` and ``webapp/main.py`` already load via ``load_dotenv()``), so
one .env keeps configuring the whole stack.
"""

from pathlib import Path

import re

from pydantic_settings import BaseSettings, SettingsConfigDict

# .../app  (this file lives at app/controller/bot/bots/support_bot/config.py)
APP_ROOT = Path(__file__).resolve().parents[4]


class SupportBotSettings(BaseSettings):
    # --- Bot API token ---------------------------------------------------
    # Defaults to the same BOT_TOKEN the webapp already uses (see
    # webapp/config.py's `bot_token`) -- that's the @SUTMusic_Bot account
    # the Mini App's own deep links (https://t.me/SUTMusic_Bot?startapp)
    # point at, so this is the natural bot to also answer chat messages.
    # Set SUPPORT_BOT_TOKEN instead only if a *different* bot account
    # should own the chat-command surface.
    bot_token: str = ""
    support_bot_token: str = ""

    # --- Reports -----------------------------------------------------------
    # chat_id reports (and anything sent through the "Report a problem"
    # menu) get forwarded to. Defaults to the project admin.
    admin_chat_id: int = 8651094051

    # --- Search --------------------------------------------------------
    # Base URL of the running FastAPI webapp (webapp/main.py). Local by
    # default, since deploy/start.sh always runs the bot + webapp on the
    # same host. Only the public, unauthenticated GET /api/search endpoint
    # is used -- see api_client.py.
    webapp_api_base_url: str = "http://localhost:8000"

    # Base URL of the same self-hosted Local Bot API Server the webapp uses
    # for oversized files (see webapp/config.py's `telegram_local_api_base`,
    # e.g. "http://127.0.0.1:8081"). IMPORTANT: once a Local Bot API Server
    # is in play for a bot token, every consumer of that token -- webapp AND
    # this bot -- has to go through it, not a mix of local + the default
    # https://api.telegram.org. Telegram enforces a single active
    # getUpdates listener *per bot token*, regardless of which HTTP front
    # door (cloud or local) the request came through, since the local
    # server ultimately proxies to the same backend. Leaving this bot on
    # the cloud default while something else talks to the token through the
    # local server is exactly what produces "TelegramConflictError:
    # terminated by other getUpdates request" and silent, unresponsive
    # commands like /start. Set this to the same value as the webapp's
    # TELEGRAM_LOCAL_API_BASE and this bot will poll through the local
    # server too, leaving exactly one consumer. Leave both empty to keep
    # using the cloud API as before.
    telegram_local_api_base: str = ""

    # --- Mini App deep links ------------------------------------------------
    # https://t.me/{bot_username}?startapp -- the exact link the user asked
    # for, used for the "Open Mini App" button.
    mini_app_deeplink: str = "https://t.me/SUTMusic_Bot?startapp"
    # Bot username (no @), used to build per-result deep links, e.g.
    # https://t.me/{bot_username}?startapp=track_{id} -- the same pattern
    # webapp/routers/tracks.py's build_share_caption() already uses, and the
    # only start_param format the frontend currently understands
    # (frontend/src/App.jsx's START_PARAM_TRACK). Artists don't have a
    # start_param route yet, so artist results link to the app generically.
    bot_username: str = "SUTMusic_Bot"

    # --- Contributors / About -------------------------------------------
    # "owner/repo" on GitHub, e.g. "your-org/sut-music" -- a full URL like
    # "https://github.com/owner/repo" or "https://github.com/owner/repo/tree/branch"
    # also works, it's normalized below. Powers both the "Contributors" menu
    # (pulled live from GitHub's API -- never hand-maintained, so it can't
    # go stale) and the repo link on the "About" page. Leave empty and both
    # degrade gracefully with a note instead of erroring.
    github_repo: str = ""

    # Optional: a GitHub personal access token (no special scopes needed --
    # public read access is enough). Unauthenticated GitHub API calls are
    # capped at 60/hour per IP, which one busy chat could burn through;
    # setting this raises that to 5000/hour. Leave empty to call
    # anonymously.
    github_token: str = ""

    model_config = SettingsConfigDict(
        env_file=str(APP_ROOT / ".env"),
        extra="ignore",
    )

    @property
    def token(self) -> str:
        return self.support_bot_token or self.bot_token

    @property
    def repo_slug(self) -> str:
        """`github_repo` normalized down to "owner/repo", however it was
        entered -- a bare slug, a full https://github.com/owner/repo URL,
        or one with a /tree/<branch> (or trailing slash) tacked on. The
        GitHub contributors API only ever wants "owner/repo".
        """
        value = self.github_repo.strip()
        if not value:
            return ""
        value = re.sub(r"^https?://github\.com/", "", value, flags=re.IGNORECASE)
        value = value.strip("/")
        parts = value.split("/")
        if len(parts) < 2:
            return ""
        return f"{parts[0]}/{parts[1]}"

    @property
    def github_url(self) -> str:
        return f"https://github.com/{self.repo_slug}" if self.repo_slug else ""


settings = SupportBotSettings()
