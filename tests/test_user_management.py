import pytest
from pydantic import ValidationError

from app.schemas.auth import PasswordChange
from app.schemas.user import UserUpdate


def test_update_kosong_tidak_punya_field():
    assert UserUpdate().model_dump(exclude_unset=True) == {}


def test_hanya_field_yang_dikirim_yang_tercatat():
    assert UserUpdate(name="Budi").model_dump(exclude_unset=True) == {"name": "Budi"}


def test_username_dinormalisasi_huruf_kecil():
    assert UserUpdate(username="  Budi.S ").username == "budi.s"


def test_username_karakter_tidak_valid_ditolak():
    with pytest.raises(ValidationError):
        UserUpdate(username="budi santoso")


def test_nama_hanya_spasi_ditolak():
    with pytest.raises(ValidationError):
        UserUpdate(name="   ")


def test_password_terlalu_pendek_ditolak():
    with pytest.raises(ValidationError):
        UserUpdate(password="short")


def test_peran_tidak_dikenal_ditolak():
    with pytest.raises(ValidationError):
        UserUpdate(role="superadmin")


def test_ganti_password_baru_minimal_8():
    with pytest.raises(ValidationError):
        PasswordChange(old_password="lama", new_password="pendek")
    assert PasswordChange(old_password="lama", new_password="barubaru1").new_password == "barubaru1"