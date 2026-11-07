#!/usr/bin/env bash
# =============================================================================
#  Cài đặt tự động trên VPS Ubuntu 22.04 / 24.04 (chưa cần tên miền)
#  Chạy từ thư mục mã nguồn đã clone:   sudo bash deploy/install-vps.sh
#  Chạy lại nhiều lần không sao (bỏ qua bước đã làm).
#
#  Script sẽ:
#   1. Cài gói hệ thống (python, tmux, OCR, caddy, ufw), đặt múi giờ Việt Nam
#   2. Tạo tài khoản hệ thống 'auction', chép mã nguồn vào /opt/autolist
#   3. Tạo môi trường Python + cài thư viện, chạy kiểm thử
#   4. Cấu hình chạy thật (tắt lưu trang gốc để tiết kiệm ổ cứng)
#   5. Tạo dịch vụ web + thu thập tự động (systemd), sao lưu hằng đêm
#   6. Caddy: HTTPS trên địa chỉ IP (chứng chỉ tự ký) -> https://<IP>
#   7. Tường lửa: chỉ mở SSH, 80, 443
#   8. Tạo tài khoản quản trị web
# =============================================================================
set -euo pipefail

APP=/opt/autolist
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER=auction
PUBLIC_IP="${PUBLIC_IP:-$(curl -fsS -4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')}"
HAS_SYSTEMD=0; [ -d /run/systemd/system ] && HAS_SYSTEMD=1

step() { echo; echo "=== $* ==="; }
[ "$(id -u)" = 0 ] || { echo "Hãy chạy bằng sudo: sudo bash deploy/install-vps.sh"; exit 1; }

step "1/8 Cài gói hệ thống"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git python3 python3-venv python3-pip tmux curl ufw \
    tesseract-ocr tesseract-ocr-vie poppler-utils sqlite3 cron >/dev/null
if ! command -v caddy >/dev/null; then
  apt-get install -y -q caddy >/dev/null 2>&1 || echo "  (!) Không cài được caddy từ kho Ubuntu – xem https://caddyserver.com/docs/install"
fi
timedatectl set-timezone Asia/Ho_Chi_Minh 2>/dev/null || ln -sf /usr/share/zoneinfo/Asia/Ho_Chi_Minh /etc/localtime

step "2/8 Tài khoản hệ thống & mã nguồn"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /bin/bash "$APP_USER"
mkdir -p "$APP"
if [ "$SRC" != "$APP" ]; then
  # chép mã nguồn (kể cả .git để sau này 'git pull'); không ghi đè dữ liệu đã có
  KEEP=(); [ -f "$APP/config/settings.yaml" ] && KEEP=(--exclude=./config/settings.yaml)   # giữ cấu hình đã chỉnh
  tar -C "$SRC" --exclude=./data --exclude=./.venv --exclude=./backups "${KEEP[@]}" -cf - . | tar -C "$APP" -xf -
fi
mkdir -p "$APP/data" "$APP/backups"
chown -R "$APP_USER:$APP_USER" "$APP"
git config --system --add safe.directory "$APP" 2>/dev/null || true

step "3/8 Môi trường Python & thư viện"
sudo -u "$APP_USER" bash -c "cd $APP && [ -d .venv ] || python3 -m venv .venv"
sudo -u "$APP_USER" bash -c "cd $APP && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -e '.[ocr,dev]'"
sudo -u "$APP_USER" bash -c "cd $APP && .venv/bin/pytest -q 2>&1 | tail -1"

step "4/8 Cấu hình chạy thật"
CFG="$APP/config/settings.yaml"
if grep -q '^raw_cache_dir: data/raw' "$CFG"; then
  sed -i 's|^raw_cache_dir: data/raw.*|raw_cache_dir: ""                # tắt lưu trang gốc (tiết kiệm ổ cứng)|' "$CFG"
