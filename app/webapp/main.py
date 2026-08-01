"""
FastAPI entrypoint for the SUT Music Mini App backend.

Run from the project root (the same directory as the bot's own main.py, so
that `model.*`, `db.*`, `utils.*`, `config.*` all resolve exactly the way
they do for the Telegram bot):

    uvicorn webapp.main:app --host 0.0.0.0 --port 8000 --reload

This backend does NOT open its own database connection -- it reuses the
bot's model/db layer (see webapp/db_conn.py), so both the bot and the Mini
App read/write the exact same live data with the exact same caching.
"""

from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from . import enrichment_queue
from .routers import auth, users, tracks, artists, home, search, ranks, latest, suggestions, media


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Starts the small background worker pool that drains the cover/
    # description enrichment queue (see webapp/enrichment_queue.py and
    # repository.enqueue_track_enrichment / enqueue_artist_enrichment). No
    # cover or description is ever fetched from Last.fm ahead of a request
    # -- these workers only ever process jobs that a real request already
    # queued because it found nothing for that track/artist in the DB.
    enrichment_queue.start_workers()
    yield
    await enrichment_queue.stop_workers()


app = FastAPI(title="SUT Music API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Content-Range/Accept-Ranges/Content-Length need to be readable by
    # cross-origin JS (not just the native <audio> element) for range-based
    # audio seeking to work reliably everywhere the Mini App is embedded.
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(tracks.router)
app.include_router(artists.router)
app.include_router(home.router)
app.include_router(search.router)
app.include_router(ranks.router)
app.include_router(latest.router)
app.include_router(suggestions.router)
app.include_router(media.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
