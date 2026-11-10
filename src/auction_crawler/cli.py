"""Giao diện dòng lệnh: `auction --help`."""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .config import DEFAULT_CRON, get_settings
from .sources import all_sources, get_source
from .storage import Repository

app = typer.Typer(help="Thu thập, phân loại & thống kê tin đấu giá tài sản", no_args_is_help=True)
console = Console()


def _setup() -> tuple:
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(message)s", handlers=[RichHandler(console=console, show_path=False)])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    repo = Repository(s.resolved_db_url)
    repo.init_db()
    return s, repo


def _d(v: Optional[str]) -> Optional[date]:
    return datetime.strptime(v, "%Y-%m-%d").date() if v else None


@app.command("sources")
def sources_cmd():
    """Liệt kê các nguồn đã cấu hình."""
    for n in all_sources():
        src = get_source(n)
        console.print(f"[bold]{n}[/] - {src.cfg.get('label', '')} | mode={src.mode} fetcher={src.cfg.get('fetcher', 'http')}")


@app.command("init-db")
def init_db():
    """Tạo bảng cơ sở dữ liệu."""
    s, _ = _setup()
    console.print(f"[green]OK[/] {s.resolved_db_url}")


@app.command()
def crawl(
    source: list[str] = typer.Option(None, "--source", "-s", help="Tên nguồn (mặc định: tất cả)"),
    max_pages: int = typer.Option(None, "--max-pages", "-p"),
    no_detail: bool = typer.Option(False, "--no-detail", help="Chỉ lấy danh sách, không vào trang chi tiết"),
    full: bool = typer.Option(False, "--full", help="Quét lại toàn bộ (không dừng ở tin đã có)"),
    since: str = typer.Option(None, "--since", help="Chỉ lấy tin từ ngày YYYY-MM-DD (backfill theo khoảng)"),
):
    """Thu thập tin đăng từ các nguồn.

    Ví dụ: backfill nhanh 1 năm chỉ danh sách: auction crawl -s dgts --since 2025-11-01 --no-detail -p 2000
    rồi bổ sung chi tiết dần: auction enrich -s dgts --limit 5000"""
    from .pipeline import crawl_source

    s, repo = _setup()
    failed = []
    for name in source or all_sources():
        try:
            st = crawl_source(name, s, repo, max_pages=max_pages, fetch_detail=not no_detail, full=full,
                              since=_d(since))
            console.print(f"[green]{name}[/]: trang={st.pages} tìm={st.found} mới={st.inserted} "
                          f"cập nhật={st.updated} không đổi={st.unchanged} lỗi={st.errors}")
        except Exception as e:
            failed.append(name)
            console.print(f"[red]{name} thất bại:[/] {e}")
    if failed:
        raise typer.Exit(1)   # mã lỗi để script / lịch chạy biết có nguồn thất bại


@app.command()
def enrich(source: str = typer.Option(..., "--source", "-s"), limit: int = typer.Option(1000, "--limit", "-n"),
           since: str = typer.Option(None, "--since"),
           realestate: bool = typer.Option(False, "--realestate", help="Chỉ tin BĐS (sau re-build), ưu tiên nhiều phiên")):
    """Tải chi tiết (giá, tiền đặt trước, nơi có TS...) cho tin đã có nhưng chưa có chi tiết."""
    from .pipeline import enrich_missing

    s, repo = _setup()
    st = enrich_missing(source, s, repo, limit=limit, since=_d(since), realestate=realestate)
    console.print(f"[green]{source}[/]: xử lý={st.found} cập nhật={st.updated} lỗi={st.errors}")


@app.command("ocr-prices")
def ocr_prices_cmd(source: str = typer.Option("taisancong", "--source", "-s"),
                   limit: int = typer.Option(50, "--limit", "-n"), since: str = typer.Option(None, "--since"),
                   keep_pdf: bool = typer.Option(False, "--keep-pdf", help="Lưu PDF vào data/raw/<nguồn>/pdf")):
    """Đọc giá khởi điểm/tiền đặt trước từ PDF đính kèm (OCR tiếng Việt) cho tin chưa có giá."""
    from .ocr import ocr_available
    from .pipeline import ocr_prices

    if not ocr_available():
        console.print("[yellow]Chưa có tesseract/pdftoppm - chỉ đọc được PDF có lớp chữ.[/] "
                      "Cài: apt-get install -y tesseract-ocr tesseract-ocr-vie poppler-utils")
    s, repo = _setup()
    st = ocr_prices(source, s, repo, limit=limit, since=_d(since), keep_pdf=keep_pdf)
    console.print(f"[green]{source}[/]: xử lý={st.found} có giá={st.updated} lỗi={st.errors}")


