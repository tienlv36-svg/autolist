#!/usr/bin/env bash
# =============================================================================
#  Cài đặt tự động trên VPS Ubuntu 22.04 / 24.04
#  Chạy từ thư mục mã nguồn đã clone:
#     Có tên miền :  sudo DOMAIN=hangdg.com EMAIL=ban@email.com bash deploy/install-vps.sh
#     Chưa có     :  sudo bash deploy/install-vps.sh        (truy cập https://<IP>, chứng chỉ tự ký)
#  Tên miền được ghi nhớ (data/.domain) -> lần sau cập nhật chỉ cần: sudo bash deploy/install-vps.sh
#  Chạy lại nhiều lần không sao (bỏ qua bước đã làm).
#
#  Script sẽ:
#   1. Cài gói hệ thống (python, tmux, OCR, caddy, ufw), đặt múi giờ Việt Nam
#   2. Tạo tài khoản hệ thống 'auction', chép mã nguồn vào /opt/autolist
#   3. Tạo môi trường Python + cài thư viện, chạy kiểm thử
#   4. Cấu hình chạy thật (tắt lưu trang gốc để tiết kiệm ổ cứng)
#   5. Tạo dịch vụ web + thu thập tự động (systemd), sao lưu hằng đêm
#   6. Caddy: HTTPS thật cho tên miền (Let's Encrypt) nếu DNS đã trỏ về VPS;
#      ngược lại HTTPS trên địa chỉ IP (chứng chỉ tự ký) -> https://<IP>
#   7. Tường lửa: chỉ mở SSH, 80, 443; fail2ban chặn IP dò mật khẩu SSH
#   8. Tạo tài khoản quản trị web
# =============================================================================
set -euo pipefail

APP=/opt/autolist
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER=auction
PUBLIC_IP="${PUBLIC_IP:-$(curl -fsS -4 --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')}"
HAS_SYSTEMD=0; [ -d /run/systemd/system ] && HAS_SYSTEMD=1
DOMAIN="${DOMAIN:-$(cat "$APP/data/.domain" 2>/dev/null || true)}"
DOMAIN="$(echo "$DOMAIN" | tr 'A-Z' 'a-z' | sed -E 's#^https?://##; s#/.*$##; s#^www\.##')"
EMAIL="${EMAIL:-}"

step() { echo; echo "=== $* ==="; }
[ "$(id -u)" = 0 ] || { echo "Hãy chạy bằng sudo: sudo bash deploy/install-vps.sh"; exit 1; }

step "1/8 Cài gói hệ thống"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git python3 python3-venv python3-pip tmux curl ufw \
    tesseract-ocr tesseract-ocr-vie poppler-utils sqlite3 cron rclone fail2ban >/dev/null
# fail2ban: chặn IP dò mật khẩu SSH (cấu hình mặc định của Ubuntu đã bật bảo vệ sshd)
systemctl enable --now fail2ban >/dev/null 2>&1 || true
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
mkdir -p "$APP/data" "$APP/backups" "$APP/data/files"
# Đợt 2: lịch cũ (2:00 hoặc 6 giờ/lần) -> 2 lượt/ngày 0:00 và 12:00 (chỉ đổi khi còn đúng giá trị mặc định cũ)
if grep -Eq '^  cron: "(0 2|17 \*/6) \* \* \*"' "$APP/config/settings.yaml" 2>/dev/null; then
  sed -i -E 's|^  cron: "(0 2\|17 \*/6) \* \* \*".*|  cron: "0 0,12 * * *"           # 2 lượt/ngày: 0:00 và 12:00; mỗi lượt xong tự sao lưu|' "$APP/config/settings.yaml"
fi
grep -q '^  cron: "0 0,12 \* \* \*"' "$APP/config/settings.yaml" 2>/dev/null \
  && echo "  Lịch thu thập: 0:00 và 12:00 mỗi ngày" \
  || echo "  (!) Lịch thu thập trong config/settings.yaml khác mặc định: $(grep -m1 '^  cron:' "$APP/config/settings.yaml" 2>/dev/null)"
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
# sao lưu: chạy tự động sau MỖI lượt thu thập (auction-scheduler gọi deploy/backup.sh) -> bỏ lịch cron 4:15 cũ
if crontab -u "$APP_USER" -l 2>/dev/null | grep -q 'deploy/backup.sh'; then
  crontab -u "$APP_USER" -l 2>/dev/null | grep -v 'deploy/backup.sh' | crontab -u "$APP_USER" - 2>/dev/null || true
fi
echo "  Sao lưu tự động sau mỗi lượt thu thập (0:00 và 12:00) vào $APP/backups"

