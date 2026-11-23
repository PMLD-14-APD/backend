"""Satu thread = satu sesi analisis. Membaca frame (file atau stream CCTV), menjalankan
detektor, menilai kepatuhan tiap orang, lalu mengisi detection_logs, detection_log_items
dan compliance_stats. Selesai sendiri untuk file; stream berjalan sampai di-stop."""
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import cv2

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.ai_model import AIModel, ApdClass, EnvironmentApdClass
from app.models.analysis import AnalysisSession, ComplianceStat, DetectionLog, DetectionLogItem
from app.models.video_source import VideoSource
from app.services.analysis import finalize_session
from app.services.inference import detector as detector_module
from app.services.inference.compliance import LENGKAP, RANK, PersonResult, evaluate
from app.services.inference.preview import ItemOverlay, LivePreview, PersonOverlay
from app.services.inference.tracker import IouTracker
from app.services.stream_manager import stream_manager
from app.storage.local import save_snapshot


@dataclass
class TrackState:
    streak_status: str | None = None
    streak_len: int = 0
    confirmed: str | None = None          # status yang sudah stabil
    last_logged_status: str | None = None
    last_logged_at: float = 0.0


@dataclass
class Bucket:
    ranks: dict[int, int] = field(default_factory=dict)   # track_id -> status terburuk di jam ini
    dirty: bool = False


def iter_file_frames(path: str, target_fps: int, stop: threading.Event):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError(f"Gagal membuka file video: {path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, round(src_fps / max(target_fps, 1)))
    idx = 0
    try:
        while not stop.is_set():
            if not cap.grab():
                break
            if idx % step == 0:
                ok, frame = cap.retrieve()
                if ok:
                    yield idx, idx / src_fps, frame
            idx += 1
    finally:
        cap.release()


def iter_stream_frames(session_id: str, stop: threading.Event, target_fps: int = 5,
                       giveup_seconds: float | None = None):
    """Frame terbaru dari StreamWorker, paling banyak target_fps kali per detik.

    Selama kamera offline, generator menunggu (worker menyambung ulang sendiri) dan tidak ada frame
    yang dianalisis. Error hanya kalau offline lebih lama dari giveup_seconds (None/0 = tidak pernah)
    atau thread worker mati tanpa di-stop."""
    if giveup_seconds is None:
        giveup_seconds = settings.stream_offline_giveup_minutes * 60
    start, last_seq, n = time.time(), -1, 0
    interval, next_at = 1.0 / max(target_fps, 1), 0.0
    while not stop.is_set():
        worker = stream_manager.workers.get(session_id)
        if worker is None:
            return
        wait = next_at - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, 0.05))
            continue
        if worker.frame_seq == last_seq or worker.latest_frame is None or not worker.connected:
            if not worker.is_alive() and not stop.is_set():
                raise RuntimeError("Stream CCTV berhenti tanpa diminta")
            if giveup_seconds and worker.offline_seconds() > giveup_seconds:
                raise RuntimeError(
                    f"Kamera offline lebih dari {giveup_seconds / 60:g} menit (STREAM_OFFLINE_GIVEUP_MINUTES)")
            time.sleep(0.05 if not worker.connected else 0.005)
            continue
        seq, frame = worker.get_latest()
        if frame is None:
            continue
        next_at = time.monotonic() + interval
        last_seq = seq
        n += 1
        yield n, time.time() - start, frame


