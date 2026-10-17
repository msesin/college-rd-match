#!/usr/bin/env bash
# Daily backup of the dashboard database. Keeps 14 days.
# Cron (crontab -e):  30 3 * * * /home/ubuntu/ugs-rd-matching/deploy/backup.sh
set -euo pipefail
APP=/home/ubuntu/ugs-rd-matching
OUT=/home/ubuntu/ugs-backups
mkdir -p "$OUT"
STAMP=$(date +%Y%m%d-%H%M)
# sqlite3's online backup is safe while the site is running (a plain file copy may not be)
"$APP/.venv/bin/python" - "$APP/data/db.sqlite3" "$OUT/db-$STAMP.sqlite3" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
gzip "$OUT/db-$STAMP.sqlite3"
find "$OUT" -name 'db-*.sqlite3.gz' -mtime +14 -delete
