from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .config import settings


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎧 Open Mini App", url=settings.mini_app_deeplink)
    kb.button(text="🔎 Search", callback_data="menu:search")
    kb.button(text="🚩 Report a problem", callback_data="menu:report")
    kb.button(text="📄 Terms & Privacy", callback_data="menu:terms")
    kb.button(text="👥 Contributors", callback_data="menu:contributors")
    kb.button(text="ℹ️ About this bot", callback_data="menu:about")
    kb.adjust(1, 1, 2, 2)
    return kb.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Back to menu", callback_data="menu:main")
    return kb.as_markup()


def cancel_report_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✖️ Cancel", callback_data="report:cancel")
    return kb.as_markup()


def track_deeplink(track_id: int) -> str:
    # https://t.me/{bot}?startapp=track_{id} -- the only start_param route
    # the Mini App frontend currently understands (App.jsx's
    # START_PARAM_TRACK), same pattern webapp/routers/tracks.py already
    # uses for share captions.
    return f"https://t.me/{settings.bot_username}?startapp=track_{track_id}"


def search_results_kb(tracks: list[dict]) -> InlineKeyboardMarkup:
    """One 'Open in App' button per track result, plus a generic Mini App
    button and a back-to-menu button. Artists don't get per-item buttons --
    there's no start_param route for them in the frontend yet, so they're
    listed in the text only (see handlers.py::_format_search_results).
    """
    kb = InlineKeyboardBuilder()
    for t in tracks:
        title = t.get("title") or "Untitled"
        label = title if len(title) <= 40 else title[:37] + "…"
        kb.row(InlineKeyboardButton(text=f"▶ {label}", url=track_deeplink(t["id"])))
    kb.row(InlineKeyboardButton(text="🎧 Open Mini App", url=settings.mini_app_deeplink))
    kb.row(InlineKeyboardButton(text="⬅️ Back to menu", callback_data="menu:main"))
    return kb.as_markup()


MAX_CONTRIBUTOR_BUTTONS = 15


def contributors_kb(contributors: list[dict], repo_slug: str) -> InlineKeyboardMarkup:
    """One button per contributor (GitHub already returns them ordered by
    contribution count, most first -- see content.py::get_contributors_data),
    each linking straight to that person's GitHub profile, followed by a
    button to the repo's full contributors graph and a back-to-menu button.
    """
    kb = InlineKeyboardBuilder()
    for i, c in enumerate(contributors[:MAX_CONTRIBUTOR_BUTTONS], start=1):
        label = f"{i}. {c['login']} ({c['contributions']})"
        kb.row(InlineKeyboardButton(text=label, url=c["url"]))
    if repo_slug:
        kb.row(
            InlineKeyboardButton(
                text="📜 Full contributors list",
                url=f"https://github.com/{repo_slug}/graphs/contributors",
            )
        )
    kb.row(InlineKeyboardButton(text="⬅️ Back to menu", callback_data="menu:main"))
    return kb.as_markup()
