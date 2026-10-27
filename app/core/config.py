from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/apd_detection"
    # Dashboard: zona waktu untuk pengelompokan harian/jam
    dashboard_timezone: str = "Asia/Jakarta"
   
    # JWT auth
    secret_key: str = "ganti-ini-di-env-jangan-dipakai-buat-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8  # 8 jam

    # MinIO / object storage
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "apd-violations"

    # Penyimpanan file video unggahan (lokal)
    upload_dir: str = "storage/uploads"
    upload_expire_days: int = 30
    max_upload_mb: int = 500

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