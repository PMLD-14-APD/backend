#!/bin/sh
# Backup harian DB (container simovis-db) + foto bukti.
# Crontab:  0 2 * * * /path/ke/BE_V2/deploy/backup.sh >> $HOME/simovis-backup/backup.log 2>&1
# Restore:  docker compose exec -T db pg_restore -U simovis -d apd_detection_v2 --clean --no-owner < FILE.dump
set -e
cd "$(dirname "$0")"
DEST=${BACKUP_DIR:-$HOME/simovis-backup}
mkdir -p "$DEST/db"
docker compose exec -T db pg_dump -U simovis -Fc apd_detection_v2 > "$DEST/db/apd_$(date +%F).dump"
find "$DEST/db" -name 'apd_*.dump' -mtime +14 -delete
rsync -a ../storage/snapshots/ "$DEST/snapshots/"
echo "[$(date '+%F %T')] backup ok"
# Opsional ke Google Drive:  rclone sync "$DEST" gdrive:simovis-backup
