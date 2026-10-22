from app.services.inference.session_runner import SessionRunner


class InferenceManager:
    """Melacak SessionRunner yang sedang jalan (satu per sesi analisis)."""

    def __init__(self):
        self.runners: dict[str, SessionRunner] = {}

    def start(self, session_id) -> None:
        key = str(session_id)
        if key in self.runners and self.runners[key].is_alive():
            return
        runner = SessionRunner(session_id)
        runner.start()
        self.runners[key] = runner

    def stop(self, session_id, timeout: float = 60) -> None:
        """Minta runner berhenti lalu TUNGGU sampai hasil terakhir ditulis ke DB."""
        runner = self.runners.pop(str(session_id), None)
        if runner:
            runner.stop()
            runner.join(timeout)

    def stop_all(self) -> None:
        for key in list(self.runners):
            self.stop(key, timeout=15)

    def status(self) -> dict:
        self.runners = {k: r for k, r in self.runners.items() if r.is_alive()}
        return {k: {"alive": True} for k in self.runners}


inference_manager = InferenceManager()