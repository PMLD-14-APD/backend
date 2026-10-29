from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.analysis import AnalysisSession, ComplianceStat, DetectionLog


def finalize_session(db: Session, session: AnalysisSession, status: str = "done",
                     error_message: str | None = None) -> None:
    """Tutup sesi: hitung total dari compliance_stats & detection_logs, lalu set status.
    Dipakai endpoint /stop dan bisa dipanggil juga oleh worker inferensi saat selesai/gagal.
    compliance_rate dalam persen (0-100) = orang yang APD-nya lengkap / total orang."""
    totals = (
        db.query(
            func.coalesce(func.sum(ComplianceStat.total_persons), 0),
            func.coalesce(func.sum(ComplianceStat.lengkap), 0),
        )
        .filter(ComplianceStat.session_id == session.id)
        .one()
    )
    total_persons, lengkap = int(totals[0]), int(totals[1])
    session.total_persons = total_persons
    session.total_violations = (
        db.query(func.count(DetectionLog.id)).filter(DetectionLog.session_id == session.id).scalar() or 0
    )
    session.compliance_rate = round(lengkap / total_persons * 100, 2) if total_persons else None
    session.status = status
    session.error_message = error_message
    session.finished_at = datetime.now(timezone.utc)
