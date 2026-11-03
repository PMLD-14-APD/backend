# APD Detection – Backend

REST API untuk sistem pemantauan kepatuhan Alat Pelindung Diri (APD). Dibangun dengan **FastAPI**,
**PostgreSQL** (SQLAlchemy 2 + Alembic), autentikasi **JWT**, dan pipeline inferensi **YOLO** (Ultralytics)
yang berjalan sebagai thread di dalam proses API.

Skema database mengikuti `erd_apd_revisi.drawio` (12 tabel).

## Status fitur

| Area | Status |
|---|---|
| Auth: register (pending approval), login, refresh, logout, ganti password, `/auth/me` | Selesai |
| Manajemen user admin: cari, paginasi, ubah nama/username/role, reset password, approve/reject/aktif/nonaktif/hapus | Selesai |
| Perlindungan admin terakhir (tidak bisa menonaktifkan/menghapus/menurunkan admin aktif terakhir; dikunci `FOR UPDATE`) | Selesai |
| Log aktivitas untuk admin (`/activity-logs`) dengan filter user, aksi, tipe target, pencarian, rentang tanggal | Selesai |
| Master data: lokasi (+ `camera_count`, pencarian), environment, kelas APD, model AI | Selesai |
| Sumber video: CCTV (RTSP/HTTP) dan unggah file; pencarian, filter lokasi, status live | Selesai |
| Pengamanan sumber video: hanya `rtsp/rtsps/http/https`, password disamarkan, tes koneksi saat daftar, `file_path` tidak pernah dikirim ke klien | Selesai |
| Sesi analisis: buat, start, stop, statistik per jam; sesi CCTV disambung ulang saat server restart | Selesai |
| Foto bukti pelanggaran **wajib login**, dilayani lewat `/detection-logs/{id}/image` | Selesai |
| Retensi & kuota storage, pembersihan terjadwal + manual | Selesai |
| Dashboard dan riwayat analisis | Selesai |
| CORS untuk frontend di origin/port lain | Selesai |
| Alert real-time (WebSocket) | **Belum** – butuh integrasi AI Ops |
| Video beranotasi (fitur "perbesar") | **Belum** – butuh integrasi AI Ops |

> Kode inferensi (`app/services/inference/`) sudah ada, tetapi **bobot model (`.pt`) tidak disertakan di repo**.
> Tanpa bobot dari tim AI Ops, sesi analisis akan berakhir `failed` dengan pesan
> "File bobot model tidak ditemukan".

## Prasyarat

- Python 3.11+
- PostgreSQL 14+ (database kosong bernama `apd_detection`)
- Bobot model YOLO dari tim AI Ops (letakkan di `storage/models/`)

