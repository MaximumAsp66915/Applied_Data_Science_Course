"""
All chat handlers for the support bot, in one router.

Behaviour summary (matches the product ask):
    * /start, /menu, "menu:main"  -> main menu (Open Mini App / Search /
      Report / Terms & Privacy / Contributors / About)
    * Any plain text sent outside of an active flow (e.g. not mid-report) is
      treated as a song/artist search query by default -- never a user
      search.
    * "Report a problem" starts a short guided flow; whatever the person
      sends next (text, photo, voice, ...) is relayed verbatim to the admin
      chat, with the reporter's identity attached.
    * Terms & Privacy / Contributors / About are read-only info pages.
"""

import html
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from . import content
from .api_client import SearchUnavailable, search_tracks_and_artists
from .config import settings
from .keyboards import back_to_menu_kb, cancel_report_kb, contributors_kb, main_menu_kb, search_results_kb
from .states import ReportStates

logger = logging.getLogger(__name__)
router = Router(name="support_bot")

WELCOME_TEXT = (
    "<b>Welcome to SUT Music 🎵</b>\n\n"
    "Send me the name of a song or an artist and I'll search it for you -- "
    "or use the menu below."
)

MAX_RESULTS_PER_KIND = 6


# ---------------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.message(Command("menu", "help"))
async def cmd_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("What would you like to do?", reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("What would you like to do?", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "menu:search")
async def cb_search_hint(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Just type a song title or an artist name and send it -- no command "
        "needed.",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Static / semi-dynamic info pages
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "menu:terms")
async def cb_terms(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        content.TERMS_PRIVACY_TEXT, reply_markup=back_to_menu_kb(), disable_web_page_preview=True
    )
    await callback.answer()


@router.callback_query(F.data == "menu:about")
async def cb_about(callback: CallbackQuery) -> None:
    text = content.ABOUT_TEXT
    if settings.github_url:
        text += f"\n\nSource code: {settings.github_url}"
    await callback.message.edit_text(text, reply_markup=back_to_menu_kb(), disable_web_page_preview=True)
    await callback.answer()


@router.callback_query(F.data == "menu:contributors")
async def cb_contributors(callback: CallbackQuery) -> None:
    await callback.answer()
    data = await content.get_contributors_data()
    kb = contributors_kb(data["contributors"], data["repo_slug"])

    # Contributors gets its own photo message (the repo's GitHub
    # social-preview image above the caption) rather than an edit_text,
    # since a text message can't be turned into a photo message in place.
    # Sent first, old menu message only removed once this succeeds so we
    # never lose the menu if the photo fetch fails.
    sent = None
    if data["photo_url"]:
        try:
            sent = await callback.message.answer_photo(
                photo=data["photo_url"],
                caption=data["caption"],
                reply_markup=kb,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to send contributors preview photo: %s", exc)

    if sent is None:
        sent = await callback.message.answer(
            data["caption"], reply_markup=kb, disable_web_page_preview=True
        )

    try:
        await callback.message.delete()
    except Exception:  # noqa: BLE001 - message may already be gone/too old, harmless
        pass


# ---------------------------------------------------------------------------
# Report flow
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "menu:report")
async def cb_report_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ReportStates.waiting_for_report)
    await callback.message.edit_text(
        "<b>Report a problem</b>\n\n"
        "Describe the bug, or whatever's wrong -- a screenshot or voice "
        "note works too. Send it in your next message and I'll pass it "
        "straight to the admin.",
        reply_markup=cancel_report_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "report:cancel", StateFilter(ReportStates.waiting_for_report))
async def cb_report_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Report cancelled.", reply_markup=main_menu_kb())
    await callback.answer()


@router.message(Command("cancel"), StateFilter(ReportStates.waiting_for_report))
async def cmd_cancel_report(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Report cancelled.", reply_markup=main_menu_kb())


@router.message(StateFilter(ReportStates.waiting_for_report))
async def receive_report(message: Message, state: FSMContext) -> None:
    await state.clear()

    user = message.from_user
    display_name = " ".join(filter(None, [user.first_name, user.last_name])) or "Unknown"
    username = f"@{user.username}" if user.username else "no username"
    reported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    reference = f"RPT-{message.message_id}-{user.id}"

    header = (
        "🚩 <b>New report</b>\n"
        f"From: {html.escape(display_name)} ({username}, id <code>{user.id}</code>)\n"
        f"When: {reported_at}\n"
        f"Ref: <code>{reference}</code>"
    )

    try:
        await message.bot.send_message(settings.admin_chat_id, header)
        await message.forward(settings.admin_chat_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to forward report to admin: %s", exc)
        await message.answer(
            "Sorry, something went wrong sending that report. Please try "
            "again in a bit.",
            reply_markup=main_menu_kb(),
        )
        return

    await message.answer(
        f"Thanks, that's been sent to the admin. Reference: <code>{reference}</code>",
        reply_markup=main_menu_kb(),
    )


# ---------------------------------------------------------------------------
# Default: free text -> song/artist search (never users)
# ---------------------------------------------------------------------------

@router.message(StateFilter(None), F.text, ~F.text.startswith("/"))
async def default_search(message: Message) -> None:
    query = message.text.strip()
    if not query:
        return

    try:
        results = await search_tracks_and_artists(query, limit=MAX_RESULTS_PER_KIND)
    except SearchUnavailable:
        await message.answer(
            "Search is temporarily unavailable -- please try again in a "
            "moment, or use the Mini App directly.",
            reply_markup=main_menu_kb(),
        )
        return

    tracks = results["tracks"]
    artists = results["artists"]

    if not tracks and not artists:
        await message.answer(
            f"No songs or artists found for “{html.escape(query)}”.",
            reply_markup=main_menu_kb(),
        )
        return

    await message.answer(
        _format_search_results(query, tracks, artists),
        reply_markup=search_results_kb(tracks),
        disable_web_page_preview=True,
    )


def _format_search_results(query: str, tracks: list[dict], artists: list[dict]) -> str:
    lines = [f"Results for “{html.escape(query)}”:\n"]

    if tracks:
        lines.append("<b>🎵 Tracks</b>")
        for t in tracks:
            title = html.escape(t.get("title") or "Untitled")
            performer = html.escape(t.get("performer") or "")
            artist_names = ", ".join(a.get("name", "") for a in t.get("artists") or [])
            by = html.escape(artist_names or performer) if (artist_names or performer) else None
            lines.append(f"• {title}" + (f" — {by}" if by else ""))
        lines.append("")

    if artists:
        lines.append("<b>🎤 Artists</b>")
        for a in artists:
            name = html.escape(a.get("name") or "Unknown")
            likes = a.get("likes_count", 0)
            lines.append(f"• {name} ({likes} likes)")
        lines.append("")

    lines.append("Tap a track below to open it in the app.")
    return "\n".join(lines)
