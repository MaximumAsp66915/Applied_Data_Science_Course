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
    # "owner/repo" on GitHub, e.g. "your-org/sut-music". Powers both the
    # "Contributors" menu (pulled live from GitHub's API -- never
    # hand-maintained, so it can't go stale) and the repo link on the
    # "About" page. Leave empty and both degrade gracefully with a note
    # instead of erroring.
    github_repo: str = "https://github.com/MaximumAsp66915/Applied_Data_Science_Course/tree/project"

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
    def github_url(self) -> str:
        return f"https://github.com/{self.github_repo}" if self.github_repo else ""


settings = SupportBotSettings()
