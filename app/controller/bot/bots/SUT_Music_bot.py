import asyncio
import json
import re
import unicodedata
from pathlib import Path
from typing import Optional

import aiofiles
import httpx


from telethon import TelegramClient, types
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeCustomEmoji,
    ReactionEmoji,
    ReactionCustomEmoji,
    MessagePeerReaction
)
from telethon.tl.functions.messages import GetMessageReactionsListRequest, GetCustomEmojiDocumentsRequest
from telethon.tl.types import InputPeerChannel, InputPeerChat

from config import get_config
from model.SUTMusic.artist_reaction import ArtistReaction
from model.SUTMusic.cover import Cover
from model.SUTMusic.reaction_type import ReactionType
from model.SUTMusic.track_reaction import TrackReaction
from model.SUTMusic.user_musicbot_state import UserMusicBotState
# async DB models
from model.objects.user import User
from model.objects.chat import Chat
from model.SUTMusic.track import Track
from model.SUTMusic.artist import Artist
from utils.loggers.error_logger import ErrorLogger
from utils.loggers.flag_logger import FlagLogger
from webapp.enrichment_queue import EnrichmentQueue, PRIORITY_CLIENT
from webapp import repository as webapp_repository

# The scraper runs as its own OS process (see deploy/start.sh -- `python
# main.py` and `uvicorn webapp.main:app` are separate processes, not one),
# so it can't reach into the webapp's in-memory track_queue/artist_queue
# (webapp/enrichment_queue.py) -- those only exist, and only have running
# workers, inside the webapp process. Rather than duplicate the queueing
# logic, this reuses the exact same EnrichmentQueue class (and the exact
# same underlying Last.fm/fanart.tv fetch functions from webapp/repository.py
# -- same DB, same Track/Artist models, so it's fully safe to call directly)
# with its own small pool scoped to this process. Same "lazy background
# fetch, never block the caller" behavior new tracks/artists get from a real
# request, now also applied the moment the scraper itself creates them.
_scraper_track_enrichment_queue = EnrichmentQueue("scraper-track", num_workers=2)
_scraper_artist_enrichment_queue = EnrichmentQueue("scraper-artist", num_workers=2)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
INTERNAL_DB_SESSION = f"{PROJECT_ROOT}/db/db_files/collect_data.json"

TELEGRAM_BOT_API = "https://api.telegram.org"

telegram_sutmusic = get_config().TELEGRAM_SUTMusic


