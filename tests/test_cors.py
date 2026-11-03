from app.core.config import parse_origins


def test_parse_origins_pisah_koma_dan_rapikan():
    assert parse_origins("http://a.com, http://b.com/ ,") == ["http://a.com", "http://b.com"]


def test_parse_origins_kosong():
    assert parse_origins("") == []
    assert parse_origins(" , ") == []


def test_parse_origins_wildcard():
    assert parse_origins("*") == ["*"]


def test_header_cors_dikirim_untuk_origin_yang_diizinkan():
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    r = c.options("/auth/login", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_origin_asing_tidak_diizinkan():
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).options("/auth/login", headers={
        "Origin": "http://evil.example",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in r.headers