## Instalasi

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env     # lalu isi DATABASE_URL dan SECRET_KEY
```

Linux/macOS:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Siapkan database dan data awal:

```bash
alembic upgrade head          # buat semua tabel + indeks
python seed_master_data.py    # environment "Konstruksi" + kelas helmet & vest
python create_admin.py        # buat akun admin pertama (interaktif)
python seed_demo_data.py      # opsional: data contoh untuk demo
```

Jalankan server:

```bash
uvicorn app.main:app --reload
```

- Dokumentasi interaktif (Swagger): http://localhost:8000/docs
- Health check: `GET /health`

> **Jalankan dengan satu worker uvicorn** (jangan pakai `--workers N`). Manajer inferensi, manajer stream,
> dan daftar token logout disimpan di memori proses.

## Konfigurasi (`.env`)

| Variabel | Default | Keterangan |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/apd_detection` | Koneksi PostgreSQL |
| `SECRET_KEY` | (placeholder) | **Wajib diganti** dengan string acak panjang |
| `ALGORITHM` | `HS256` | Algoritma JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Umur token = batas tidak aktif (SRS 5.2) |
| `SESSION_MAX_MINUTES` | `480` | Batas total satu sesi login walau terus di-refresh |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:5173` | Origin frontend, pisahkan dengan koma. Produksi: isi domain sebenarnya, jangan `*` |
| `UPLOAD_DIR` / `UPLOAD_EXPIRE_DAYS` / `MAX_UPLOAD_MB` | `storage/uploads` / `30` / `500` | Unggahan video |
| `STORAGE_QUOTA_MB` | `20480` | Total ukuran video unggahan yang boleh tersimpan (`0` = tanpa batas) |
| `SNAPSHOT_RETENTION_DAYS` | `90` | Foto bukti lebih tua dihapus, log tetap ada (`0` = nonaktif) |
| `HISTORY_RETENTION_DAYS` | `365` | Log pelanggaran + sesi selesai lebih tua dihapus (`0` = nonaktif) |
| `CLEANUP_INTERVAL_MINUTES` | `60` | Interval pembersihan terjadwal (`0` = nonaktif) |
| `CCTV_REGISTER_ADMIN_ONLY` | `false` | `true` = hanya admin yang boleh mendaftarkan CCTV |
| `VALIDATE_STREAM_ON_CREATE` | `true` | Uji koneksi stream sebelum disimpan (matikan di dev tanpa kamera) |
| `STREAM_PROBE_TIMEOUT_SECONDS` | `8` | Batas waktu uji koneksi |
| `MODELS_DIR` / `SNAPSHOT_DIR` | `storage/models` / `storage/snapshots` | Folder bobot model dan foto bukti |
| `PERSON_LABEL` | `person` | Nama kelas orang pada keluaran model |
| `INFERENCE_CONF` | `0.4` | Ambang confidence deteksi |
| `CONFIRM_FRAMES` | `3` | Status dianggap sah setelah N frame berturut-turut |
| `VIOLATION_COOLDOWN_SECONDS` | `30` | Jeda minimal pencatatan ulang pelanggaran orang yang sama |
| `STATS_FLUSH_SECONDS` | `10` | Seberapa sering hasil ditulis ke DB |
| `DASHBOARD_TIMEZONE` | `Asia/Jakarta` | Zona waktu pengelompokan harian/jam |

Variabel `MINIO_*` ada di konfigurasi tetapi **belum dipakai**; foto bukti saat ini disimpan di disk lokal.

## Alur pemakaian

1. Admin menyiapkan master data: lokasi, environment + kelas APD wajib, dan model AI aktif
   (`POST /ai-models/`, `weights_path` relatif terhadap `MODELS_DIR`).
2. User mendaftar (`POST /auth/register`), admin menyetujui (`POST /users/{id}/approve`).
3. User membuat sumber video: `POST /video-sources/` (CCTV) atau `POST /video-sources/upload` (file).
4. `POST /analysis-sessions/` → `/{id}/start` → `/{id}/stop`.
5. Hasil: `GET /detection-logs/?session_id=...`, `GET /analysis-sessions/{id}/stats`, dashboard, dan riwayat.

> `label_key` kelas APD harus **sama persis** dengan nama kelas keluaran model (default: `helmet`, `vest`).

## Ringkasan endpoint

Semua endpoint selain `register`, `login`, `/` dan `/health` membutuhkan header
`Authorization: Bearer <token>`. Kolom Akses: **Admin** = hanya admin, **Login** = semua user aktif
(user biasa hanya melihat data miliknya sendiri).

### Auth – `/auth`
| Method | Path | Akses | Fungsi |
|---|---|---|---|
| POST | `/register` | Publik | Daftar akun (status `pending`) |
| POST | `/login` | Publik | Login (form OAuth2), mengembalikan token + `expires_in` |
| POST | `/refresh` | Login | Tukar token yang masih berlaku dengan token baru |
| POST | `/change-password` | Login | Ganti password sendiri |
| POST | `/logout` | Login | Cabut token yang dipakai |
| GET | `/me` | Login | Profil sendiri |

### Users – `/users` (Admin)
| Method | Path | Fungsi |
|---|---|---|
| GET | `/` | Daftar user: `search`, `status`, `role`, `sort_order`, `limit`, `offset` |
| POST | `/` | Buat user langsung aktif |
| GET | `/{id}` | Detail user |
| PATCH | `/{id}` | Ubah `name`, `username`, `role`, `password` (+ `confirm_password`) |
| POST | `/{id}/approve` · `/reject` · `/deactivate` · `/activate` | Ubah status akun |
| DELETE | `/{id}` | Soft delete |

### Log aktivitas & storage (Admin)
| Method | Path | Fungsi |
|---|---|---|
| GET | `/activity-logs/` | Filter `user_id`, `action` (mis. `user.*`), `target_type`, `search`, tanggal |
| GET | `/activity-logs/actions` | Daftar aksi untuk dropdown filter |
| GET | `/storage/usage` | Pemakaian video & foto bukti, kuota, pengaturan retensi |
| POST | `/storage/cleanup` | Jalankan pembersihan sekarang |

### Master data
| Prefix | Baca (Login) | Tulis (Admin) |
|---|---|---|
| `/locations` | `GET /`, `GET /{id}` (`search`, `camera_count`) | `POST`, `PATCH /{id}`, `DELETE /{id}` |
| `/environments` | `GET /`, `GET /{id}`, `GET /{id}/apd-classes` | `POST`, `PATCH`, `DELETE`, `PUT /{id}/apd-classes`, `DELETE /{id}/apd-classes/{apd_class_id}` |
| `/apd-classes` | `GET /`, `GET /{id}` | `POST`, `PATCH /{id}`, `DELETE /{id}` |
| `/ai-models` | `GET /`, `GET /{id}` | `POST`, `PATCH /{id}`, `DELETE /{id}` |

### Video sources – `/video-sources`
| Method | Path | Fungsi |
|---|---|---|
| GET | `/` | Daftar untuk halaman Monitoring: `search` (kamera/lokasi), `location_id`, `source_type`, `status`, `live`, paginasi |
| GET | `/{id}` | Detail |
| POST | `/` | Daftarkan CCTV (URL divalidasi + diuji koneksinya) |
| POST | `/upload` | Unggah file video (`.mp4 .avi .mov .mkv .webm`) |
| PATCH | `/{id}` | Ubah nama, lokasi, FPS, status |
| DELETE | `/{id}` | Hapus sumber + sesi, log, dan foto buktinya |

### Analysis sessions – `/analysis-sessions`
| Method | Path | Fungsi |
|---|---|---|
| GET | `/` | Daftar sesi (`source_id`, `status`) |
| POST | `/` | Buat sesi (`queued`) |
| POST | `/{id}/start` · `/{id}/stop` | Mulai / hentikan analisis |
| GET | `/{id}` · `/{id}/stats` | Detail sesi / statistik kepatuhan per jam |
| GET | `/stream-status/live` | Stream dan proses inferensi yang sedang berjalan |

### Detection logs, dashboard, riwayat
| Method | Path | Fungsi |
|---|---|---|
| GET | `/detection-logs/`, `/detection-logs/{id}` | Log deteksi |
| GET | `/detection-logs/{id}/image` | Foto bukti (JPEG). Header `Authorization`, atau `?token=` untuk tag `<img>` |
| GET | `/dashboard/summary` · `/trend` · `/violations` · `/breakdown` · `/recent-violations` · `/active-sessions` | Data dashboard |
| GET | `/history/sessions` · `/history/violations` · `/history/violations/{id}` | Riwayat analisis |

## Keamanan

- **Password** di-hash dengan bcrypt (panjang 8–72 karakter).
- **Sesi 30 menit tidak aktif**: token berumur `ACCESS_TOKEN_EXPIRE_MINUTES`. Frontend memanggil
  `POST /auth/refresh` saat ada aktivitas; jika diam lebih lama, token mati dan harus login ulang.
  Total umur sesi dibatasi `SESSION_MAX_MINUTES`.
- **Logout** mencabut token (`jti`) lewat denylist **di memori**: hilang saat server restart dan tidak dibagi antar worker.
- **Akun nonaktif/dihapus/ditolak**: token langsung tidak berlaku.
- **URL stream**: skema selain `rtsp/rtsps/http/https` (mis. `file://`) ditolak; password dan parameter rahasia
  (`token`, `password`, dst.) disamarkan di respons API. Karakter khusus di password harus di-encode (`@` → `%40`).
