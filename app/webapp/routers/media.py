import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, RedirectResponse

from .. import repository as repo
from ..media import open_telegram_stream, resolve_telegram_file_url

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/cover/{cover_id}")
async def get_cover(cover_id: int):
    row = await repo.get_cover(cover_id)
    if not row:
        raise HTTPException(404, "Cover not found")

    if row.get("source") == "lastfm":
        url = await repo.get_or_refresh_lastfm_cover_url(cover_id)
        if not url:
            raise HTTPException(404, "Cover not found")
        return RedirectResponse(url, status_code=302)

    file_id = row.get("file_id")
    if not file_id:
        raise HTTPException(404, "Cover not found")

    try:
        url = await resolve_telegram_file_url(file_id)
        stream = await open_telegram_stream(url)
    except (httpx.HTTPStatusError, httpx.TransportError):
        raise HTTPException(502, "Failed to fetch cover from Telegram")

    return StreamingResponse(stream.iter_and_close(), media_type="image/jpeg")