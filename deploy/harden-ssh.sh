#!/usr/bin/env bash
# =============================================================================
#  Bảo mật SSH: chỉ cho đăng nhập bằng KHOÁ SSH, tắt đăng nhập bằng mật khẩu.
#  Chạy:  sudo bash /root/autolist/deploy/harden-ssh.sh
#
#  AN TOÀN: script TỪ CHỐI chạy nếu /root/.ssh/authorized_keys chưa có khoá nào
#  (tránh tự khoá mình ở ngoài). Hãy thêm khoá & thử đăng nhập bằng khoá TRƯỚC.
#  Hoàn tác:  sudo bash /root/autolist/deploy/harden-ssh.sh --undo
#  Lỡ bị khoá ngoài: Portal Vietnix -> VPS -> Open Xterm.js Console -> chạy lệnh hoàn tác.
# =============================================================================
set -euo pipefail
CONF=/etc/ssh/sshd_config.d/10-autolist-harden.conf
[ "$(id -u)" = 0 ] || { echo "Chạy bằng sudo"; exit 1; }

reload_ssh() { sshd -t && (systemctl reload ssh 2>/dev/null || systemctl reload sshd); }

if [ "${1:-}" = "--undo" ]; then
  rm -f "$CONF" && reload_ssh && echo "Đã hoàn tác: đăng nhập bằng mật khẩu được bật lại."
  exit 0
fi

KEYS=/root/.ssh/authorized_keys
N=$(grep -cE '^(ssh-(ed25519|rsa)|ecdsa-sha2-|sk-)' "$KEYS" 2>/dev/null || true)
if [ "${N:-0}" -lt 1 ]; then
  echo "DỪNG: $KEYS chưa có khoá SSH nào."
  echo "Làm theo hướng dẫn 'Bước 2 – Đăng nhập bằng khoá SSH' trước, thử đăng nhập bằng khoá thành công rồi mới chạy lại."
  exit 1
fi
echo "Tìm thấy $N khoá trong $KEYS:"
awk '{print "  - " $1 " ... " $NF}' "$KEYS"

cat > "$CONF" <<CFG
# Tạo bởi autolist/deploy/harden-ssh.sh – chỉ đăng nhập bằng khoá SSH
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CFG
reload_ssh
echo
echo "XONG: SSH chỉ còn nhận đăng nhập bằng khoá."
echo "QUAN TRỌNG: GIỮ NGUYÊN cửa sổ này, mở PowerShell MỚI và thử:  ssh root@<IP>"
echo "  - Vào được KHÔNG hỏi mật khẩu -> hoàn tất."
echo "  - Không vào được -> quay lại cửa sổ này chạy:  sudo bash $0 --undo"