- **Foto bukti** tidak dilayani sebagai file statis dan dilindungi dari path traversal.
- **Otorisasi data**: user biasa hanya melihat sumber video, sesi, dan log miliknya; admin melihat semua.

## Retensi & storage

Pembersihan berjalan terjadwal (`CLEANUP_INTERVAL_MINUTES`) dan bisa dipicu admin lewat `POST /storage/cleanup`:

- Video unggahan kedaluwarsa (`UPLOAD_EXPIRE_DAYS`) dihapus beserta sesi, log, dan fotonya.
- Foto bukti lebih tua dari `SNAPSHOT_RETENTION_DAYS` dihapus (log tetap ada).
- Log pelanggaran, statistik, dan sesi selesai lebih tua dari `HISTORY_RETENTION_DAYS` dihapus.
- File/folder yatim di disk dibersihkan.
- Kuota `STORAGE_QUOTA_MB` menghitung **video unggahan** saja. Foto bukti dikendalikan lewat retensi
  dan dapat dipantau di `GET /storage/usage`.

## Pengujian

```bash
pip install pytest httpx
pytest
```

Tes memakai SQLite in-memory dan folder sementara, jadi tidak butuh PostgreSQL maupun model AI.

## Struktur proyek

```
app/
  api/        # router: auth, users, activity_logs, master_data, video_sources,
              #         analysis_sessions, detection_logs, dashboard, history, storage_admin
  core/       # config, database, security (JWT, denylist), timeutils
  models/     # model SQLAlchemy (12 tabel)
  schemas/    # skema Pydantic
  services/   # logika bisnis: users, history, retention, stream_*, inference/
  storage/    # penyimpanan lokal: unggahan video dan foto bukti
alembic/      # migrasi database
tests/        # pytest
create_admin.py · seed_master_data.py · seed_demo_data.py · reset_db.py
```

## Reset database (development)

```bash
python reset_db.py
alembic upgrade head
```

## Keterbatasan yang diketahui

- Denylist logout, manajer inferensi, dan manajer stream ada di memori: gunakan **satu worker**.
- Foto bukti masih di disk lokal; integrasi MinIO belum ada (kolom `image_url` sudah siap).
- Alert real-time (WebSocket) dan video beranotasi belum ada; keduanya bergantung pada keluaran AI Ops.
- `CCTV_REGISTER_ADMIN_ONLY` default `false` (mengikuti ERD). Set `true` jika pendaftaran CCTV harus dibatasi admin.