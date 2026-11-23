"""Validasi dan penyamaran URL stream CCTV (logika murni, tanpa jaringan/database).

URL stream bisa memuat kredensial, mis. rtsp://admin:rahasia@192.168.1.10:554/stream.
Dua aturan di sini: hanya skema stream yang diizinkan (file://, path lokal, dsb. ditolak karena
URL ini dibuka langsung oleh server), dan password tidak boleh tampil di respons API maupun log.
"""
import re

ALLOWED_SCHEMES = {"rtsp", "rtsps", "http", "https"}

# parameter query yang nilainya dianggap rahasia (token/password di URL)
_SECRET_QUERY = re.compile(r"(?i)([?&;](?:password|passwd|pass|pwd|token|key|secret|auth)=)[^&#]*")


def _split_authority(rest: str) -> tuple[str, str]:
    """Pisahkan 'user:pass@host:port' dari sisa URL ('/path?query')."""
    cuts = [i for i in (rest.find(c) for c in "/?#") if i != -1]
    cut = min(cuts) if cuts else len(rest)
    return rest[:cut], rest[cut:]


def validate_stream_url(url: str) -> str:
    """Kembalikan URL yang sudah dirapikan, atau raise ValueError dengan pesan yang bisa ditampilkan."""
    url = (url or "").strip()
    if not url:
        raise ValueError("URL stream tidak boleh kosong")
    if any(ch.isspace() or ord(ch) < 32 for ch in url):
        raise ValueError("URL stream tidak boleh mengandung spasi atau karakter kontrol")

    scheme, sep, rest = url.partition("://")
    scheme = scheme.lower()
    if not sep or scheme not in ALLOWED_SCHEMES:
        raise ValueError("URL stream harus diawali rtsp://, rtsps://, http://, atau https://")

    authority, tail = _split_authority(rest)
    if "@" in tail:
        # '@' / '/' / '?' / '#' di dalam password membuat URL ambigu dan password-nya bisa bocor saat disamarkan
        raise ValueError("Karakter khusus pada username/password harus di-encode (mis. @ jadi %40, / jadi %2F)")

    hostport = authority.rpartition("@")[2]
    if not hostport or hostport.startswith(":"):
        raise ValueError("URL stream tidak memiliki alamat host")
    return f"{scheme}://{rest}"


def mask_stream_url(url):
    """Samarkan password: rtsp://admin:rahasia@10.0.0.5/s -> rtsp://admin:***@10.0.0.5/s.
    Nilai parameter query yang rahasia (token, password, dsb.) ikut disamarkan. None tetap None."""
    if url is None:
        return None
    scheme, sep, rest = url.partition("://")
    if sep:
        authority, tail = _split_authority(rest)
        if "@" in authority:
            userinfo, _, hostport = authority.rpartition("@")
            user, colon, _pw = userinfo.partition(":")
            authority = f"{user}:***@{hostport}" if colon else f"{userinfo}@{hostport}"
        url = f"{scheme}://{authority}{tail}"
    return _SECRET_QUERY.sub(r"\1***", url)

def unmask_stream_url(new: str, old) -> str:
    """URL hasil edit di FE bisa masih memuat password tersamar ('***') dari respons API.
    Kalau username-nya sama dengan URL lama, '***' diganti password lama supaya user tidak perlu
    mengetik ulang password saat hanya mengganti IP/port. Raise ValueError kalau masih ada '***'."""
    if old and "***" in new:
        n_scheme, n_sep, n_rest = new.partition("://")
        o_scheme, o_sep, o_rest = old.partition("://")
        if n_sep and o_sep:
            n_auth, n_tail = _split_authority(n_rest)
            o_auth, _ = _split_authority(o_rest)
            if "@" in n_auth and "@" in o_auth:
                n_user, _, n_host = n_auth.rpartition("@")
                o_user, _, _ = o_auth.rpartition("@")
                n_name, n_colon, n_pw = n_user.partition(":")
                o_name, o_colon, o_pw = o_user.partition(":")
                if n_pw == "***" and o_colon and n_name == o_name:
                    new = f"{n_scheme}://{n_name}:{o_pw}@{n_host}{n_tail}"
    if "***" in new:
        raise ValueError("Password/token pada URL tersamar (***). Ketik ulang password kamera")
    return new
