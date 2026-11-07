"""Dò trang bằng trình duyệt thật (Playwright): render JS, chụp màn hình, lưu HTML
và GHI LẠI MỌI REQUEST XHR/FETCH trả JSON -> tìm API ẩn phía sau trang danh sách.

Cài:  pip install -e .[browser] && playwright install chromium
Chạy: python tools/probe_browser.py https://dgts.moj.gov.vn/thong-bao-cong-khai-viec-dau-gia.html
      python tools/probe_browser.py <url> --click "text=2"   # bấm sang trang 2 để xem request phân trang
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from auction_crawler.inspector import analyze_html  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default="data/probe")
    ap.add_argument("--click", action="append", default=[], help="Selector Playwright để bấm (vd 'text=2', '.pagination a >> nth=1')")
    ap.add_argument("--wait", type=int, default=3000, help="ms chờ sau khi tải")
    ap.add_argument("--headed", action="store_true", help="Hiện cửa sổ trình duyệt")
    a = ap.parse_args()

    from playwright.sync_api import sync_playwright

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^\w]+", "_", a.url)[-60:]
    captured: list[dict] = []

    def on_response(resp):
        req = resp.request
        if req.resource_type not in ("xhr", "fetch"):
            return
        entry = {"method": req.method, "url": resp.url, "status": resp.status,
                 "post_data": req.post_data, "content_type": resp.headers.get("content-type", "")}
        try:
            if "json" in entry["content_type"]:
                body = resp.json()
                entry["json_preview"] = json.dumps(body, ensure_ascii=False)[:1500]
        except Exception:
            pass
        captured.append(entry)

    with sync_playwright() as pw:
        br = pw.chromium.launch(headless=not a.headed)
        page = br.new_page(locale="vi-VN", viewport={"width": 1366, "height": 900})
        page.on("response", on_response)
        page.goto(a.url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(a.wait)
        snaps = [("p1", page.content())]
        page.screenshot(path=str(out / f"{slug}_p1.png"), full_page=True)
        for i, sel in enumerate(a.click, start=2):
            print(f"-> bấm {sel!r}")
            page.click(sel)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(a.wait)
            snaps.append((f"p{i}", page.content()))
            print(f"   URL hiện tại: {page.url}")
        br.close()

    for tag, html in snaps:
        fn = out / f"{slug}_{tag}.html"
        fn.write_text(html, encoding="utf-8")
        print(f"Đã lưu {fn}")
    (out / f"{slug}_xhr.json").write_text(json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Phân tích HTML (sau render) ===")
    print(json.dumps(analyze_html(snaps[0][1], a.url), ensure_ascii=False, indent=2))
    print(f"\n=== {len(captured)} request XHR/fetch (chi tiết: {slug}_xhr.json) ===")
    for c in captured:
        flag = "JSON" if "json_preview" in c else "    "
        print(f"[{flag}] {c['method']} {c['status']} {c['url'][:150]}")
        if c.get("post_data"):
            print(f"         body: {c['post_data'][:200]}")
    print("\nGợi ý: nếu thấy request JSON chứa danh sách tin -> đặt mode: api trong config/sources/<nguồn>.yaml")


if __name__ == "__main__":
    main()
