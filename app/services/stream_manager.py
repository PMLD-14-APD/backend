from app.core.config import settings
from app.services.stream_worker import StreamWorker


class StreamManager:
    """Singleton yang nge-track semua StreamWorker (satu per sesi analisis CCTV) yang lagi jalan."""

    def __init__(self):
        self.workers: dict[str, StreamWorker] = {}

    def start(self, session_id: str, stream_url: str, target_fps: int = 5, on_frame=None):
        if session_id in self.workers and self.workers[session_id].running:
            return  # udah jalan, skip
        worker = StreamWorker(
            session_id, stream_url, target_fps, on_frame=on_frame,
            open_timeout=settings.stream_probe_timeout_seconds,
            retry_min_seconds=settings.stream_retry_min_seconds,
            retry_max_seconds=settings.stream_retry_max_seconds,
        )
        worker.start()
        self.workers[session_id] = worker

    def stop(self, session_id: str):
        worker = self.workers.pop(session_id, None)
        if worker:
            worker.stop()

    def stop_all(self):
        for sid in list(self.workers):
            self.stop(sid)

    def state_of(self, session_id: str) -> dict | None:
        """Status kamera satu sesi: state (connecting|connected|reconnecting), detik offline."""
        w = self.workers.get(session_id)
        if w is None:
            return None
        return {"state": w.state, "connected": w.connected, "offline_seconds": round(w.offline_seconds(), 1)}

    def status(self):
        return {
            sid: self.state_of(sid) | {"running": w.running}
            for sid, w in self.workers.items()
        }


# singleton, di-import di mana-mana biar semua nunjuk ke instance yang sama
stream_manager = StreamManager()
