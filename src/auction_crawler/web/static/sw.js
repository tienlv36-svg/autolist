// Service worker: cho phép "cài" web lên màn hình điện thoại. Trang luôn lấy mới từ máy chủ (dữ liệu thay đổi
// liên tục, có đăng nhập); chỉ lưu sẵn CSS/JS/biểu tượng và một trang báo mất mạng.
const CACHE = "hangdg-v1";
const STATIC = ["/static/app.css?v=1", "/static/app.js?v=1", "/static/icon-192.png", "/offline"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(STATIC)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    e.respondWith(caches.match(req).then(r => r || fetch(req)));
  } else if (req.mode === "navigate") {
    e.respondWith(fetch(req).catch(() => caches.match("/offline")));
  }
});