@app.command("tag-types")
def tag_types(since: str = typer.Option(None, "--since")):
    """dgts: gắn loại tài sản chính thức (16 loại theo Luật ĐGTS) cho tin trong DB."""
    from .pipeline import tag_official_types

    s, repo = _setup()
    res = tag_official_types(s, repo, _d(since))
    for k, v in sorted(res.items(), key=lambda x: -x[1]):
        console.print(f"{v:>8,}  {k[:100]}")


@app.command()
def dedupe(threshold: float = typer.Option(0.35, help="Ngưỡng trùng từ tên tài sản (0-1)")):
    """Đánh dấu tin cùng một cuộc đấu giá đăng ở nhiều nguồn (thống kê sẽ không đếm trùng)."""
    from .dedupe import find_duplicates

    _, repo = _setup()
    console.print(f"Đã đánh dấu {find_duplicates(repo, threshold)} tin thuộc nhóm trùng")


@app.command()
def probe(url: str, out: Path = typer.Option(Path("data/probe"), help="Thư mục lưu HTML")):
    """Tải 1 URL (HTTP thường), lưu HTML và gợi ý selector / phân trang / API.
    Trang render bằng JS: dùng `python tools/probe_browser.py <url>`."""
    from .http_client import Fetcher
    from .inspector import analyze_html

    s = get_settings()
    f = Fetcher(s, "probe")
    html = f.get_html(url)
    f.close()
    out.mkdir(parents=True, exist_ok=True)
    fn = out / (re.sub(r"[^\w]+", "_", url)[-80:] + ".html")
    fn.write_text(html, encoding="utf-8")
    console.print(f"Đã lưu: {fn}")
    console.print_json(json.dumps(analyze_html(html, url), ensure_ascii=False))


@app.command("test-selectors")
def test_selectors(source: str, html_file: Path, detail: bool = typer.Option(False, "--detail", "-d"),
                   url: str = typer.Option(None, help="URL gốc để ghép link tương đối")):
    """Chạy selector của nguồn trên file HTML đã lưu (không cần mạng)."""
    from .pipeline import build_notice
    from .classifier import RuleClassifier

    src = get_source(source)
    if src.mode == "api" and not detail:
        console.print(f"[yellow]{source} dùng API JSON - không parse HTML danh sách.[/] Thử: auction crawl -s {source} -p 1")
        raise typer.Exit()
    html = html_file.read_text(encoding="utf-8")
    base = url or src.cfg["list"]["url"]
    if detail:
        data = (src.parse_detail_html(html) if hasattr(src, "parse_detail_html")  # type: ignore[attr-defined]
                else src.parse_detail(html, base))
        console.print_json(json.dumps(data, ensure_ascii=False))
        n = build_notice(source, {"source_id": "test", "title": data.get("asset_name", ""), **data}, RuleClassifier())
        console.print_json(n.model_dump_json(exclude={"raw", "content"}))
        return
    items = src.parse_list(html, base)
    t = Table(title=f"{len(items)} tin")
    cols = ["source_id", *src.cfg["list"].get("fields", {}).keys()]
    for c in cols:
        t.add_column(c, overflow="fold", max_width=40)
    for it in items[:30]:
        t.add_row(*[str(it.get(c) or "") for c in cols])
    console.print(t)


@app.command()
def stats(date_from: str = typer.Option(None, "--from"), date_to: str = typer.Option(None, "--to"),
          source: str = typer.Option(None, "--source", "-s")):
    """In bảng thống kê nhanh ra màn hình."""
    from .stats import load_df, summary

    _, repo = _setup()
    df = load_df(repo, _d(date_from), _d(date_to), source)
    console.print(f"Tổng số tin: [bold]{len(df)}[/]")
    for name, tbl in summary(df).items():
        if tbl.empty or name.startswith("Top") or " x " in name:
            continue
        t = Table(title=name)
        for c in tbl.columns:
            t.add_column(str(c), justify="right" if tbl[c].dtype.kind in "if" else "left")
        for row in tbl.head(20).itertuples(index=False):
            t.add_row(*[f"{v:,.0f}" if isinstance(v, (int, float)) and v == v else str(v) for v in row])
        console.print(t)


@app.command()
def export(fmt: str = typer.Option("xlsx", "--format", "-f", help="xlsx | csv"),
           date_from: str = typer.Option(None, "--from"), date_to: str = typer.Option(None, "--to"),
           source: str = typer.Option(None, "--source", "-s"), out: Path = typer.Option(None, "--out", "-o")):
    """Xuất dữ liệu + thống kê ra Excel/CSV."""
    from .stats import export_csv, export_excel, load_df

    s, repo = _setup()
    df = load_df(repo, _d(date_from), _d(date_to), source)
    out = out or s.path(s.export_dir) / f"dau_gia_{datetime.now():%Y%m%d_%H%M}.{fmt}"
    path = export_excel(df, out) if fmt == "xlsx" else export_csv(df, out)
    console.print(f"[green]Đã xuất {len(df)} tin:[/] {path}")