resolves_here() {   # tên miền đã trỏ (bản ghi A) về đúng IP của VPS chưa?
  getent ahostsv4 "$1" 2>/dev/null | awk '{print $1}' | sort -u | grep -qx "$PUBLIC_IP"
}
MODE=ip
if [ -n "$DOMAIN" ]; then
  if resolves_here "$DOMAIN" || [ "${FORCE_DOMAIN:-0}" = 1 ]; then
    MODE=domain
  else
    echo "  (!) $DOMAIN chưa trỏ về $PUBLIC_IP (hiện: $(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u | tr '\n' ' '))"
    echo "      -> tạm dùng HTTPS trên IP. Tạo bản ghi A rồi chạy lại script sau 5-30 phút."
  fi
  echo "$DOMAIN" > "$APP/data/.domain"; chown "$APP_USER:$APP_USER" "$APP/data/.domain"
fi

if [ "$MODE" = domain ]; then
  step "6/8 Caddy – HTTPS thật (Let's Encrypt) cho $DOMAIN"
  WWW=""; resolves_here "www.$DOMAIN" && WWW="www.$DOMAIN"
else
  step "6/8 Caddy – HTTPS trên địa chỉ IP $PUBLIC_IP"
fi
if command -v caddy >/dev/null; then
  if [ "$MODE" = domain ]; then
    {
      echo "# Phần mềm đấu giá BĐS: https://$DOMAIN  (chứng chỉ Let's Encrypt, Caddy tự gia hạn)"
      [ -n "$EMAIL" ] && printf '{\n\temail %s\n}\n' "$EMAIL"
      printf '%s {\n\tencode gzip\n\trequest_body {\n\t\tmax_size 1GB\n\t}\n' "$DOMAIN"
      printf '\theader Strict-Transport-Security "max-age=31536000"\n\treverse_proxy 127.0.0.1:8000\n}\n'
      [ -n "$WWW" ] && printf '%s {\n\tredir https://%s{uri} permanent\n}\n' "$WWW" "$DOMAIN"
      true
    } > /etc/caddy/Caddyfile
  else
    {
      echo "# Truy cập: https://$PUBLIC_IP  (chứng chỉ tự ký - trình duyệt cảnh báo lần đầu, chọn \"Tiếp tục\")"
      echo "# Có tên miền: sudo DOMAIN=ten-mien.com bash deploy/install-vps.sh"
      printf '{\n\t# trình duyệt không gửi SNI khi truy cập bằng IP -> chỉ định chứng chỉ mặc định\n\tdefault_sni %s\n}\n' "$PUBLIC_IP"
      printf '%s {\n\ttls internal\n\tencode gzip\n\trequest_body {\n\t\tmax_size 1GB\n\t}\n\treverse_proxy 127.0.0.1:8000\n}\n' "$PUBLIC_IP"
    } > /etc/caddy/Caddyfile
  fi
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 \
    && echo "  Cấu hình Caddy hợp lệ" || echo "  (!) Cấu hình Caddy lỗi: caddy validate --config /etc/caddy/Caddyfile"
  if [ "$HAS_SYSTEMD" = 1 ]; then systemctl enable caddy >/dev/null 2>&1; systemctl restart caddy; echo "  caddy: $(systemctl is-active caddy)"; fi
fi
# cookie đăng nhập chỉ gửi qua HTTPS khi chạy bằng tên miền
if [ "$HAS_SYSTEMD" = 1 ]; then
  mkdir -p /etc/systemd/system/auction-web.service.d
  printf '[Service]\nEnvironment=AUCTION_COOKIE_SECURE=%s\n' "$([ "$MODE" = domain ] && echo 1 || echo 0)" \
    > /etc/systemd/system/auction-web.service.d/override.conf
  systemctl daemon-reload && systemctl restart auction-web
fi

step "7/8 Tường lửa"
if [ "$HAS_SYSTEMD" = 1 ]; then
  ufw allow OpenSSH >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null
  ufw --force enable >/dev/null && ufw status | head -8
  echo "  fail2ban: $(systemctl is-active fail2ban 2>/dev/null)"
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
if [ "$MODE" = domain ]; then
  echo " XONG. Mở trình duyệt:  https://$DOMAIN"
  echo " (lần đầu Caddy cần ~30 giây để xin chứng chỉ; nếu báo lỗi, đợi 1 phút rồi tải lại)"
else
  echo " XONG. Mở trình duyệt:  https://$PUBLIC_IP   (cảnh báo chứng chỉ là bình thường)"
fi
echo " Bước tiếp theo: lấy dữ liệu lần đầu – sudo -u auction bash $APP/deploy/first-load.sh (trong tmux)"
echo "==================================================================="