class SUT_Music_bot():
    api_id = 1
    api_hash = ""
    sut_music_chat_id = 1
    storage_chat_id = 1

    def __init__(self):
        pass

    async def initialize_bot(self):
        try:
            pass
        except Exception as e:
            ErrorLogger.background_log_error(7, f"error in initialize_bot as {e}", e)

        # -------------------------
        # STATIC HELPER METHODS
        # -------------------------

    @staticmethod
    async def _load_last_offset() -> int:
        """Read the last offset from the JSON file if it exists, else return 0."""
        file_path = Path(INTERNAL_DB_SESSION)
        if file_path.is_file():
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    data = json.loads(content)
                    return data.get("last_offset", 0)
            except Exception as e:
                ErrorLogger.background_log_error(7, f"Error reading JSON offset: {e}", e)
        return 0

    @staticmethod
    async def _save_last_offset(offset: int):
        """Save the given offset to the JSON file without overwriting other keys."""
        file_path = Path(INTERNAL_DB_SESSION)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        data = {}
        if file_path.is_file():
            try:
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    data = json.loads(content)
            except Exception:
                pass  # If file is corrupt, overwrite with empty dict structure

        data["last_offset"] = offset

        try:
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=4))
        except Exception as e:
            ErrorLogger.background_log_error(7, f"Error writing JSON offset: {e}", e)

    @staticmethod
    def _get_clean_performer(raw_performer_str: str) -> str:
        """
        Returns the clean text for the display performer string.
        Removes all brackets, parentheses, and their contents, keeping text clean for the UI.
        """
        if not raw_performer_str:
            return ""

        # 1. Remove complete brackets first so handles/bullets inside them don't break the string
        brackets_pattern = r'(\[.*?\]|\(.*?\)|\{.*?\}|<.*?>)'
        cleaned = re.sub(brackets_pattern, '', raw_performer_str)

        # 2. Now safely remove trailing promotional junk, handles, and bullets
        cleaned = re.split(r'(?:•|@)', cleaned)[0]

        return " ".join(cleaned.split()).strip()

    @staticmethod
    def _extract_artists(clean_performer_str: str) -> list[str]:
        """
        Splits the clean performer string into individual artist names.
        Handles symbols (~ : + , & - / | \\) and word delimiters (ft, feat, featuring, vs).
        """
        if not clean_performer_str:
            return []

        delimiters_pattern = r'(?:[~:+,&\-/|\\\\]+|\bfeat(?:uring)?\b|\bft\b|\bvs\b)'
        possible_artists = re.split(delimiters_pattern, clean_performer_str, flags=re.IGNORECASE)
        return [artist.strip() for artist in possible_artists if artist.strip()]

    # Unicode "format" (Cf) characters are invisible-by-design (soft hyphen,
    # zero-width space/joiner, word joiner, BOM, bidi marks, ...) and have no
    # business surviving into an artist name or track title -- they're
    # copy-paste noise (e.g. "Don Toliver\u00ad", a real artist name with a
    # trailing soft hyphen someone's keyboard/app inserted), and they make two
    # names that *look* identical actually compare unequal, breaking the
    # dedup/lookup logic below. Control characters (Cc) are stripped for the
    # same reason. Combining marks etc. are left alone -- diacritics are real,
    # meaningful characters (Beyoncé, Sigur Rós), not noise.
    @staticmethod
    def _strip_invisible_chars(text: str) -> str:
        if not text:
            return text
        return "".join(ch for ch in text if unicodedata.category(ch) not in ("Cf", "Cc"))

    # A short blocklist of tokens that regularly survive artist-splitting as
    # if they were a real artist name, but never are one: leftover session
    # descriptors, format tags, and uploader-added junk.
    _ARTIST_NAME_BLOCKLIST = {
        "live", "remix", "cover", "acoustic", "instrumental", "official",
        "audio", "video", "unknown", "unknown artist", "various artists",
        "va", "original mix", "explicit", "clean", "official audio",
        "official video", "hq", "prod", "prod by", "n/a", "na",
    }

    # Matches a bare domain-shaped string end-to-end, e.g. "Fa.Com",
    # "musicbot.ir" -- a website/handle that ended up parsed out as if it
    # were an artist, not an actual artist name.
    _DOMAIN_LIKE_PATTERN = re.compile(
        r'^[a-z0-9-]+\.(com|net|org|io|co|tv|me|cc|info|biz|ru|xyz|ir|app|gg|link|to)$',
        re.IGNORECASE,
    )

    @staticmethod
    def _normalize_artist_name(raw_name: str) -> Optional[str]:
        """
        Takes one already-split artist name and either returns a clean,
        usable version of it, or None if it isn't actually an artist name
        at all. Returning None means "drop this one silently" -- the caller
        filters those out.
        """
        if not raw_name:
            return None

        name = SUT_Music_bot._strip_invisible_chars(raw_name)

        # Defensive re-strip of any bracket pairs that leaked through
        # individually (e.g. a stray "(Live)" that wasn't part of a fully
        # bracket-wrapped performer string to begin with, so
        # _get_clean_performer never saw it as a group to remove).
        name = re.sub(r'(\[.*?\]|\(.*?\)|\{.*?\}|<.*?>)', '', name)

        # Leading/trailing punctuation and whitespace -- catches names that
        # start with "." (the leftover from an "ft."/"feat." split eating
        # the word but not the trailing period), stray dashes, colons, etc.
        name = name.strip(" \t\r\n.,;:!?-_'\"|/\\")
        name = " ".join(name.split())  # collapse internal whitespace

        if not name:
            return None
        if name.lower() in SUT_Music_bot._ARTIST_NAME_BLOCKLIST:
            return None
        if SUT_Music_bot._DOMAIN_LIKE_PATTERN.match(name):
            return None
        if not re.search(r'\w', name, flags=re.UNICODE):
            # Nothing left but punctuation/symbols.
            return None

        return name

    @staticmethod
    def _clean_artist_names(raw_names: list[str]) -> list[str]:
        """Normalizes every split artist name, drops the ones that turn out
        not to be real names (see _normalize_artist_name), and de-duplicates
        case-insensitively while keeping first-seen order -- so a messy
        performer string that splits into the same artist twice (e.g. a
        copy-pasted "Drake, Drake" caption) doesn't create two identical
        entries in artists_id for one track."""
        cleaned: list[str] = []
        seen_lower: set[str] = set()
        for raw in raw_names:
            name = SUT_Music_bot._normalize_artist_name(raw)
            if not name:
                continue
            key = name.lower()
            if key in seen_lower:
                continue
            seen_lower.add(key)
            cleaned.append(name)
        return cleaned

    # Titles that mean "no real title was ever given" -- either literally
    # empty, or a placeholder someone's uploader client/tagger writes when
    # it has nothing better (a bare ".", "...", "-", "N/A", "untitled", ...).
    _INVALID_TITLE_VALUES = {
        "", ".", "..", "...", "....", "-", "--", "_", "n/a", "na",
        "unknown", "untitled", "no title", "none", "null",
    }

    @staticmethod
    def _is_valid_track_title(raw_title: str) -> bool:
        """False means: skip this track entirely, don't save it. Covers a
        missing title, a placeholder like "." / "..." / "untitled", and a
        title that, once cleaned, is nothing but punctuation/symbols with no
        actual letters, digits, or other word characters in it."""
        if not raw_title:
            return False
        cleaned = SUT_Music_bot._strip_invisible_chars(raw_title).strip()
        if not cleaned:
            return False
        if cleaned.lower() in SUT_Music_bot._INVALID_TITLE_VALUES:
            return False
        if not re.search(r'\w', cleaned, flags=re.UNICODE):
            return False
        return True

    @staticmethod
    async def _resolve_custom_emoji_alt(client: TelegramClient, document_id: int) -> Optional[str]:
        """Custom/premium emoji reactions carry a `document_id`, not a
        Unicode character -- the old code stored the literal string
        "CustomEmoji" as if that WAS the emoji, which meant every custom
        reaction, no matter which one was actually picked, collapsed into
        one meaningless catch-all reaction_types row. Telegram documents for
        custom emoji carry a DocumentAttributeCustomEmoji with an `alt`
        field: the ordinary Unicode character the custom emoji is a reskin
        of (a custom fire-emoji sticker's `alt` is still "\U0001F525"). Resolving
        that lets a custom emoji reaction behave exactly like a normal one.
        Returns None if it can't be resolved, so the caller can skip the
        reaction entirely instead of inserting another placeholder row."""
        try:
            docs = await client(GetCustomEmojiDocumentsRequest(document_id=[document_id]))
            for doc in docs or []:
                for attr in getattr(doc, "attributes", []) or []:
                    if isinstance(attr, DocumentAttributeCustomEmoji) and getattr(attr, "alt", None):
                        return attr.alt
        except Exception as e:
            FlagLogger.background_flag(8, f"[custom emoji] Failed to resolve document {document_id}: {e}")
        return None

    @staticmethod
    async def _resolve_bot_api_media(chat_id: int, message_id: int) -> Optional[dict]:
        """Recovers a genuine Bot-API `file_id` (and, if the file has one, an
        embedded cover-art thumbnail) for a message this scraper just
        archived via the Telethon *userbot* session.

        `msg.document.id` (what used to be stored directly as `file_id`) is
        an MTProto document id from the userbot session, not a Bot-API
        file_id -- calling Bot API `getFile` with it 400s downstream (see
        webapp/media.py's own docstring, which documents this exact bug and
        ships a reactive per-track self-heal for it). The only way to get a
        real, Bot-API-usable file_id for an already-archived message is to
        have the *bot* itself forward that message once; the returned
        Message object carries a fresh, valid file_id -- and, as a bonus,
        Telegram nests any embedded audio artwork right there as a `thumb`/
        `thumbnail` object with its own real file_id, so this same call
        covers "fetch the cover while scraping" too, at no extra API cost.

        Doing this once here, at ingestion time, means a track has a working
        file_id (and cover, when the file embeds one) from the moment it's
        saved, instead of 400ing on its first play and self-healing
        reactively. webapp/media.py's resolve_message_file_id stays in place
        as a safety net for anything ingested before this fix, and as a
        fallback for any deployment that hasn't set BOT_TOKEN here.

        Returns None (never raises) if BOT_TOKEN isn't configured or the
        call fails for any reason -- callers fall back to the old behavior.
        """
        bot_token = telegram_sutmusic.get('bot_token')
        if not bot_token:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{TELEGRAM_BOT_API}/bot{bot_token}/forwardMessage",
                    json={
                        "chat_id": chat_id,
                        "from_chat_id": chat_id,
                        "message_id": message_id,
                        "disable_notification": True,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                if not payload.get("ok"):
                    return None
                result = payload.get("result") or {}
        except Exception as e:
            FlagLogger.background_flag(8, f"[file_id] Bot-API recovery failed for message {message_id}: {e}")
            return None

        media = result.get("audio") or result.get("document") or result.get("voice")
        if not media or not media.get("file_id"):
            return None

        thumb = media.get("thumbnail") or media.get("thumb")
        return {
            "file_id": media["file_id"],
            "unique_file_id": media.get("file_unique_id"),
            "thumb": {
                "file_id": thumb["file_id"],
                "unique_file_id": thumb.get("file_unique_id"),
                "width": thumb.get("width"),
                "height": thumb.get("height"),
            } if thumb and thumb.get("file_id") else None,
        }

    @staticmethod
    def _ensure_enrichment_workers_started() -> None:
        """Starts this process's own enrichment worker pools on first use.
        Both EnrichmentQueue.start_workers() calls are themselves idempotent
        (a no-op if already running), so it's safe to call this on every
        message -- it only actually spins anything up once."""
        _scraper_track_enrichment_queue.start_workers()
        _scraper_artist_enrichment_queue.start_workers()

    @staticmethod
    def _enqueue_track_enrichment(track_id: int, title: str, performer: str, cover_id: Optional[int]) -> None:
        """Lazy background Last.fm lookup for a track this scraper just
        created -- same job webapp/repository.enqueue_track_enrichment
        would schedule for it on a real request, just triggered at
        ingestion time instead of waiting for someone to ask for it first.
        Always fetches track details (summary) regardless of `cover_id`;
        only fetches a cover via Last.fm if `cover_id` is still None (i.e.
        the file had no embedded artwork -- see _resolve_bot_api_media)."""
        SUT_Music_bot._ensure_enrichment_workers_started()
        row: webapp_repository.Row = {
            "id": track_id, "title": title, "performer": performer,
            "cover_id": cover_id, "metadata": {},
        }
        if not webapp_repository.track_enrichment_pending(row):
            return
        _scraper_track_enrichment_queue.enqueue(
            f"track:{track_id}",
            lambda: webapp_repository._fetch_and_cache_track_lastfm(row),
            priority=PRIORITY_CLIENT,
        )

    @staticmethod
    def _enqueue_artist_enrichment(artist_id: int, name: str) -> None:
        """Lazy background Last.fm + MusicBrainz/fanart.tv lookup for an
        artist this scraper just created -- see _enqueue_track_enrichment's
        docstring, same idea. Only ever called for a genuinely new artist
        row (see the artist-creation loop below); an artist that already
        existed was already enqueued once, back when it was first created."""
        SUT_Music_bot._ensure_enrichment_workers_started()
        row: webapp_repository.Row = {
            "id": artist_id, "name": name, "description": None,
            "cover_id": None, "metadata": {},
        }
        description_pending, cover_pending = webapp_repository.artist_enrichment_pending(row)
        if not (description_pending or cover_pending):
            return
        _scraper_artist_enrichment_queue.enqueue(
            f"artist:{artist_id}",
            lambda: webapp_repository.enrich_artist_with_lastfm(artist_id, row),
            priority=PRIORITY_CLIENT,
        )

    @staticmethod
    async def user_checker(chat_id: int,
                           username: Optional[str]=None,
                           first_name: Optional[str]=None,
                           last_name: Optional[str]=None):

        user = await Chat.get_user_by_chat_id(chat_id)
        if user is None:
            print(f"[DB] Registering new User profile for Chat ID: {chat_id}")
            result = await User.create()
            if not result.success:
                ErrorLogger.background_log_error(7, f"Failed at making new user with chat_id: {chat_id}")
                return None

            user: User = result.data
            result = await user.assign_user_fields(first_name=first_name,
                                                   last_name=last_name, username=username)

            user_chat = await Chat.get_by_id(chat_id)
            await user_chat.assign_user_id(user.user_id)

            if not result.success:
                ErrorLogger.background_log_error(7,
                                                 f"Failed at assigning new user telebot parameter at chat_id: {chat_id}")
                return None

        else:
            print(f"[DB] Found matching User profile for Chat ID: {chat_id}")
            user_chat = await Chat.get_by_id(chat_id)
            have_chat_id = await user_chat.get_parameter("user_id")
            if not have_chat_id:
                await user.assign_user_fields(first_name=first_name,
                                              last_name=last_name, username=username)
            else:
                if username:
                    await user.update_parameter("username", username)
                if first_name:
                    await user.update_parameter("first_name", first_name)
                if last_name:
                    await user.update_parameter("last_name", last_name)

        return user

    @staticmethod
    async def chat_checker(chat_id: int,
                           first_name: Optional[str]=None,
                           last_name: Optional[str]=None,
                           username: Optional[str]=None):

        chat = await Chat.get_by_id(chat_id)
        if chat is None:
            print(f"[DB] Creating new private Chat record for ID: {chat_id}")
            result = await Chat.create(chat_id=chat_id, chat_type="private")
            if not result.success:
                ErrorLogger.background_log_error(7,
                                                 f"Failed at making new chat with chat_id: {chat_id} and chat_type: private")
                return None

            chat: Chat = result.data
            result = await chat.assign_chat_fields(title=None,
                                                   first_name=first_name,
                                                   last_name=last_name,
                                                   username=username)

            if not result.success:
                ErrorLogger.background_log_error(7,
                                                 f"Failed at assigning new chat fields parameter at chat_id: {chat_id}")
                return None

        else:
            print(f"[DB] Found existing Chat session ID: {chat_id}")
            have_chat_id = await chat.get_parameter("username") or await chat.get_parameter("title")
            if not have_chat_id:
                await chat.assign_chat_fields(title=None,
                                              first_name=first_name,
                                              last_name=last_name,
                                              username=username
                                              )
            else:
                await chat.update_parameter("username", username)
                await chat.update_parameter("first_name", first_name)
                await chat.update_parameter("last_name", last_name)

        return chat




    @staticmethod
    async def collect_data():
        """
        Main execution method for the scheduled task.
        Instantiates the client, fetches messages, processes them, and saves progress.
        """
        SUT_Music_bot.api_id = int(telegram_sutmusic.get('api_id'))
        SUT_Music_bot.api_hash = telegram_sutmusic.get('api_hash')
        SUT_Music_bot.sut_music_chat_id = int(telegram_sutmusic.get('sut_music_chat_id'))
        SUT_Music_bot.storage_chat_id = int(telegram_sutmusic.get('storage_chat_id'))

        client = TelegramClient("collect_data", SUT_Music_bot.api_id, SUT_Music_bot.api_hash)

        try:
            await client.start()
            FlagLogger.background_flag(8, "[INFO] Connected to Telegram. Starting data collection...")

            try:
                entity = await client.get_entity(SUT_Music_bot.sut_music_chat_id)
                if hasattr(entity, 'megagroup') or hasattr(entity, 'broadcast'):
                    peer = InputPeerChannel(channel_id=entity.id, access_hash=entity.access_hash)
                else:
                    peer = InputPeerChat(chat_id=entity.id)
            except Exception as e:
                ErrorLogger.background_log_error(8,
                                                 f"❌ [Reaction Sync] Failed to resolve entity for group {SUT_Music_bot.sut_music_chat_id}: {e}")
                return

            chat_entity = await client.get_input_entity(SUT_Music_bot.sut_music_chat_id)
            offset_id = await SUT_Music_bot._load_last_offset()
            limit = 100
            previous_track = ""
            global_track_counter = 0

            while True:
                try:
                    await asyncio.sleep(1.5)
                    messages = await client.get_messages(
                        chat_entity,
                        offset_id=offset_id,
                        limit=limit,
                        reverse=True
                    )
                except FloodWaitError as e:
                    FlagLogger.background_flag(8, f"[FloodWaitError] Sleeping for {e.seconds} seconds...")
                    await asyncio.sleep(e.seconds)
                    continue
                except Exception as e:
                    ErrorLogger.background_log_error(7, f"Error fetching messages: {e}", e)
                    break

                if not messages:
                    FlagLogger.background_flag(8, "[INFO] No more messages found. Finished.")
                    break

                try:
                    sender_ids = list({msg.sender_id for msg in messages if msg.sender_id})
                    if sender_ids:
                        await client.get_entity(sender_ids)
                except Exception as e:
                    FlagLogger.background_flag(7, f"[INFO] Cache notice during batch pre-fetch optimization: {e}")

                for msg in messages:
                    if msg.media and getattr(msg, 'document', None):
                        global_track_counter += 1
                        previous_track = await SUT_Music_bot._process_message(client, peer, msg, previous_track, global_track_counter)
                        offset_id = msg.id
                        asyncio.create_task(SUT_Music_bot._save_last_offset(offset_id))
                    else:
                        print(f"Skipping non-audio message ID: {msg.id}")

                if len(messages) < limit:
                    FlagLogger.background_flag(5, "[INFO] Reached the last batch of messages.")
                    break

        except Exception as e:
            ErrorLogger.background_log_error(7, f"Critical error in collect_data: {e}", e)
        finally:
            await client.disconnect()
            FlagLogger.background_flag(8, "[INFO] Client disconnected.")

    @staticmethod
    async def _process_message(client: TelegramClient, peer, msg, previous_track: str, track_number: int) -> str:
        """Processes a single message, forwarding audio and organizing metadata."""
        if not msg.media or not getattr(msg, 'document', None):
            return previous_track

        print(f"\n--- Processing Audio Item #{track_number} (Telegram Message ID: {msg.id}) ---")
        mime = getattr(msg.document, 'mime_type', '') or ''

        from telethon.utils import get_extension
        extension = get_extension(msg.document)

        attr_audio = None
        attr_filename = None

        for attr in msg.document.attributes:
            if isinstance(attr, DocumentAttributeAudio):
                attr_audio = attr
            elif isinstance(attr, DocumentAttributeFilename):
                attr_filename = attr

        track_name = ""
        artist_str = ""

        if mime.startswith("audio"):
            file_type = "audio"
            if attr_audio:
                possible_title = getattr(attr_audio, 'title', None) or ""
                possible_perf = getattr(attr_audio, 'performer', None) or ""
                track_name = possible_title.strip()
                artist_str = possible_perf.strip()
            else:
                if attr_filename and attr_filename.file_name:
                    fn_no_ext = attr_filename.file_name.rsplit('.', 1)[0]
                    track_name = fn_no_ext.strip()
        else:
            if attr_filename and attr_filename.file_name.lower().endswith(('.mp3', '.wav', '.flac', '.ogg')):
                file_type = "document"
                fn_no_ext = attr_filename.file_name.rsplit('.', 1)[0]
                track_name = fn_no_ext.strip()
            else:
                print(f"Skipped: Message {msg.id} document properties do not match structural audio criteria.")
                return previous_track

        performer = SUT_Music_bot._get_clean_performer(artist_str)
        artist_names = SUT_Music_bot._clean_artist_names(SUT_Music_bot._extract_artists(performer))
        print(f"Extracted Raw String: '{artist_str}' -> Parsed Artists List: {artist_names}")

        track_name = SUT_Music_bot._strip_invisible_chars(track_name).strip()
        if not SUT_Music_bot._is_valid_track_title(track_name):
            print(f"Skipped: Message {msg.id} has no usable track title ('{track_name}'). Not saving.")
            FlagLogger.background_flag(5, f"[INFO] Skipped msg {msg.id}: no usable track title.")
            return previous_track

        await asyncio.sleep(1)

        try:
            forwarded = await client.forward_messages(
                entity=SUT_Music_bot.storage_chat_id,
                messages=msg.id,
                from_peer=SUT_Music_bot.sut_music_chat_id
            )
            if isinstance(forwarded, list):
                forwarded = forwarded[0]
            storage_msg_id = forwarded.id
            print(f"Forwarded successfully. Storage Message ID assigned: {storage_msg_id}")
        except FloodWaitError as e:
            FlagLogger.background_flag(8, f"[FloodWaitError while forwarding] Sleeping {e.seconds}s...")
            await asyncio.sleep(e.seconds)
            forwarded = await client.forward_messages(
                entity=SUT_Music_bot.storage_chat_id,
                messages=msg.id,
                from_peer=SUT_Music_bot.sut_music_chat_id
            )
            if isinstance(forwarded, list):
                forwarded = forwarded[0]
            storage_msg_id = forwarded.id
        except Exception as e:
            ErrorLogger.background_log_error(7, f"Failed to forward msg {msg.id}: {e}", e)
            return previous_track

        sender = await msg.get_sender()

        sender_user = None
        user_state = None
        sender_username = None

        if sender and isinstance(sender, types.User):
            sender_chat_id = sender.id
            sender_username = getattr(sender, 'username', None)
            sender_first_name = getattr(sender, 'first_name', None)
            sender_last_name = getattr(sender, 'last_name', None)

            print(f"Sender Meta identified: @{sender_username} (ID: {sender_chat_id})")
            if sender_chat_id:
                sender_chat = await SUT_Music_bot.chat_checker(
                    chat_id=sender_chat_id,
                    first_name=sender_first_name,
                    last_name=sender_last_name,
                    username=sender_username
                )

                sender_user = await SUT_Music_bot.user_checker(
                    chat_id=sender_chat_id,
                    first_name=sender_first_name,
                    last_name=sender_last_name,
                    username=sender_username
                )

                user_state = await UserMusicBotState.get_by_user_id(sender_user.user_id)
                if not user_state:
                    user_state = (await UserMusicBotState.create(sender_user.user_id)).data

            if sender_chat is None or sender_user is None:
                ErrorLogger.background_log_error(7, f"Failed to verify or make user database records for msg {msg.id}")

        else:
            FlagLogger.background_flag(5, f"[INFO] Message {msg.id}: Posted by Unknown entity types/Channels.")



        # --- DB INSTANTIATION: ARTISTS ---
        artists_id = []
        artists_obj = []

        for single_artist_name in artist_names:
            found_artists = await Artist.search_artists(
                conditions={"name": ("ilike", f"{single_artist_name}")},
                limit=1
            )
            if found_artists is None or len(found_artists) == 0:
                print(f"[DB-Artist] '{single_artist_name}' not found. Inserting new record...")
                result_a = await Artist.create(name=single_artist_name)
                if result_a.success:
                    artists_id.append(result_a.data.artist_id)
                    artists_obj.append(result_a.data)
                    SUT_Music_bot._enqueue_artist_enrichment(result_a.data.artist_id, single_artist_name)
            else:
                print(f"[DB-Artist] Match discovered: '{single_artist_name}' (ID: {found_artists[0].artist_id}) already in database.")
                artists_id.append(found_artists[0].artist_id)
                artists_obj.append(found_artists[0])

        # Recover a genuine Bot-API file_id (and, if the file embeds one, a
        # cover thumbnail) for the copy we just archived -- see
        # _resolve_bot_api_media's docstring for why msg.document.id itself
        # is the wrong thing to store here.
        bot_media = await SUT_Music_bot._resolve_bot_api_media(SUT_Music_bot.storage_chat_id, storage_msg_id)
        resolved_file_id = (bot_media or {}).get("file_id") or str(msg.document.id)
        resolved_unique_file_id = (bot_media or {}).get("unique_file_id") or str(msg.document.access_hash)

        # --- DB INSTANTIATION: TRACK ---
        track_search_results = await Track.search_tracks(conditions={
            "title": ("ilike", f"{track_name}"),
            "performer": ("ilike", f"{performer}")
        }, limit=1)

        if track_search_results is None or len(track_search_results) == 0:
            print(f"[DB-Track] '{track_name}' by '{performer}' not found. Adding track entity...")

            cover_id = None
            thumb = (bot_media or {}).get("thumb")
            if thumb and sender_user:
                # The audio file already carries embedded artwork -- seed
                # the cover from that instead of waiting on the separate
                # Last.fm/fanart.tv enrichment pass to find one later (see
                # webapp/repository.py's enrichment queue, which only ever
                # enqueues a job for a track that still has no cover_id).
                cover_res = await Cover.create(uploaded_by=sender_user.user_id, source="telegram_embedded")
                if cover_res.success:
                    cover_obj = cover_res.data
                    await cover_obj.update_parameter("file_id", thumb["file_id"])
                    await cover_obj.update_parameter("unique_file_id", thumb.get("unique_file_id"))
                    await cover_obj.update_parameter("width", thumb.get("width"))
                    await cover_obj.update_parameter("height", thumb.get("height"))
                    cover_id = cover_obj.cover_id

            track_res = await Track.create(
                file_id=resolved_file_id,
                unique_file_id=resolved_unique_file_id,
                file_type=file_type,
                mime_type=mime,
                extension=extension,
                title=track_name,
                artists_id=artists_id,
                performer=performer,
                cover_id=cover_id,
                duration=getattr(attr_audio, 'duration', None) if attr_audio else None,
                uploaded_by=[int(sender_user.user_id)] if sender_user else None,
                chat_id=SUT_Music_bot.storage_chat_id,
                message_id=storage_msg_id
            )
            if track_res.success:
                final_track_instance = track_res.data
                print(f"[SUCCESS] New track committed to DB: ID {final_track_instance.track_id}")
                SUT_Music_bot._enqueue_track_enrichment(
                    final_track_instance.track_id, track_name, performer, cover_id
                )
            else:
                ErrorLogger.background_log_error(7, f"Failed committing track record structural payload for track: {track_name}")
                return previous_track
        else:
            final_track_instance = track_search_results[0]
            if sender_user:
                prev_uploaded_by = await final_track_instance.get_parameter("uploaded_by")
                if not prev_uploaded_by:
                    prev_uploaded_by = []
                prev_uploaded_by.append(int(sender_user.user_id))
                await final_track_instance.update_parameter("uploaded_by", prev_uploaded_by)
            print(f"[DB-Track] Duplicate found. Reusing track instance ID: {final_track_instance.track_id}")

        if user_state:
            await user_state.uploaded_track(track_id=final_track_instance.track_id, artist_id=artists_id)

        # --- PLACEHOLDER FOR REACTION GATHERING LOGIC ---
        if msg.reactions and msg.reactions.can_see_list:
            await SUT_Music_bot._collect_reactions(client, peer, msg, final_track_instance, artists_id, artists_obj, sender_user, user_state)


        print(f"Processed summary: #{track_number} -> '{track_name}' by {artist_names} | submitted by @{sender_username}")
        return str(final_track_instance.track_id)

    @staticmethod
    async def _collect_reactions(client, peer, msg, track_obj: Track, artists_id: list[int], artists_obj: list[Artist], sender_user:User, user_state:UserMusicBotState):
        """
        Isolated structural logic wrapper for historical evaluation.
        Fetches reactions via Telethon and updates TrackReaction/ArtistReaction database entries.
        """

        # 2. Extract Required Track metadata
        track_id = track_obj.track_id

        all_reactions = []
        offset = 0
        limit = 100

        # 3. Pagination Scraping Loop
        while True:
            try:
                resp = await client(GetMessageReactionsListRequest(
                    peer=peer,
                    id=msg.id,
                    limit=limit,
                    offset=str(offset)
                ))
            except FloodWaitError as e:
                print(f"⚠️ [FloodWaitError] Sleeping {e.seconds}s during reaction collection...")
                await asyncio.sleep(e.seconds)
                continue
            except Exception as e:
                print(f"❌ [Error] Failed to fetch reaction batch: {e}")
                break

            if not resp.reactions:
                break

            all_reactions.extend(resp.reactions)
            offset += len(resp.reactions)

            if len(resp.reactions) < limit:
                break

        # 4. Parse & Ingest Reactions Into DB Layers
        for reac in all_reactions:
            if not isinstance(reac, MessagePeerReaction):
                continue

            chat_id = getattr(reac.peer_id, 'user_id', None)
            if not chat_id:
                continue

            username = getattr(reac.peer_id, 'username', None)
            first_name = getattr(reac.peer_id, 'first_name', None)
            last_name = getattr(reac.peer_id, 'last_name', None)

            print(f"Sender Meta identified: @{username} (ID: {chat_id})")

            chat = await SUT_Music_bot.chat_checker(
                chat_id=chat_id,
                first_name=first_name,
                last_name=last_name,
                username=username
            )

            user = await SUT_Music_bot.user_checker(
                chat_id=chat_id,
                first_name=first_name,
                last_name=last_name,
                username=username
            )

            sender_user_state = await UserMusicBotState.get_by_user_id(user.user_id)
            if not sender_user_state:
                sender_user_state = (await UserMusicBotState.create(user.user_id)).data

            if chat is None or user is None:
                ErrorLogger.background_log_error(7,
                                                 f"Failed to verify or make user database records for msg {msg.id} for reaction")

            # Extract Emoji string
            reaction_emoji = None
            if isinstance(reac.reaction, ReactionEmoji):
                reaction_emoji = reac.reaction.emoticon
            elif isinstance(reac.reaction, ReactionCustomEmoji):
                # Custom/premium emoji carry a document_id, not a Unicode
                # character -- try to resolve it to the ordinary emoji it's
                # a reskin of (see _resolve_custom_emoji_alt). If that can't
                # be resolved, fall back to the "CustomEmoji" catch-all row
                # that's now a deliberate, kept entry in reaction_types
                # rather than dropping the reaction entirely.
                reaction_emoji = await SUT_Music_bot._resolve_custom_emoji_alt(client, reac.reaction.document_id) \
                    or "CustomEmoji"

            if not reaction_emoji:
                continue

            # reaction_types is now a hand-curated, already-unique table
            # (every row synced against Telegram's own reaction set), so
            # this is a direct save: exact-match lookup, and only create a
            # new row for something genuinely not in the table yet.
            rx = await ReactionType.get_by_emoji(reaction_emoji)
            if not rx:
                FlagLogger.background_flag(8, f"Found new emoji of {reaction_emoji}")
                rx = (await ReactionType.create(reaction_emoji, "neutral")).data

            sentiment = await rx.get_parameter("sentiment") or "neutral"

            tasks = []
            if sentiment == "neutral":
                if user_state and user:
                    tasks.append(asyncio.create_task(user_state.received_reaction(from_track_id=track_id,
                                                                     from_artist_id=artists_id,
                                                                     from_user_id=user.user_id,
                                                                     reaction_id=rx.reaction_type_id)))
                if sender_user_state and sender_user:
                    tasks.append(asyncio.create_task(sender_user_state.sent_reaction(to_track_id=track_id,
                                                                        to_artist_id=artists_id,
                                                                        to_user_id=sender_user.user_id,
                                                                        reaction_id=rx.reaction_type_id)))
                if track_obj:
                    tasks.append(asyncio.create_task(track_obj.received_reaction()))
                if artists_obj and len(artists_obj) > 0:
                    for artist in artists_obj:
                        tasks.append(asyncio.create_task(artist.received_reaction()))

                if tasks:
                    await asyncio.gather(*tasks)

            if sentiment == "like":
                if user_state and user:
                    tasks.append(asyncio.create_task(user_state.received_like(from_track_id=track_id,
                                                                     from_artist_id=artists_id,
                                                                     from_user_id=user.user_id,
                                                                     reaction_id=rx.reaction_type_id)))
                if sender_user_state and sender_user:
                    tasks.append(asyncio.create_task(sender_user_state.sent_like(to_track_id=track_id,
                                                                        to_artist_id=artists_id,
                                                                        to_user_id=sender_user.user_id,
                                                                        reaction_id=rx.reaction_type_id)))
                if track_obj:
                    tasks.append(asyncio.create_task(track_obj.received_like()))
                    tasks.append(asyncio.create_task(track_obj.received_reaction()))
                if artists_obj and len(artists_obj) > 0:
                    for artist in artists_obj:
                        tasks.append(asyncio.create_task(artist.received_like()))
                        tasks.append(asyncio.create_task(artist.received_reaction()))

                if tasks:
                    await asyncio.gather(*tasks)

            if sentiment == "dislike":
                if user_state and user:
                    tasks.append(asyncio.create_task(user_state.received_dislike(from_track_id=track_id,
                                                                     from_artist_id=artists_id,
                                                                     from_user_id=user.user_id,
                                                                     reaction_id=rx.reaction_type_id)))
                if sender_user_state and sender_user:
                    tasks.append(asyncio.create_task(sender_user_state.sent_dislike(to_track_id=track_id,
                                                                        to_artist_id=artists_id,
                                                                        to_user_id=sender_user.user_id,
                                                                        reaction_id=rx.reaction_type_id)))
                if track_obj:
                    tasks.append(asyncio.create_task(track_obj.received_dislike()))
                    tasks.append(asyncio.create_task(track_obj.received_reaction()))
                if artists_obj and len(artists_obj) > 0:
                    for artist in artists_obj:
                        tasks.append(asyncio.create_task(artist.received_dislike()))
                        tasks.append(asyncio.create_task(artist.received_reaction()))

                if tasks:
                    await asyncio.gather(*tasks)

            # A) Ingest into Track Reactions Table
            track_res = await TrackReaction.create(
                track_id=track_id,
                user_id=user.user_id,
                reaction_id=rx.reaction_type_id,
                sentiment=sentiment,
                on_user_id=sender_user.user_id if sender_user else None,
                message_id=msg.id
            )

            if track_res.success:
                print(f" → [TRACK DB] Recorded '{reaction_emoji}' ({sentiment}) by User {user.user_id} on track {track_id}")

            # B) Ingest into Artist Reactions Table for every artist tied to this track
            if artists_id and len(artists_id) > 0:
                for artist_id in artists_id:
                    artist_res = await ArtistReaction.create(
                        artist_id=artist_id,
                        user_id=user.user_id,
                        reaction_id=rx.reaction_type_id,
                        sentiment=sentiment,
                        on_user_id=sender_user.user_id if sender_user else None,
                        message_id=msg.id
                    )

                    if artist_res.success:
                        print(f" → [ARTIST DB] Recorded '{reaction_emoji}' ({sentiment}) by User {user.user_id} on artist {artist_id}")

async def main():
    pass

if __name__ == "__main__":
    asyncio.run(main())