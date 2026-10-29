# APD Detection - Backend

FastAPI + PostgreSQL (SQLAlchemy 2, Alembic). Skema database mengikuti `erd_apd_revisi.drawio` (12 tabel).

## Menjalankan (Windows PowerShell)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env        # lalu isi DATABASE_URL dan SECRET_KEY
# buat database PostgreSQL: apd_detection

alembic upgrade head          # buat 12 tabel
python seed_master_data.py    # environment "Konstruksi" + kelas helmet & vest
python create_admin.py        # buat akun admin

uvicorn app.main:app --reload
```

Dokumentasi API: http://localhost:8000/docs

## Alur pemakaian

1. Admin: tambah AI model untuk environment (`POST /ai-models/`), lokasi bila perlu.
2. User: buat sumber video, yaitu `POST /video-sources/` (CCTV) atau `POST /video-sources/upload` (file; kedaluwarsa 30 hari).
3. `POST /analysis-sessions/` lalu `/{id}/start` dan `/{id}/stop`.
4. Hasil: `GET /detection-logs/?session_id=...` dan `GET /analysis-sessions/{id}/stats`.

## Reset database (development)

```powershell
python reset_db.py
alembic upgrade head
```

## Belum ada

Worker inferensi AI (membaca frame, menjalankan model, mengisi `detection_logs`, `detection_log_items`,
`compliance_stats`) belum ada di repo ini. Fungsi `app.services.analysis.finalize_session` siap dipakai worker tersebut.
Upload snapshot ke MinIO juga belum (kolom `image_url` sudah ada).