fi
sudo -u "$APP_USER" "$APP/.venv/bin/auction" init-db >/dev/null

step "5/8 Dịch vụ chạy nền & sao lưu"
if [ "$HAS_SYSTEMD" = 1 ]; then
  cp "$APP/deploy/auction-web.service" "$APP/deploy/auction-scheduler.service" /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable auction-web >/dev/null 2>&1
  systemctl restart auction-web                      # áp dụng mã nguồn mới khi chạy lại script để cập nhật
  if systemctl is-enabled auction-scheduler >/dev/null 2>&1; then systemctl restart auction-scheduler; fi
  # Thu thập tự động: bật sau khi đã lấy dữ liệu lần đầu (xem hướng dẫn) -> systemctl enable --now auction-scheduler
  echo "  auction-web: $(systemctl is-active auction-web) | auction-scheduler: $(systemctl is-active auction-scheduler 2>/dev/null)"
else
  echo "  (!) Máy không dùng systemd – bỏ qua tạo dịch vụ"
fi
CRON="15 2 * * * $APP/deploy/backup.sh >> $APP/backups/backup.log 2>&1"
( crontab -u "$APP_USER" -l 2>/dev/null | grep -v 'deploy/backup.sh' ; echo "$CRON" ) | crontab -u "$APP_USER" - 2>/dev/null \
  && echo "  Sao lưu tự động 2:15 mỗi đêm vào $APP/backups" || echo "  (!) Chưa đặt được lịch sao lưu (thiếu cron)"

step "6/8 Caddy – HTTPS trên địa chỉ IP $PUBLIC_IP"
if command -v caddy >/dev/null; then
  cat > /etc/caddy/Caddyfile <<EOF
# Truy cập: https://$PUBLIC_IP  (chứng chỉ tự ký - trình duyệt cảnh báo lần đầu, chọn "Tiếp tục")
# Khi có tên miền: xem docs/HUONG_DAN_VPS.md mục "Khi có tên miền"
{
	# trình duyệt không gửi SNI khi truy cập bằng IP -> chỉ định chứng chỉ mặc định
	default_sni $PUBLIC_IP
}
$PUBLIC_IP {
	tls internal
	encode gzip
	request_body {
		max_size 1GB
	}
	reverse_proxy 127.0.0.1:8000
}
EOF
  if [ "$HAS_SYSTEMD" = 1 ]; then systemctl enable caddy >/dev/null 2>&1; systemctl restart caddy; echo "  caddy: $(systemctl is-active caddy)"; fi
fi

step "7/8 Tường lửa"
if [ "$HAS_SYSTEMD" = 1 ]; then
  ufw allow OpenSSH >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null
  ufw --force enable >/dev/null && ufw status | head -8
fi

step "8/8 Tài khoản quản trị web"
if sudo -u "$APP_USER" "$APP/.venv/bin/python" -c "
import sqlite3,sys; c=sqlite3.connect('$APP/data/auction.db')
sys.exit(0 if c.execute(\"select count(*) from users where role='admin'\").fetchone()[0] else 1)" 2>/dev/null; then
  echo "  Đã có tài khoản quản trị – bỏ qua"
elif [ -t 0 ]; then
  read -rp "  Tên đăng nhập quản trị [admin]: " U; U=${U:-admin}
  read -rp "  Họ tên: " N; N=${N:-Quản trị viên}
  sudo -u "$APP_USER" bash -c "cd $APP && .venv/bin/auction user-add '$U' --name '$N' --admin"
else
  echo "  Tạo sau bằng: sudo -u $APP_USER $APP/.venv/bin/auction user-add admin --name 'Quản trị viên' --admin"
fi

echo
echo "==================================================================="
echo " XONG. Mở trình duyệt:  https://$PUBLIC_IP"
echo " Bước tiếp theo: lấy dữ liệu lần đầu (docs/HUONG_DAN_VPS.md, Bước 6)"
echo "==================================================================="
