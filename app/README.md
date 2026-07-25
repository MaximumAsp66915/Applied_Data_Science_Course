# SUT Music

A Telegram bot (`controller/`, `model/`, `db/`, `utils/`, `config/`, `main.py`) and its
companion Mini App web frontend (`frontend/`) + backend (`webapp/`), sharing one
live Postgres database.

## Layout

```
SUTMusic/
├── main.py              # bot entrypoint (unchanged from your original project)
├── controller/          # Telethon bot logic (unchanged)
├── initializer/         # bot startup (unchanged)
├── model/               # cached data-model layer (Track, Artist, User, Chat,
│                         #   TrackReaction, UserMusicBotState, ReactionType, Cover, ...)
│                         #   -- shared by BOTH the bot and the webapp
├── db/                   # low-level Postgres access + the encrypted DB session file
├── utils/                 # shared helpers (logging, time, results, ...)
├── config/                # env-based config for dev/prod
├── webapp/                # <-- NEW: FastAPI backend for the Mini App
│   ├── main.py            #   entrypoint: uvicorn webapp.main:app
│   ├── db_conn.py          #   grabs the bot's own shared Postgres connection
│   ├── repository.py       #   data access, built on model/ + raw joins for lists
│   ├── schema.py            #   column definitions used by repository.py
│   ├── serializers.py       #   DB row -> JSON shape the frontend expects
│   ├── telegram_auth.py      #   verifies Mini App initData (HMAC)
│   ├── media.py               #   proxies Telegram file_ids (audio/covers)
│   ├── config.py               #   webapp settings (BOT_TOKEN, CORS, ...)
│   └── routers/                 #   auth, users, tracks, artists, home, search,
│                                 #   ranks, suggestions, media
├── frontend/                     # <-- React (Vite + Tailwind) Mini App UI
├── requirements.txt               # bot + webapp dependencies, merged
└── .env.example
```

## Why this split works

Your original SUTMusic project already had a clean cached data layer
(`model/SUTMusic/*.py`, `model/objects/*.py`) sitting on top of a fast
Postgres helper (`db/postgreSQL_helper.py`) with per-field caching
(`AutoExpiringDict`). Rather than reinventing that, `webapp/repository.py`:

- Uses the **Model classes directly** (`Track`, `Artist`, `TrackReaction`,
  `User`, `Chat`, `UserMusicBotState`, `ReactionType`) for anything
  single-entity: login, reactions, counters. This is exactly where the
  caching in `model/` pays off, and it keeps the webapp's writes 100%
  consistent with what the Telegram bot itself does (same counters, same
  `user_musicbot_state` bookkeeping).
- Uses the **same underlying connection** (`webapp/db_conn.py` grabs
  `Internal_DB_Track().db`, which is the identical pooled connection every
  `Internal_DB_*` class in `db/internal_db/SUTMusic/*.py` uses — they all
  load the same encrypted session file) for list/search/leaderboard/
  analytics queries via `search_rows` / `fetch_all`, since those need
  multi-table joins the per-object model layer doesn't expose as one call.

No second database, no duplicated connection pool, no schema drift.

### One important discovery worth knowing about
`user_id` in `tracks.uploaded_by`, `track_reactions.user_id`,
`user_musicbot_state.user_id`, etc. is **not** the raw Telegram id — your bot
maps real Telegram `chat_id` → internal `user_id` through the `Chat` model
(`Chat.get_user_by_chat_id`, `User.create`, `chat.assign_user_id`). The
webapp's login flow (`webapp/repository.py::upsert_user_from_telegram`)
reproduces that exact same linkage, so someone who's used the bot in the
group and someone who only opens the Mini App resolve to the *same* row.

## Running it

```bash
pip install -r requirements.txt --break-system-packages   # or use a venv
cp .env.example .env                                       # fill in BOT_TOKEN at least
```

**Bot** (unchanged):
```bash
python main.py
```

**Webapp backend** (from the project root, so `model.*`/`db.*`/`utils.*`/`config.*` resolve):
```bash
uvicorn webapp.main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend**:
```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, talks to /api on :8000 via Vite proxy/VITE_API_URL
```

For production, build the frontend (`npm run build`) and serve `frontend/dist`
from your CDN/static host, pointing `VITE_API_URL` at your deployed
`webapp` backend, and set `CORS_ORIGINS` in `.env` to that frontend's origin.

## Required env vars (see `.env.example`)

- `BOT_TOKEN` — the classic `@BotFather` token. **This is new** — your bot
  previously only needed Telethon's `API_ID`/`API_HASH` (MTProto/userbot
  auth). The webapp needs a real Bot API token for two things: verifying the
  signed Mini App `initData` header, and resolving `file_id`s to bytes via
  `getFile` (audio streaming + cover images).
- `INTERNAL_DB_*` / `EXTERNAL_DB_*` — only used as a fallback; the shipped
  encrypted session file (`db/internal_db/internal_db_session.session`)
  already carries working credentials.
- `CORS_ORIGINS`, `SUGGESTION_ENGINE_URL` — webapp-only, see `.env.example`.

## What's stubbed / simplified (flagged honestly, not hidden)

- **Suggestions** (`GET /api/suggestions/next`): if `SUGGESTION_ENGINE_URL`
  isn't set, falls back to a simple "random pick among top-liked tracks you
  haven't reacted to" — a real recommender wasn't part of either zip you
  sent, so this keeps the endpoint honestly functional rather than fake.
- **`most_correlated` users** (Profile page "Community pulse"): computed with
  a straightforward reaction-overlap SQL query (agreement % on shared
  tracks, min. 3 overlapping reactions) rather than anything more
  sophisticated — swap the query in `repository.get_user_relations` if you
  want a fancier metric later.
- Track/artist/user **text search** uses plain `ILIKE` (fine for a
  friend-group-sized library); switch to the existing `fuzzy=True`
  trigram-similarity option already built into `db/postgreSQL_helper.py`'s
  `search_ids` if your catalog grows large enough that typo-tolerance
  matters more than raw simplicity.