@app.command("eval-classify")
def eval_classify(sample: int = typer.Option(15, "--sample", "-n"), dim: str = typer.Option("asset_type"),
                  code: str = typer.Option("khac", help="Mã nhóm cần soát mẫu")):
    """Phân bố kết quả phân loại + in mẫu tin của một nhóm (mặc định 'khac') để bổ sung từ khoá."""
    from sqlalchemy import func, select

    from .classifier import RuleClassifier
    from .storage import NoticeRow

    _, repo = _setup()
    clf = RuleClassifier()
    col = getattr(NoticeRow, dim)
    with repo.session() as ss:
        total = ss.scalar(select(func.count(NoticeRow.id))) or 1
        rows = ss.execute(select(col, func.count()).group_by(col).order_by(func.count().desc())).all()
        t = Table(title=f"Phân bố {dim} ({total:,} tin)")
        for c in ("Mã", "Nhãn", "Số tin", "%"):
            t.add_column(c)
        for c, n in rows:
            t.add_row(str(c), clf.label_of(dim, c), f"{n:,}", f"{100 * n / total:.1f}")
        console.print(t)
        for r in ss.scalars(select(NoticeRow).where(col == code).order_by(func.random()).limit(sample)):
            console.print(f"[dim]{r.source}[/] {r.title[:150]} [dim]| {(r.asset_owner or '')[:60]}[/]")


@app.command("re-build")
def re_build():
    """Lọc tin BĐS, trích diện tích/tờ-thửa/phường, gom các phiên đấu giá thành tài sản."""
    import time

    from .realestate.linker import rebuild

    _, repo = _setup()
    t = time.time()
    st = rebuild(repo)
    console.print(f"BĐS: {st['notices']:,} thông báo -> {st['properties']:,} tài sản "
                  f"(mới {st['created']:,}, gộp {st['merged']:,}) trong {time.time() - t:.0f}s")


@app.command("telegram-setup")
def telegram_setup(token: str = typer.Option(..., "--token", help="Token bot lấy từ @BotFather"),
                   chat_id: str = typer.Option(None, "--chat-id", help="Bỏ trống để tự tìm nhóm vừa thêm bot")):
    """Cài thông báo Telegram: kiểm tra token, tìm nhóm chat, lưu cấu hình (data/telegram.json), gửi tin thử."""
    from .notify import discover_chats, get_me, save_config, send

    s = get_settings()
    try:
        me = get_me(token)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]Token không hợp lệ:[/] {e}")
        raise typer.Exit(1)
    console.print(f"Bot: [bold]@{me.get('username')}[/]")
    if not chat_id:
        chats = discover_chats(token)
        groups = [c for c in chats if c["type"] in ("group", "supergroup", "channel")] or chats
        if not groups:
            console.print("[yellow]Chưa thấy nhóm nào.[/] Thêm bot vào nhóm Telegram, gửi tin [bold]/start[/] trong nhóm, "
                          "rồi chạy lại lệnh này.")
            raise typer.Exit(1)
        if len(groups) > 1:
            console.print("Bot đang ở nhiều cuộc trò chuyện – chạy lại kèm --chat-id <ID>:")
            for c in groups:
                console.print(f"  {c['id']:>16}  {c['type']:<10} {c['name']}")
            raise typer.Exit(1)
        chat_id = groups[0]["id"]
        console.print(f"Nhóm: [bold]{groups[0]['name']}[/] (id {chat_id})")
    p = save_config(s, token, chat_id)
    if send(s, "✅ <b>Đấu giá BĐS</b>: đã kết nối thông báo Telegram. Báo cáo sẽ gửi sau mỗi lượt thu thập."):
        console.print(f"[green]Đã lưu cấu hình ({p}) và gửi tin thử vào nhóm.[/]")
    else:
        console.print("[red]Đã lưu cấu hình nhưng gửi tin thử lỗi[/] – kiểm tra bot còn trong nhóm.")
        raise typer.Exit(1)


@app.command()
def notify(text: str = typer.Argument(..., help="Nội dung (cho phép thẻ HTML <b>, <i>)")):
    """Gửi một tin nhắn Telegram (dùng trong script, vd sao lưu)."""
    from .notify import send

    if not send(get_settings(), text):
        console.print("[yellow]Chưa cấu hình Telegram hoặc gửi lỗi[/]")
        raise typer.Exit(1)


@app.command("telegram-test")
def telegram_test():
    """Gửi tin thử tới nhóm Telegram đã cấu hình."""
    from .notify import send

    ok = send(get_settings(), "🔔 Tin thử từ <b>Đấu giá BĐS</b> – thông báo hoạt động bình thường.")
    console.print("[green]Đã gửi[/]" if ok else "[red]Chưa cấu hình hoặc gửi lỗi[/]")
    raise typer.Exit(0 if ok else 1)


