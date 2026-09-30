from app.services.camera_worker import CameraWorker


class CameraManager:
    """Singleton yang nge-track semua CameraWorker yang lagi jalan.
    Di-import dan dipakai bareng di seluruh app (main.py, api/cameras.py)."""

    def __init__(self):
        self.workers: dict[str, CameraWorker] = {}

    def start_camera(self, camera_id: str, stream_url: str, target_fps: int = 5, on_frame=None):
        if camera_id in self.workers and self.workers[camera_id].running:
            return  # udah jalan, skip
        worker = CameraWorker(camera_id, stream_url, target_fps, on_frame=on_frame)
        worker.start()
        self.workers[camera_id] = worker

    def stop_camera(self, camera_id: str):
        worker = self.workers.pop(camera_id, None)
        if worker:
            worker.stop()

    def stop_all(self):
        for cid in list(self.workers):
            self.stop_camera(cid)

    def status(self):
        return {
            cid: {"connected": w.connected, "running": w.running}
            for cid, w in self.workers.items()
        }


# singleton, di-import di mana-mana biar semua nunjuk ke instance yang sama
camera_manager = CameraManager()
