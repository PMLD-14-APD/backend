"""Logika murni riwayat (tanpa database), supaya gampang dites."""
from datetime import datetime
from typing import Optional


def violation_label(violation_type: Optional[str], apd_names: dict[str, str]) -> str:
    """'NO_HELMET,NO_VEST' -> 'Tanpa Helm, Tanpa Rompi'.

    apd_names memetakan 'NO_<LABEL_KEY>' ke nama APD. Kalau tidak dikenal, dipakai labelnya apa adanya."""
    labels = []
    for part in (p.strip() for p in (violation_type or "").split(",")):
        if not part:
            continue
        name = apd_names.get(part) or part.removeprefix("NO_").replace("_", " ").title()
        labels.append(f"Tanpa {name}")
    return ", ".join(labels) or "-"


def duration_seconds(started_at: Optional[datetime], finished_at: Optional[datetime]) -> Optional[float]:
    """Durasi sesi dalam detik. None kalau belum mulai atau masih berjalan."""
    if started_at is None or finished_at is None:
        return None
    return round((finished_at - started_at).total_seconds(), 1)


def escape_like(text: str) -> str:
    """Supaya '%' dan '_' yang diketik pengguna dicari apa adanya, bukan dianggap wildcard."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")