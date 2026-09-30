from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/apd_detection"

    # MinIO / object storage (dipakai nanti pas integrasi upload gambar pelanggaran)
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "apd-violations"

    class Config:
        env_file = ".env"


settings = Settings()
