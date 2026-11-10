#!/usr/bin/env bash
# Sao lưu CSDL (an toàn khi đang chạy) + file tải lên + cấu hình (khoá cookie, Telegram, tên miền).
# Giữ 14 bản trên VPS; nếu đã cấu hình Google Drive (rclone remote "gdrive") thì đẩy thêm lên Drive,
# giữ 30 ngày. Lỗi -> báo Telegram. Trạng thái lần gần nhất ghi vào data/.last_backup.json.
# Dùng: deploy/backup.sh [thư_mục_đích]     (mặc định /opt/autolist/backups)
# Tự chạy sau MỖI lượt thu thập (0:00 và 12:00) – do auction-scheduler gọi.
# File đính kèm đã lưu (data/files, có thể rất lớn) KHÔNG nằm trong bản sao lưu nén; nếu có file data/.drive_files
# thì được đồng bộ dần (chỉ phần mới) lên Google Drive: <remote>:autolist-files/
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$APP_DIR/backups}"
KEEP="${KEEP:-28}"      # 2 lượt/ngày -> 14 ngày
REMOTE="${RCLONE_REMOTE:-gdrive}"
REMOTE_DIR="${RCLONE_DIR:-autolist-backups}"
REMOTE_DAYS="${RCLONE_KEEP_DAYS:-30}"
STAMP="$(date +%Y%m%d_%H%M)"
FILE="$DEST/autolist_$STAMP.tar.gz"
A="$APP_DIR/.venv/bin/auction"
mkdir -p "$DEST"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
trap '"$A" notify "❌ <b>Sao lưu lỗi</b> lúc $(date "+%H:%M %d/%m") – xem $DEST/backup.log" >/dev/null 2>&1 || true' ERR

"$APP_DIR/.venv/bin/python" - "$APP_DIR/data/auction.db" "$TMP/auction.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1], timeout=60)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close()
PY

EXTRA=()
for f in media secret.key telegram.json .domain; do [ -e "$APP_DIR/data/$f" ] && EXTRA+=("$f"); done
if [ ${#EXTRA[@]} -gt 0 ]; then
  tar -czf "$FILE" -C "$TMP" auction.db -C "$APP_DIR/data" "${EXTRA[@]}"
else
  tar -czf "$FILE" -C "$TMP" auction.db
fi
ls -1t "$DEST"/autolist_*.tar.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
SIZE="$(du -h "$FILE" | cut -f1)"

OFFSITE=false
if command -v rclone >/dev/null && rclone listremotes 2>/dev/null | grep -qx "$REMOTE:"; then
  rclone copy "$FILE" "$REMOTE:$REMOTE_DIR/" --retries 3
  rclone delete "$REMOTE:$REMOTE_DIR/" --min-age "${REMOTE_DAYS}d" --include "autolist_*.tar.gz" || true
  OFFSITE=true
  if [ -f "$APP_DIR/data/.drive_files" ] && [ -d "$APP_DIR/data/files" ]; then
    rclone copy "$APP_DIR/data/files" "$REMOTE:autolist-files/" --retries 3 --transfers 2 || echo "(!) đồng bộ file đính kèm lỗi"
  fi
fi

printf '{"at": "%s", "file": "%s", "size": "%s", "offsite": %s}\n' \
  "$(date '+%F %T')" "$(basename "$FILE")" "$SIZE" "$OFFSITE" > "$APP_DIR/data/.last_backup.json"
echo "$(date '+%F %T') OK $FILE ($SIZE) offsite=$OFFSITE"
