from datetime import date

import pytest
from fastapi import HTTPException

from app.api.dashboard import DashboardFilters, rate


def make(date_from=None, date_to=None):
    return DashboardFilters(date_from, date_to, None, None, None)


def test_default_7_hari_terakhir():
    f = make()
    assert (f.date_to - f.date_from).days == 6


def test_date_to_ikut_dihitung_penuh():
    f = make(date(2026, 10, 1), date(2026, 10, 3))
    assert (f.end - f.start).days == 3


def test_rentang_terbalik_ditolak():
    with pytest.raises(HTTPException) as e:
        make(date(2026, 10, 5), date(2026, 10, 1))
    assert e.value.status_code == 422


def test_rentang_terlalu_panjang_ditolak():
    with pytest.raises(HTTPException):
        make(date(2024, 1, 1), date(2026, 1, 1))


def test_rate():
    assert rate(7, 10) == 70.0
    assert rate(1, 3) == 33.33
    assert rate(0, 0) is None