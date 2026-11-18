"""Tayangan langsung beranotasi dari sesi analisis yang sedang berjalan (integrasi AI Ops).

- GET /analysis-sessions/{id}/live.mjpg : stream MJPEG (multipart/x-mixed-replace), bisa langsung jadi src <img>
- GET /analysis-sessions/{id}/preview.jpg : satu frame beranotasi terakhir (thumbnail)

Aksesnya sama dengan sesi analisis: admin semua sesi, user biasa hanya sesi dari sumber miliknya.
Tidak ada yang disimpan ke disk; frame diambil dari memori SessionRunner yang sedang jalan."""
import asyncio
import time
import uuid

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.analysis_sessions import get_session_for_user
from app.core.database import get_db
from app.core.security import get_current_user_allow_query_token
from app.models.user import User
from app.services.inference.manager import inference_manager
from app.services.inference.preview import MAX_WIDTH, THUMB_WIDTH
from app.services.inference.session_runner import SessionRunner

router = APIRouter(prefix="/analysis-sessions", tags=["Live Preview"])

BOUNDARY = "frame"
POLL_SECONDS = 0.015         # cek frame baru ~60x per detik (kamera 30 fps tetap terkejar)
HEARTBEAT_SECONDS = 2.0      # kirim ulang frame terakhir kalau diam, supaya koneksi putus cepat ketahuan
FIRST_FRAME_WAIT_SECONDS = 3.0
SIZES = {"full": MAX_WIDTH, "thumb": THUMB_WIDTH}
SizeParam = Query("full", description="full = lebar maks. 1280 px, thumb = 480 px (kartu dashboard)")
NO_STORE = {"Cache-Control": "private, no-store, no-transform", "X-Content-Type-Options": "nosniff"}


def _live_runner(db: Session, session_id: uuid.UUID, user: User) -> SessionRunner:
    session = get_session_for_user(db, session_id, user)      # 404 kalau bukan miliknya
    status = session.status
    db.close()            # jangan tahan koneksi DB selama stream berjalan
    runner = inference_manager.runners.get(str(session_id))
    if status != "processing" or runner is None or not runner.is_alive():
        raise HTTPException(status_code=404, detail="Tayangan langsung hanya tersedia saat analisis berjalan")
    return runner


def _part(jpeg: bytes) -> bytes:
    return (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n").encode() + jpeg + b"\r\n"


async def _mjpeg(runner: SessionRunner, width: int):
    seen, sent_key, last_sent, data = None, None, 0.0, None
    while runner.is_alive():
        now = time.monotonic()
        seq = runner.preview.seq
        if seq != seen:
            seen = seq
            key, frame = await asyncio.to_thread(runner.preview.jpeg, width)
            if frame is not None and key != sent_key:
                sent_key, data, last_sent = key, frame, now
                yield _part(data)
        elif data is not None and now - last_sent >= HEARTBEAT_SECONDS:
            last_sent = now
            yield _part(data)
        await asyncio.sleep(POLL_SECONDS)


@router.get("/{session_id}/live.mjpg", response_class=StreamingResponse)
def live_mjpeg(
    session_id: uuid.UUID,
    size: Literal["full", "thumb"] = SizeParam,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_allow_query_token),
):
    """Video beranotasi real-time (MJPEG). Berakhir sendiri saat sesi selesai/dihentikan."""
    runner = _live_runner(db, session_id, current_user)
    return StreamingResponse(
        _mjpeg(runner, SIZES[size]),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={**NO_STORE, "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}/preview.jpg", response_class=Response)
def live_preview_jpeg(
    session_id: uuid.UUID,
    size: Literal["full", "thumb"] = SizeParam,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_allow_query_token),
):
    """Satu frame beranotasi terakhir. 404 kalau sesi tidak berjalan / belum ada frame."""
    runner = _live_runner(db, session_id, current_user)
    deadline = time.monotonic() + FIRST_FRAME_WAIT_SECONDS
    seq, data = runner.preview.jpeg(SIZES[size])
    while data is None and runner.is_alive() and time.monotonic() < deadline:
        time.sleep(0.1)      # model baru dimuat, tunggu sebentar frame pertama
        seq, data = runner.preview.jpeg(SIZES[size])
    if data is None:
        raise HTTPException(status_code=404, detail="Frame belum tersedia")
    return Response(content=data, media_type="image/jpeg", headers=NO_STORE)
