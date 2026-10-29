from datetime import date, datetime, timedelta, timezone

from app.core.timeutils import day_bounds
from app.services.history import duration_seconds, escape_like, violation_label

APD = {"NO_HELMET": "Helm", "NO_VEST": "Rompi"}


# ---------------------------------------------------------------- label pelanggaran
def test_label_satu_apd():
    assert violation_label("NO_HELMET", APD) == "Tanpa Helm"


def test_label_beberapa_apd():
    assert violation_label("NO_HELMET,NO_VEST", APD) == "Tanpa Helm, Tanpa Rompi"


def test_label_apd_tak_dikenal_memakai_labelnya():
    assert violation_label("NO_SAFETY_GLOVES", APD) == "Tanpa Safety Gloves"


def test_label_kosong():
    assert violation_label("", APD) == "-" and violation_label(None, APD) == "-"


# ---------------------------------------------------------------- durasi
def test_durasi_sesi():
    mulai = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
    assert duration_seconds(mulai, mulai + timedelta(hours=2, seconds=30)) == 7230.0


def test_durasi_none_kalau_belum_mulai_atau_masih_berjalan():
    t = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
    assert duration_seconds(None, t) is None
    assert duration_seconds(t, None) is None


# ---------------------------------------------------------------- pencarian aman
def test_escape_like_wildcard_dicari_apa_adanya():
    assert escape_like("100%") == "100\\%"
    assert escape_like("gudang_1") == "gudang\\_1"
    assert escape_like("a\\b") == "a\\\\b"


# ---------------------------------------------------------------- batas tanggal
def test_day_bounds_tanpa_batas():
    assert day_bounds(None, None) == (None, None)


def test_day_bounds_satu_sisi():
    start, end = day_bounds(date(2026, 10, 9), None)
    assert start is not None and end is None
    start, end = day_bounds(None, date(2026, 10, 9))
    assert start is None and end is not None


def test_day_bounds_tanggal_akhir_ikut_dihitung_dan_zona_lokal():
    start, end = day_bounds(date(2026, 10, 9), date(2026, 10, 11))
    assert end - start == timedelta(days=3)
    assert start.utcoffset() == timedelta(hours=7)          # Asia/Jakarta


def test_pelanggaran_pagi_hari_masuk_tanggalnya_sendiri():
    start, end = day_bounds(date(2026, 10, 9), date(2026, 10, 9))
    jam_6_pagi_wib = datetime(2026, 10, 8, 23, 0, tzinfo=timezone.utc)      # = 06:00 WIB tanggal 9
    assert start <= jam_6_pagi_wib < end
    tengah_malam_sebelumnya = datetime(2026, 10, 8, 16, 59, tzinfo=timezone.utc)   # = 23:59 WIB tanggal 8
    assert not (start <= tengah_malam_sebelumnya < end)