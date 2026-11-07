"""Kiểm tra 'sức khoẻ' selector: tải trang 1 mỗi nguồn và báo số tin + tỉ lệ field rỗng.
Chạy định kỳ để phát hiện sớm khi website đổi giao diện.   python tools/check_sources.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from auction_crawler.config import get_settings  # noqa: E402
from auction_crawler.pipeline import make_fetcher  # noqa: E402
from auction_crawler.sources import all_sources, get_source  # noqa: E402


def main() -> int:
    s = get_settings()
    bad = 0
    for name in all_sources():
        src = get_source(name)
        f = make_fetcher(s, src)
        try:
            _, items = next(iter(src.iter_pages(f, 1)), (None, []))
            items = items[:20]
            fields = list(src.cfg.get("list", {}).get("fields", {}).keys()) or [
                "title", "asset_owner", "auction_org", "auction_date", "registration_end"]
            fields = [{"registration": "registration_start"}.get(k, k) for k in fields]
            print(f"[{name}] {len(items)} tin ở trang 1")
            for k in fields:
                filled = sum(1 for it in items if it.get(k))
                pct = 100 * filled / len(items) if items else 0
                mark = "OK " if pct >= 80 else "!! "
                print(f"   {mark}{k:<15} {pct:5.1f}% có dữ liệu")
            if items and src.has_detail():
                d = src.enrich(f, items[0])
                keys = sorted(k for k, v in d.items() if v and not k.startswith("_"))
                print(f"   chi tiết tin đầu có: {keys}")
            if not items:
                bad += 1
        except Exception as e:
            bad += 1
            print(f"[{name}] LỖI: {e!r}")
        finally:
            f.close()
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
