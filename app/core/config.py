from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/apd_detection"
    # Dashboard: zona waktu untuk pengelompokan harian/jam
    dashboard_timezone: str = "Asia/Jakarta"
   
    # JWT auth
    secret_key: str = "ganti-ini-di-env-jangan-dipakai-buat-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30      # SRS 5.2: sesi tidak aktif 30 menit harus divalidasi ulang (lewat /auth/refresh)
    session_max_minutes: int = 60 * 8          # batas total satu sesi login (diperpanjang lewat refresh), lewat itu wajib login ulang

    # MinIO / object storage
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "apd-violations"

    # Penyimpanan file video unggahan (lokal)
    upload_dir: str = "storage/uploads"
    upload_expire_days: int = 30
    max_upload_mb: int = 500
    storage_quota_mb: int = 20480              # total ukuran video unggahan yang boleh tersimpan (0 = tanpa batas)

    # Retensi & pembersihan terjadwal (0 = nonaktif)
    snapshot_retention_days: int = 90          # foto bukti lebih tua dari ini dihapus (log pelanggarannya tetap ada)
    history_retention_days: int = 365          # log pelanggaran + sesi selesai lebih tua dari ini dihapus
    cleanup_interval_minutes: int = 60         # seberapa sering pembersihan berjalan

    # Sumber CCTV
    cctv_register_admin_only: bool = False     # True = hanya admin yang boleh mendaftarkan CCTV (default: ikut ERD, semua user)
    validate_stream_on_create: bool = True     # uji koneksi stream sebelum disimpan (matikan di dev tanpa kamera)
    stream_probe_timeout_seconds: int = 8

    # Inferensi AI
    models_dir: str = "storage/models"        # folder bobot model (weights_path relatif ke sini)
    snapshot_dir: str = "storage/snapshots"   # foto bukti pelanggaran (sementara lokal, belum MinIO)
    person_label: str = "person"              # nama kelas orang di keluaran model
    inference_conf: float = 0.4               # ambang confidence deteksi
    confirm_frames: int = 3                   # status baru dianggap sah setelah N frame berturut-turut
    violation_cooldown_seconds: int = 30      # jeda minimal pencatatan ulang pelanggaran orang yang sama
    stats_flush_seconds: int = 10             # seberapa sering hasil ditulis ke DB
    class Config:
        env_file = ".env"
settings = Settings()