from datetime import date, datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.config import settings


def local_tz() -> ZoneInfo:
    return ZoneInfo(settings.dashboard_timezone)


def day_bounds(date_from: Optional[date], date_to: Optional[date]) -> tuple[Optional[datetime], Optional[datetime]]:
    """Ubah rentang tanggal LOKAL menjadi batas waktu [awal, akhir); tanggal `date_to` ikut dihitung penuh.
    Salah satu boleh kosong, artinya tidak ada batas di sisi itu.

    Di database waktu disimpan dalam UTC. Pelanggaran pukul 06:00 WIB tanggal 9 tersimpan sebagai
    23:00 UTC tanggal 8, jadi tanpa konversi ini ia akan masuk filter tanggal 8."""
    tz = local_tz()
    start = datetime.combine(date_from, time.min, tzinfo=tz) if date_from else None
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz) if date_to else None
    return start, end