class SessionRunner(threading.Thread):
    def __init__(self, session_id: uuid.UUID):
        super().__init__(daemon=True, name=f"session-{session_id}")
        self.session_id = session_id
        self._stop_event = threading.Event()
        self.tracker = IouTracker(max_age=20)
        self.states: dict[int, TrackState] = {}
        self.buckets: dict[datetime, Bucket] = {}
        self.stat_rows: dict[datetime, uuid.UUID] = {}
        self.pending_logs: list[DetectionLog] = []
        self.preview = LivePreview()          # frame beranotasi terakhir untuk tayangan langsung

    def stop(self):
        self._stop_event.set()

    # ------------------------------------------------------------------
    def run(self):
        db = SessionLocal()
        status, error = "done", None
        try:
            ctx = self._load_context(db)
            detector = detector_module.load_detector(ctx["weights_path"])
            self._process(db, ctx, detector)
        except Exception as exc:                      # model gagal load, video rusak, stream putus, dll
            db.rollback()
            status, error = "failed", f"{type(exc).__name__}: {exc}"[:500]
            print(f"[session:{self.session_id}] GAGAL: {error}")
        finally:
            try:
                self._flush(db)
                if not self._stop_event.is_set():     # selesai sendiri / gagal -> kita yang menutup sesi
                    session = db.get(AnalysisSession, self.session_id)
                    if session is not None and session.status == "processing":
                        source = db.get(VideoSource, session.source_id)
                        if source is not None and source.source_type == "cctv_stream":
                            source.status = "inactive"
                        finalize_session(db, session, status, error)
                        db.commit()
                    stream_manager.stop(str(self.session_id))
            except Exception as exc:
                db.rollback()
                print(f"[session:{self.session_id}] gagal menutup sesi: {exc}")
            finally:
                db.close()

    # ------------------------------------------------------------------
    def _load_context(self, db) -> dict:
        session = db.get(AnalysisSession, self.session_id)
        source = db.get(VideoSource, session.source_id)
        model = db.get(AIModel, session.model_id)
        rows = (
            db.query(ApdClass)
            .join(EnvironmentApdClass, EnvironmentApdClass.apd_class_id == ApdClass.id)
            .filter(EnvironmentApdClass.environment_id == source.environment_id,
                    EnvironmentApdClass.is_mandatory.isnot(False))
            .order_by(ApdClass.label_key)
            .all()
        )
        if not rows:
            raise RuntimeError("Environment ini belum punya APD wajib (environment_apd_classes)")
        return {
            "source_type": source.source_type,
            "file_path": source.file_path,
            "stream_url": source.stream_url,
            "target_fps": source.target_fps,
            "weights_path": model.weights_path,
            "apd_ids": {r.label_key: r.id for r in rows},
            "apd_names": {r.label_key: r.name for r in rows},
        }

    def _process(self, db, ctx: dict, detector) -> None:
        if ctx["source_type"] == "video_upload":
            frames = iter_file_frames(ctx["file_path"], ctx["target_fps"], self._stop_event)
        else:
            frames = iter_stream_frames(str(self.session_id), self._stop_event, ctx["target_fps"])
            sid = str(self.session_id)
            self.preview.raw_source = lambda: stream_manager.workers.get(sid)   # tampilan live pakai fps penuh

        required = list(ctx["apd_ids"])
        last_flush = time.monotonic()
        for frame_no, video_ts, frame in frames:
            detections = detector.detect(frame)
            results = evaluate(detections, required, settings.person_label)
            ids = self.tracker.update([r.box for r in results], frame_no)
            now = datetime.now(timezone.utc)
            for result, tid in zip(results, ids):
                self._handle_person(ctx, result, tid, frame, frame_no, video_ts, now)
            self.states = {t: s for t, s in self.states.items() if t in self.tracker.tracks}
            self._update_preview(ctx, frame, detections, results, ids)

            if time.monotonic() - last_flush >= settings.stats_flush_seconds:
                self._flush(db)
                last_flush = time.monotonic()

    def _handle_person(self, ctx, result: PersonResult, tid: int, frame, frame_no, video_ts, now) -> None:
        st = self.states.setdefault(tid, TrackState())
        if result.status == st.streak_status:
            st.streak_len += 1
        else:
            st.streak_status, st.streak_len = result.status, 1
        if st.streak_len >= settings.confirm_frames:
            st.confirmed = st.streak_status
        if st.confirmed is None:
            return

        # statistik per jam: tiap orang dihitung sekali, pakai status terburuk yang sudah stabil
        bucket_key = now.replace(minute=0, second=0, microsecond=0)
        bucket = self.buckets.setdefault(bucket_key, Bucket())
        rank = RANK[st.confirmed]
        if rank > bucket.ranks.get(tid, -1):
            bucket.ranks[tid] = rank
            bucket.dirty = True

        if st.confirmed == LENGKAP:
            return
        mono = time.monotonic()
        if st.last_logged_status == st.confirmed and mono - st.last_logged_at < settings.violation_cooldown_seconds:
            return
        st.last_logged_status, st.last_logged_at = st.confirmed, mono

        missing = result.missing or [k for k in ctx["apd_ids"] if k not in result.present]
        x1, y1, x2, y2 = result.box
        log = DetectionLog(
            session_id=self.session_id,
            track_id=tid,
            compliance_status=st.confirmed,
            violation_type=",".join(f"NO_{k.upper()}" for k in missing),
            confidence=result.conf,
            frame_number=frame_no,
            video_timestamp=round(video_ts, 2),
            bbox={"x": round(x1, 1), "y": round(y1, 1), "w": round(x2 - x1, 1), "h": round(y2 - y1, 1)},
            image_url=save_snapshot(self.session_id, frame, result.box, f"ID{tid} {st.confirmed}"),
            detected_at=now,
            items=[
                DetectionLogItem(apd_class_id=apd_id, is_present=key in result.present,
                                 confidence=result.present.get(key, 0.0))
                for key, apd_id in ctx["apd_ids"].items()
            ],
        )
        self.pending_logs.append(log)

    def _update_preview(self, ctx, frame, detections, results, ids) -> None:
        names = ctx["apd_names"]
        persons = []
        for result, tid in zip(results, ids):
            st = self.states.get(tid)
            status = st.confirmed if st else None
            missing = tuple(names.get(k, k) for k in result.missing) if status and status != LENGKAP else ()
            persons.append(PersonOverlay(tid, result.box, status, missing))
        items = [ItemOverlay(names[d.label], d.box) for d in detections if d.label in names]
        self.preview.update(frame, persons, items)

    def _flush(self, db) -> None:
        """Tulis log baru + statistik yang berubah ke DB (idempoten, aman dipanggil berulang)."""
        if self.pending_logs:
            db.add_all(self.pending_logs)
            self.pending_logs = []
        for key, bucket in self.buckets.items():
            if not bucket.dirty:
                continue
            counts = {r: sum(1 for v in bucket.ranks.values() if v == r) for r in (0, 1, 2)}
            row_id = self.stat_rows.get(key)
            row = db.get(ComplianceStat, row_id) if row_id else None
            if row is None:
                row = ComplianceStat(session_id=self.session_id, bucket_start=key)
                db.add(row)
                db.flush()
                self.stat_rows[key] = row.id
            row.total_persons = len(bucket.ranks)
            row.lengkap, row.kurang_lengkap, row.tidak_digunakan = counts[0], counts[1], counts[2]
            bucket.dirty = False
        db.commit()