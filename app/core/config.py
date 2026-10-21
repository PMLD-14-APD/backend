from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/apd_detection"

    # JWT auth
    secret_key: str = "ganti-ini-di-env-jangan-dipakai-buat-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8  # 8 jam

    # MinIO / object storage
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "apd-violations"

    class Config:
        env_file = ".env"


settings = Settings()