@app.command("history-scan")
def history_scan(limit: int = typer.Option(500, "--limit", "-n")):
    """Quét lịch sử giá (phiên cũ) cho tài sản CÒN HẠN đăng ký, rồi gom phiên lại."""
    from .realestate.history import scan_open_properties
    from .realestate.linker import rebuild

    s, repo = _setup()
    st = scan_open_properties(s, repo, limit=limit)
    if st.found_notices:
        rebuild(repo)
    console.print(f"Quét {st.scanned} tài sản còn hạn: thêm {st.found_notices} thông báo cũ cho "
                  f"{st.props_updated} tài sản, lỗi {st.errors}")


@app.command("docs-fetch")
def docs_fetch(minutes: float = typer.Option(300, "--minutes", "-m", help="Giới hạn thời gian (phút)"),
               limit: int = typer.Option(100_000, "--limit", "-n", help="Tối đa N tin"),
               max_disk: float = typer.Option(85, "--max-disk", help="Dừng khi ổ cứng đã dùng >= %")):
    """Tải, LƯU và đọc file đính kèm của tin BĐS (còn hạn đăng ký trước), rồi gom phiên lại
    (số liệu trong tài liệu được ưu tiên). Chạy lâu -> dùng tmux."""
    from .attachments import fetch_docs
    from .realestate.linker import rebuild
    from .scheduler import run_lock

    s, repo = _setup()
    with run_lock(s):
        st = fetch_docs(s, repo, minutes=minutes, limit=limit, max_disk_pct=max_disk,
                        ocr_max_pages=int(s.schedule.get("ocr_max_pages", 30)))
        if st.notices:
            rebuild(repo)
    console.print(f"Đọc {st.notices} tin, lưu {st.files} file ({st.bytes / 1048576:.0f} MB), OCR {st.ocr_files}, "
                  f"có số liệu {st.with_info}, lỗi {st.errors}" + (f" – {st.stopped}" if st.stopped else "")
                  + (f"; {st.details[-1]}" if st.details else ""))


@app.command("docs-reparse")
def docs_reparse():
    """Trích lại thông số từ chữ đã lưu của file đính kèm (không tải lại), rồi gom phiên lại."""
    from .attachments import reparse
    from .realestate.linker import rebuild
    from .scheduler import run_lock

    s, repo = _setup()
    with run_lock(s):
        n = reparse(repo, s)
        rebuild(repo)
    console.print(f"Đã trích lại {n} tin")


@app.command("run-now")
def run_now():
    """Chạy ngay một lượt như lịch tự động (thu thập + gom phiên + báo Telegram)."""
    from .scheduler import run_once

    s, repo = _setup()
    rep = run_once(s, repo)
    console.print(rep["text"])


@app.command("user-add")
def user_add(username: str, full_name: str = typer.Option(..., "--name", "-n"),
             admin: bool = typer.Option(False, "--admin"),
             password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True)):
    """Tạo tài khoản đăng nhập ứng dụng web (tài khoản đầu tiên nên là --admin)."""
    from sqlalchemy import select

    from .realestate.db import User
    from .web.auth import hash_password

    _, repo = _setup()
    with repo.Session.begin() as s:
        if s.scalar(select(User).where(User.username == username.lower())):
            console.print("[red]Tên đăng nhập đã tồn tại[/]")
            raise typer.Exit(1)
        s.add(User(username=username.lower(), full_name=full_name, password_hash=hash_password(password),
                   role="admin" if admin else "member"))
    console.print(f"[green]Đã tạo[/] {username} ({'quản trị' if admin else 'thành viên'})")


@app.command()
def web(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(8000), reload: bool = False):
    """Chạy ứng dụng web quản lý tài sản BĐS (mặc định http://127.0.0.1:8000)."""
    import uvicorn

    _setup()
    # proxy_headers: lấy IP thật của người dùng từ Caddy (chỉ tin proxy chạy trên cùng máy)
    uvicorn.run("auction_crawler.web.app:create_app", factory=True, host=host, port=port, reload=reload,
                proxy_headers=True, forwarded_allow_ips="127.0.0.1")


@app.command()
def reclassify():
    """Phân loại lại toàn bộ DB sau khi sửa config/categories.yaml."""
    from .pipeline import reclassify_all

    _, repo = _setup()
    console.print(f"Đã phân loại lại {reclassify_all(repo)} tin")


@app.command()
def schedule(cron: str = typer.Option(None, help="Biểu thức cron, mặc định lấy từ settings.yaml")):
    """Chạy định kỳ (tiến trình chạy nền liên tục)."""
    from .scheduler import run_scheduler

    s, repo = _setup()
    run_scheduler(s, repo, cron or s.schedule.get("cron", DEFAULT_CRON))


if __name__ == "__main__":
    app()
