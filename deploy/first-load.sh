#!/usr/bin/env bash
# =============================================================================
#  Lấy dữ liệu lần đầu - chạy các bước theo đúng thứ tự, ghi nhật ký ra data/first-load.log
#  Nên chạy trong tmux (mất vài giờ):   tmux new -s napdulieu
#     sudo -u auction bash /opt/autolist/deploy/first-load.sh
#  Tuỳ chỉnh:  DAYS=365 ENRICH_LIMIT=100000 sudo -u auction -E bash /opt/autolist/deploy/first-load.sh
#  Chạy lại được: bước đã có dữ liệu sẽ bỏ qua phần trùng.
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."
DAYS="${DAYS:-180}"                 # lấy tin dgts đăng trong N ngày gần nhất
TSC_PAGES="${TSC_PAGES:-2000}"      # số trang taisancong (20 tin/trang; ~1.800 trang = toàn bộ)
ENRICH_LIMIT="${ENRICH_LIMIT:-50000}"
SINCE="$(date -d "-${DAYS} days" +%F)"
A=.venv/bin/auction
LOG=data/first-load.log
run() {
  echo "[$(date '+%F %T')] >>> $*" | tee -a "$LOG"
  # ghi đầy đủ tiến độ (từng trang) vào nhật ký để theo dõi bằng: tail -f data/first-load.log
  "$A" "$@" > >(grep --line-buffered -vE "HTTP Request|^\s*$" | tee -a "$LOG") 2>&1
  local rc=$?
  sleep 1
  return $rc
}
must() {   # bước bắt buộc: lỗi thì dừng
  run "$@" || { echo "[$(date '+%F %T')] DỪNG: bước '$*' lỗi. Kiểm tra mạng tới dgts.moj.gov.vn / taisancong.vn" \
                "(curl -I https://dgts.moj.gov.vn) rồi chạy lại script." | tee -a "$LOG"; exit 1; }
}

echo "Lấy dữ liệu từ $SINCE | nhật ký: $LOG" | tee -a "$LOG"
must crawl -s dgts --since "$SINCE" --no-detail -p 5000       # 1. danh sách dgts (500 tin/lần)
must crawl -s taisancong --no-detail --full -p "$TSC_PAGES"    # 2. danh sách taisancong
run dedupe                                                     # 3. tin trùng giữa 2 nguồn
must re-build                                                  # 4. lọc BĐS, gom phiên -> web dùng được từ đây
run enrich -s dgts --realestate -n "$ENRICH_LIMIT"             # 5. giá, tiền đặt trước, nơi có TS (lâu nhất)
run enrich -s taisancong --realestate -n "$ENRICH_LIMIT"       # 6. chi tiết taisancong
run tag-types --since "$SINCE"                                 # 7. loại tài sản chính thức
run re-build                                                   # 8. tính lại giá phiên 1 / hiện tại / % giảm
echo "[$(date '+%F %T')] HOÀN TẤT. Bật thu thập tự động: sudo systemctl enable --now auction-scheduler" | tee -a "$LOG"
