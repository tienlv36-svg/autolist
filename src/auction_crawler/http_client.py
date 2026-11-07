"""HTTP fetcher có retry, giãn cách request, lưu cache HTML gốc; và fetcher trình duyệt (Playwright)."""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import Settings

log = logging.getLogger(__name__)

RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


class Fetcher:
    """Fetcher HTTP thuần (nhanh, nhẹ). Dùng cho trang render phía server hoặc API JSON."""

    def __init__(self, settings: Settings, source: str, transport: httpx.BaseTransport | None = None,
                 http_overrides: dict | None = None):
        self.s = settings
        # cấu hình http riêng của nguồn (vd delay_seconds, concurrency) ghi đè cấu hình chung
        self.http = settings.http.model_copy(update=http_overrides or {})
        self.source = source
        self._last = 0.0
        self._lock = threading.Lock()
        self.client = httpx.Client(
            timeout=self.http.timeout,
            verify=self.http.verify_tls,
            limits=httpx.Limits(max_connections=max(4, self.http.concurrency * 2)),
            follow_redirects=True,
            headers={"User-Agent": self.http.user_agent, "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.5"},
            transport=transport,
        )
        self.cache_dir = settings.path(settings.raw_cache_dir) / source if settings.raw_cache_dir else None

    def _throttle(self) -> None:
        """Giới hạn tốc độ dùng chung cho mọi luồng: tối thiểu delay_seconds giữa 2 lần bắt đầu request."""
        with self._lock:
            slot = max(time.monotonic(), self._last + self.http.delay_seconds)
            self._last = slot
        wait = slot - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _save_raw(self, key: str, body: str, ext: str) -> None:
        if not self.cache_dir:
            return
        d = self.cache_dir / date.today().isoformat()
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{hashlib.md5(key.encode()).hexdigest()}.{ext}").write_text(body, encoding="utf-8")

    def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        @retry(
            stop=stop_after_attempt(self.http.max_retries),
            wait=wait_exponential(multiplier=2, min=2, max=30),
            retry=retry_if_exception_type(RETRYABLE),
            reraise=True,
        )
        def _do() -> httpx.Response:
            self._throttle()
            r = self.client.request(method, url, **kw)
            if r.status_code >= 500 or r.status_code == 429:
                r.raise_for_status()
            return r

        r = _do()
        log.debug("%s %s -> %s", method, r.url, r.status_code)
        return r

    def get_html(self, url: str, params: dict | None = None) -> str:
        r = self.request("GET", url, params=params)
        r.raise_for_status()
        text = r.text
        self._save_raw(str(r.url), text, "html")
        return text

    def get_json(self, url: str, method: str = "GET", params: dict | None = None, json: Any = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        r = self.request(method, url, params=params if method == "GET" else None,
                         json=json if method != "GET" else None,
                         headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"})
        r.raise_for_status()
        self._save_raw(f"{r.url}{json}", r.text, "json")
        return r.json()

    def close(self) -> None:
        self.client.close()


class BrowserFetcher(Fetcher):
    """Fetcher dùng Chromium (Playwright) cho trang render bằng JavaScript.
    Cài: pip install -e .[browser] && playwright install chromium"""

    def __init__(self, settings: Settings, source: str, wait_selector: str | None = None,
                 http_overrides: dict | None = None):
        super().__init__(settings, source, http_overrides=http_overrides)
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("Cần cài playwright: pip install -e .[browser] && playwright install chromium") from e
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._page = self._browser.new_page(user_agent=self.http.user_agent, locale="vi-VN")
        self.wait_selector = wait_selector

    def get_html(self, url: str, params: dict | None = None) -> str:
        if params:
            url = str(httpx.URL(url, params=params))
        self._throttle()
        self._page.goto(url, wait_until="networkidle", timeout=self.http.timeout * 1000)
        if self.wait_selector:
            self._page.wait_for_selector(self.wait_selector, timeout=15000)
        html = self._page.content()
        self._save_raw(url, html, "html")
        return html

    def close(self) -> None:
        super().close()
        self._browser.close()
        self._pw.stop()
