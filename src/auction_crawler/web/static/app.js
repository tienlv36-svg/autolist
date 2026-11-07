// Nạp danh sách xã/phường khi chọn tỉnh
(function () {
  const pv = document.getElementById('province'), wd = document.getElementById('ward');
  if (!pv || !wd) return;
  pv.addEventListener('change', async () => {
    wd.innerHTML = '';
    const first = new Option(pv.value ? 'Đang tải…' : 'Chọn tỉnh trước', '');
    wd.add(first);
    wd.disabled = !pv.value;
    if (!pv.value) return;
    try {
      const r = await fetch('/api/wards?province=' + encodeURIComponent(pv.value));
      const list = await r.json();
      first.text = 'Tất cả';
      list.forEach(w => wd.add(new Option(`${w.name} (${w.count})`, w.name)));
    } catch (e) { first.text = 'Không tải được'; }
  });
})();

// Màn hình nhỏ: thu gọn bộ lọc, hiện số điều kiện đang áp dụng
(function () {
  const d = document.querySelector('.fdetails'); if (!d) return;
  const params = [...new URLSearchParams(location.search)].filter(([k, v]) => v && !['sort', 'page'].includes(k));
  const c = d.querySelector('.fcount'); if (c && params.length) c.textContent = `(${params.length} điều kiện)`;
  if (window.matchMedia('(max-width: 820px)').matches) d.removeAttribute('open');
})();
