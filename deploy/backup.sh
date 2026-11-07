#!/usr/bin/env bash
# Sao lưu CSDL (an toàn khi đang chạy) + file tải lên + khoá cookie. Giữ 14 bản gần nhất.
# Dùng: deploy/backup.sh [thư_mục_đích]     (mặc định /opt/autolist/backups)
# Cron hằng đêm:  15 2 * * * /opt/autolist/deploy/backup.sh >> /opt/autolist/backups/backup.log 2>&1
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$APP_DIR/backups}"
KEEP="${KEEP:-14}"
STAMP="$(date +%Y%m%d_%H%M)"
mkdir -p "$DEST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
"$APP_DIR/.venv/bin/python" - "$APP_DIR/data/auction.db" "$TMP/auction.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1], timeout=60)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
PY
tar -czf "$DEST/autolist_$STAMP.tar.gz" -C "$TMP" auction.db -C "$APP_DIR/data" media secret.key 2>/dev/null \
  || tar -czf "$DEST/autolist_$STAMP.tar.gz" -C "$TMP" auction.db
ls -1t "$DEST"/autolist_*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "$(date '+%F %T') OK $DEST/autolist_$STAMP.tar.gz ($(du -h "$DEST/autolist_$STAMP.tar.gz" | cut -f1))"
