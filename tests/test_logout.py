import time
import uuid

from jose import jwt

from app.core import security
from app.core.config import settings


def setup_function():
    security._revoked.clear()


def test_token_punya_jti_unik():
    sub = str(uuid.uuid4())
    a = jwt.decode(security.create_access_token({"sub": sub}), settings.secret_key, algorithms=[settings.algorithm])
    b = jwt.decode(security.create_access_token({"sub": sub}), settings.secret_key, algorithms=[settings.algorithm])
    assert a["jti"] and b["jti"] and a["jti"] != b["jti"]


def test_token_dicabut_ditolak():
    security.revoke_token("abc", time.time() + 60)
    assert security.is_revoked("abc") is True


def test_token_lain_tidak_terpengaruh():
    security.revoke_token("abc", time.time() + 60)
    assert security.is_revoked("xyz") is False
    assert security.is_revoked(None) is False


def test_entri_kedaluwarsa_dibuang():
    security.revoke_token("lama", time.time() - 1)
    assert security.is_revoked("lama") is False
    security.revoke_token("baru", time.time() + 60)
    assert "lama" not in security._revoked


def test_get_token_payload_menolak_token_logout():
    import pytest
    from fastapi import HTTPException

    token = security.create_access_token({"sub": str(uuid.uuid4())})
    payload = security.get_token_payload(token)
    security.revoke_token(payload["jti"], payload["exp"])
    with pytest.raises(HTTPException) as e:
        security.get_token_payload(token)
    assert e.value.status_code == 401