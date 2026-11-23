#!/bin/sh
set -e
alembic upgrade head
# WAJIB 1 worker: SessionRunner & stream jalan sebagai thread di proses ini.
exec uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" --workers 1 --proxy-headers
