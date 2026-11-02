import uuid

import pytest
from pydantic import ValidationError

from app.schemas.user import UserCreate, UserUpdate
from app.services.users import leaves_no_active_admin


def test_admin_terakhir_terdeteksi():
    a = uuid.uuid4()
    assert leaves_no_active_admin([a], a) is True


def test_masih_ada_admin_lain():
    a, b = uuid.uuid4(), uuid.uuid4()
    assert leaves_no_active_admin([a, b], a) is False


def test_tidak_ada_admin_aktif_sama_sekali():
    assert leaves_no_active_admin([], uuid.uuid4()) is True


def test_create_konfirmasi_password_harus_sama():
    with pytest.raises(ValidationError):
        UserCreate(name="A", username="abc", password="rahasia123", confirm_password="beda12345")
    u = UserCreate(name="A", username="ABC", password="rahasia123", confirm_password="rahasia123")
    assert u.username == "abc"


def test_update_password_butuh_konfirmasi():
    with pytest.raises(ValidationError):
        UserUpdate(password="rahasia123")
    with pytest.raises(ValidationError):
        UserUpdate(password="rahasia123", confirm_password="salah12345")
    with pytest.raises(ValidationError):
        UserUpdate(confirm_password="rahasia123")
    assert UserUpdate(password="rahasia123", confirm_password="rahasia123").password == "rahasia123"


def test_update_field_wajib_tidak_boleh_null():
    for field in ("name", "username", "role"):
        with pytest.raises(ValidationError):
            UserUpdate(**{field: None})


def test_update_normalisasi():
    u = UserUpdate(name="  Budi  ", username="BUDI_1")
    assert u.name == "Budi" and u.username == "budi_1"
    assert u.model_dump(exclude_unset=True) == {"name": "Budi", "username": "budi_1"}
    with pytest.raises(ValidationError):
        UserUpdate(name="   ")