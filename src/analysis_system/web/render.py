"""Dựng HTML cho dashboard. Không quyết định gì, chỉ trình bày.

Viết thẳng bằng chuỗi thay vì dùng thư viện template, vì một thư viện template
là một phụ thuộc và đây là bốn trang. Nếu lớn hơn thế thì nên dùng Jinja chứ
không phải viết thêm kiểu này.

Mọi thứ đến từ dữ liệu đều đi qua `safe()` trước. Mã lần chạy, tên cột, câu
nhận định — tất cả đều từ bên ngoài vào, và một trang dán chúng vào mà không
thoát ký tự là một trang chạy bất cứ thứ gì dữ liệu bảo nó chạy.
"""

from __future__ import annotations

from html import escape
from typing import Any, Final

import pandas as pd

from analysis_system.api import GateReport, ServiceError, Workspace
from analysis_system.services import retention
from analysis_system.services.column_names import would_change
from analysis_system.services.direct_answer import plainly, refusals
from analysis_system.services.findings import was_repaired
from analysis_system.services.retention import RunInfo
from analysis_system.services.svg_chart import chart_for, pairs_from
from analysis_system.services.updater import Update, Version
from analysis_system.web.naming import ROUND_MARK
from analysis_system.web.state import (
    dataset_status,
    forecast_values,
    pending_count,
    round_has_result,
    round_status,
)
from analysis_system.web.state import (
    split_rounds as shared_split_rounds,
)
from analysis_system.web.tree import Node

STYLE = """
:root { color-scheme: light dark; --line: #8883; --dim: #8888; }
* { box-sizing: border-box; }
body { font: 15px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0;
       padding: 1.5rem; max-width: 62rem; margin-inline: auto; }
h1 { font-size: 1.3rem; margin: 0 0 .3rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .7rem; }
h3 { font-size: .95rem; margin: 1.2rem 0 .4rem; }
a { color: inherit; }
.top { display: flex; justify-content: space-between; align-items: baseline;
       border-bottom: 1px solid var(--line); padding-bottom: .8rem; margin-bottom: 1.5rem; }
.muted { color: var(--dim); font-size: .9rem; }
.err { color: #c0392b; }
.ok { color: #1e8449; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; }
th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--line); }
th { font-weight: 600; font-size: .8rem; text-transform: uppercase; color: var(--dim); }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.scroll { overflow-x: auto; border: 1px solid var(--line); border-radius: .4rem; }
.card { border: 1px solid var(--line); border-radius: .5rem; padding: 1rem;
        margin-bottom: 1rem; }
.card.wait { border-color: #d68910; }
.tag { font-size: .75rem; padding: .1rem .5rem; border-radius: 1rem;
       border: 1px solid var(--line); white-space: nowrap; }
.tag.wait { border-color: #d68910; color: #d68910; }
.tag.ok { border-color: #1e8449; color: #1e8449; }
form.stack { display: grid; gap: .5rem; }
/* O tich KHONG duoc keo gian.  ap ca len checkbox lam no gian het
   dong va roi lech han sang phai, cach xa cai nhan no thuoc ve - nguoi dung
   nhin thay mot o tich lo lung khong biet cua muc nao. */
input[type=checkbox], input[type=radio] { width: auto; padding: 0; margin-right: .4rem; }
input, textarea, select { width: 100%; padding: .5rem; font: inherit;
                          border: 1px solid var(--line); border-radius: .3rem;
                          background: transparent; color: inherit; }
textarea { min-height: 4.5rem; resize: vertical; }
button { padding: .5rem 1.1rem; font: inherit; cursor: pointer; border-radius: .3rem;
         border: 1px solid var(--line); background: transparent; color: inherit; }
button.go { border-color: #1e8449; color: #1e8449; font-weight: 600; }
label { font-size: .85rem; color: var(--dim); }
ul { padding-left: 1.2rem; margin: .3rem 0; }
li { margin: .2rem 0; }
img { max-width: 100%; border: 1px solid var(--line); border-radius: .4rem; }
.qa { border-left: 3px solid var(--line); padding-left: .9rem; margin: 1.2rem 0; }
.qa .q { font-weight: 600; }
.drop { border: 2px dashed var(--line); border-radius: .5rem; padding: 1.5rem;
        text-align: center; }
code { font-size: .85em; background: #8881; padding: .1rem .3rem; border-radius: .2rem; }
.with-aside { display: grid; grid-template-columns: 15rem minmax(0, 1fr); gap: 2rem;
              align-items: start; }
/* Khong co dong nay thi mot cai bang rong day ca cot phai ra ngoai man hinh:
   o mac dinh, mot o cua grid khong co nho hon noi dung cua no. */
.with-aside > main { min-width: 0; }
.aside { position: sticky; top: 1rem; font-size: .88rem; }
.aside ul { list-style: none; padding-left: .8rem; margin: .2rem 0;
            border-left: 1px solid var(--line); }
.aside > ul { padding-left: 0; border-left: 0; }
.aside a { text-decoration: none; display: block; padding: .18rem .3rem; border-radius: .25rem; }
.aside a:hover { background: #8881; }
.aside a.here { background: #8882; font-weight: 600; }
.aside .no { color: var(--dim); font-variant-numeric: tabular-nums; }
/* Thanh dieu huong chinh. Chu to hon cay viec ben duoi vi no la muc tren,
   va co mot vach ngan de hai tang khong doc lien thanh mot. */
.aside ul.nav { font-size: 1rem; padding-left: 0; border-left: 0;
  margin: 0 0 1.2rem; padding-bottom: 1rem; border-bottom: 1px solid var(--line); }
.aside ul.nav a { padding: .35rem .5rem; }
.claim { border: 1px solid var(--line); border-radius: .5rem; padding: .8rem 1rem;
         margin-bottom: .8rem; }
.claim .more { margin-top: .6rem; }
.claim .more summary { cursor: pointer; color: var(--dim); font-size: .85rem; }
/* Ten he thong, va la duong ve trang dau. Nho hon tieu de trang vi no la
   chi dan, khong phai noi dung. */
.brand { display: block; font-size: .8rem; letter-spacing: .08em;
  text-transform: uppercase; color: var(--dim); text-decoration: none; }
.brand:hover { text-decoration: underline; }
/* Cau tra loi thang. To hon phan con lai vi no la thu duy nhat nhieu
   nguoi doc, va vien trai de mat nhan ra ngay day khong phai mot muc nua. */
/* Bon loai bieu do, chon theo hinh dang chi so chu khong theo y thich. */
.donut { display: flex; align-items: center; gap: 1.2rem; flex-wrap: wrap; }
.donut .legend { font-size: .85rem; line-height: 1.9; }
.donut .key { display: inline-block; width: .7rem; height: .7rem;
  border-radius: .15rem; margin-right: .4rem; vertical-align: middle; }
.big { padding: .6rem 0; }
.big .figure { font-size: 2.4rem; font-weight: 600; line-height: 1.1;
  font-variant-numeric: tabular-nums; }
.lead { font-size: 1.05rem; line-height: 1.6; border-left: 3px solid currentColor; }
.claim .more form { margin-top: .5rem; }
details.gaps summary { cursor: pointer; color: var(--dim); font-size: .9rem; }
.spin { display: inline-block; width: .85em; height: .85em; margin-right: .45em;
        border: 2px solid var(--line); border-top-color: currentColor;
        border-radius: 50%; vertical-align: -.1em; animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation-duration: 3s; } }
@media (max-width: 52rem) {
  .with-aside { grid-template-columns: 1fr; }
  .aside { position: static; border-bottom: 1px solid var(--line); padding-bottom: .8rem; }
}
/* Nut noi thu/mo thanh dieu huong, dat o dau cot trai - ngay duoi hang
   brand/title. No la phan tu dau cua cot nav (cot nay dinh vi tri khi cuon),
   nen bam duoc moi luc ma khong che mat noi dung dang doc. */
.nav-toggle {
  display: inline-grid; place-items: center;
  width: 2.2rem; height: 2.2rem; padding: 0;
  margin: 0 0 .7rem; font-size: 1rem; line-height: 1;
  cursor: pointer; border: 1px solid var(--line); border-radius: 50%;
  background: transparent; color: inherit;
}
.nav-toggle:hover { background: #8881; }
/* Hai ky hieu xep cung mot o cua luoi; chi mot cai hien tai mot thoi diem. */
.nav-toggle .tat, .nav-toggle .mo { grid-area: 1 / 1; }
.nav-toggle .mo { display: none; }
/* Thu gon: an moi thu trong cot tru nut, va thu cot lai dung be rong nut de
   noi dung chiem het cho con lai. */
.nav-off .nav-toggle .tat { display: none; }
.nav-off .nav-toggle .mo { display: block; }
.nav-off .aside > :not(.nav-toggle) { display: none; }
.nav-off .with-aside { grid-template-columns: auto minmax(0, 1fr); gap: .7rem; }
@media (max-width: 52rem) {
  /* Tren man hinh nho moi thu da xep mot cot: thu gon chi an danh sach,
     noi dung van nam duoi nut, khong sang ngang. */
  .nav-off .with-aside { grid-template-columns: 1fr; }
  .nav-off .aside { padding-bottom: 0; border-bottom: 0; }
}
"""


def safe(value: Any) -> str:
    """Bất cứ thứ gì, dưới dạng văn bản không thể trở thành mã."""
    return escape(str(value), quote=True)


SPINNER: Final[str] = "<span class=spin aria-hidden=true></span>"


# Tên hệ thống. Một chỗ duy nhất, vì nó hiện trên mọi trang và trên trang đăng
# nhập - hai chỗ viết khác nhau thì người dùng tưởng là hai hệ thống.
SYSTEM_NAME: Final[str] = "Analysis System"


def page(
    title: str,
    body: str,
    subtitle: str = "",
    aside: str = "",
    refresh: int = 0,
    here: str = "",
    collapsible: bool = False,
) -> str:
    """Một trang, trong cùng một khung với mọi trang khác.

    `aside` là cây việc bên trái. Trang nào không có cây thì vẫn chiếm trọn bề
    ngang như cũ, nên trang đăng nhập và trang lỗi không phải biết gì về nó.

    `collapsible` bật cho các trang chính: thêm một nút ở đầu cột trái để thu
    thanh điều hướng lại cho nội dung rộng ra, và mở lại khi cần. Trạng thái
    ghi nhớ trong trình duyệt, nên chuyển trang giữa các trang chính vẫn giữ.
    Các trang chi tiết giữ nguyên: đang làm việc với một bộ dữ liệu thì cây
    việc là bản đồ, không phải thứ để dấu đi.
    """
    toggle = (
        '<button class=nav-toggle type=button aria-pressed=false title="Thu thanh điều hướng">'
        "<span class=tat aria-hidden=true>◀</span>"
        "<span class=mo aria-hidden=true>▶</span>"
        "</button>"
        if collapsible
        else ""
    )
    script = (
        """<script>
(function () {
  var nav = localStorage.getItem("asys.nav") === "off";
  var btn = document.querySelector(".nav-toggle");
  if (nav) document.body.classList.add("nav-off");
  if (btn) btn.setAttribute("aria-pressed", nav ? "true" : "false");
  document.body.addEventListener("click", function (ev) {
    var hit = ev.target.closest ? ev.target.closest(".nav-toggle") : null;
    if (!hit) return;
    var off = document.body.classList.toggle("nav-off");
    localStorage.setItem("asys.nav", off ? "off" : "on");
    hit.setAttribute("aria-pressed", off ? "true" : "false");
  });
})();
</script>"""
        if collapsible
        else ""
    )
    # Tên hệ thống, và nó là đường về trang đầu. Vào một bộ dữ liệu rồi thì
    # cả trang chỉ còn mỗi nút Đăng xuất - muốn tải tệp khác lên phải sửa
    # thanh địa chỉ, hoặc đăng xuất rồi đăng nhập lại.
    head = f'<div><a class=brand href="/">{safe(SYSTEM_NAME)}</a><h1>{safe(title)}</h1>'
    if subtitle:
        head += f"<div class=muted>{safe(subtitle)}</div>"
    head += "</div>"
    # Thanh chinh luon co; cay viec cua bo du lieu nam duoi no khi co. Nut thu
    # gon nam o dau cot, ngay duoi hang tieu de - noi mat nhan ra duoc nhat.
    rail = toggle + main_nav(here) + aside
    middle = f"<div class=with-aside><nav class=aside>{rail}</nav><main>{body}</main></div>"
    return (
        "<!doctype html><html lang=vi><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        # Tu tai lai CHI khi con viec dang chay, va do may chu quyet dinh chu
        # khong phai trinh duyet: xong viec thi trang thoi tu tai, khong ai
        # phai nho tat no di.
        + (f'<meta http-equiv=refresh content="{refresh}">' if refresh else "")
        + f"<title>{safe(title)}</title><style>{STYLE}</style></head><body>"
        f"<div class=top>{head}"
        '<form method=post action="/dang-xuat"><button>Đăng xuất</button></form></div>'
        f"{middle}{script}</body></html>"
    )


# Ba muc cua thanh dieu huong chinh: (duong dan, ten, mot cau noi no de lam gi).
# Mot chuoi duy nhat, vi ten muc va duong dan phai di cung nhau - hai cho khai
# thi mot ngay nao do chung lech nhau va khong ai biet.
MAIN_NAV: Final[tuple[tuple[str, str, str], ...]] = (
    ("/", "Home", "Đưa dữ liệu vào và xem việc đang chạy"),
    ("/du-lieu", "Data", "Các bộ dữ liệu đã và đang xử lý"),
    ("/bang-dieu-khien", "Dashboard", "Ghép các kết luận thành một báo cáo"),
    ("/he-thong", "Hệ thống", "Phiên bản đang chạy và cập nhật code mới"),
)


def main_nav(here: str = "") -> str:
    """Thanh điều hướng chính, giống nhau ở mọi trang.

    Trước đây vào một bộ dữ liệu rồi thì không có đường nào khác ngoài Đăng
    xuất. Một thanh cố định nghĩa là ở đâu cũng biết mình đang ở đâu và đi
    được sang chỗ khác — thứ mà một trang đơn lẻ không tự cho được.
    """
    items = "".join(
        f'<li><a href="{safe(path)}" class="{"here" if path == here else ""}" '
        f'title="{safe(hint)}">{safe(name)}</a></li>'
        for path, name, hint in MAIN_NAV
    )
    return f"<ul class=nav>{items}</ul>"


def sign_in(error: str = "") -> str:
    """Trang duy nhất ai cũng xem được khi chưa đăng nhập."""
    warning = f"<p class=err>{safe(error)}</p>" if error else ""
    return (
        "<!doctype html><html lang=vi><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>Đăng nhập</title><style>{STYLE}</style></head><body>"
        '<div style="max-width:20rem;margin:6rem auto">'
        f"<h1>{safe(SYSTEM_NAME)}</h1>"
        f'{warning}<form class=stack method=post action="/dang-nhap">'
        "<label>Mật khẩu</label>"
        "<input type=password name=password autofocus autocomplete=current-password>"
        "<button class=go>Vào</button></form></div></body></html>"
    )


# --- trang chủ: đưa dữ liệu vào, và những gì đã có --------------------------------


def home(runs: list[RunInfo], space: Workspace) -> str:
    """Nơi bắt đầu, và **chỉ** nơi bắt đầu: thả một tệp vào.

    Trang này từng gánh thêm danh sách mọi việc đang làm. Danh sách đó dài thêm
    một dòng mỗi lần có tệp mới, và chỗ tải lên bị đẩy xuống dưới nó — với vài
    trăm bộ dữ liệu thì việc chính của trang chủ nằm ngoài màn hình.

    Danh sách đã chuyển sang mục **Data**, nơi nó có chỗ để dài ra.
    """
    body = (
        "<h2>Đưa dữ liệu vào</h2>"
        "<p class=muted>Thả một tệp vào đây. Hệ thống đọc, xem dữ liệu có chỗ nào "
        "cần làm sạch không, hỏi ý bạn trước khi sửa, rồi bạn hỏi gì cũng được.</p>"
        '<form class=stack method=post action="/tai-len" enctype="multipart/form-data">'
        "<div class=drop><input type=file name=tep required>"
        '<div class=muted style="margin-top:.6rem">'
        "CSV · Excel · JSON · PDF · Word · Email · ảnh · âm thanh"
        "</div></div>"
        "<label>Đặt tên cho bộ dữ liệu này (bỏ trống thì lấy theo tên tệp)</label>"
        '<input name=ten placeholder="ví dụ: ban_hang_quy3">'
        "<button class=go>Tải lên và làm sạch</button></form>"
    )
    if not runs:
        return body
    # Mot dong, khong phai mot bang: du de biet co viec o do va di sang duoc,
    # khong du de day cho tai len xuong duoi.
    waiting = sum(1 for run in runs if _pending_count(space, run.run_id))
    note = f" — {waiting} bộ đang chờ bạn duyệt" if waiting else ""
    return body + (
        '<p class=muted style="margin-top:2rem">'
        f'Đang có <a href="/du-lieu">{len(runs)} bộ dữ liệu</a>{safe(note)}.</p>'
    )


def _pending_count(space: Workspace, run_id: str) -> int:
    """Còn bao nhiêu việc đang chờ người duyệt, hoặc 0 nếu không đọc được."""
    return pending_count(space, run_id)


# --- một bộ dữ liệu: làm sạch, xem, rồi hỏi ---------------------------------------


def data_page(runs: list[RunInfo], space: Workspace) -> str:
    """Mọi bộ dữ liệu, và bộ nào đang ở đâu.

    Trang chủ trộn hai việc: chỗ tải tệp lên, và danh sách việc đang chạy. Danh
    sách đó dài dần theo mỗi tệp mới, và chỗ tải lên bị đẩy xuống dưới nó.

    Nên tách: trang chủ lo việc **đưa dữ liệu vào**, trang này lo việc **xem
    những gì đã vào**.
    """
    if not runs:
        return (
            "<div class=card>Chưa có bộ dữ liệu nào. "
            '<a href="/">Đưa một tệp vào</a> để bắt đầu.</div>'
        )

    rows = []
    for run in runs:
        rounds = len(
            [
                other
                for other in retention.runs(space.settings)
                if other.run_id.startswith(run.run_id + ROUND_MARK)
            ]
        )
        asked = f"{rounds} phân tích" if rounds else "chưa hỏi câu nào"
        rows.append(
            "<tr>"
            f'<td><a href="/bo/{safe(run.run_id)}">{safe(run.run_id)}</a></td>'
            f"<td>{safe(_dataset_state(space, run.run_id))}</td>"
            f"<td>{safe(asked)}</td>"
            f"<td class=no>{run.bytes_used / 1024:,.0f} KB</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Bộ dữ liệu</th><th>Trạng thái</th>"
        "<th>Đã hỏi</th><th>Dung lượng</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _dataset_state(space: Workspace, run_id: str) -> str:
    """Bộ dữ liệu này đang ở đâu, nói bằng tiếng người.

    Khác  bên dưới: cái đó nói về một LUOT HOI, cái này nói về cả bộ.
    """
    return dataset_status(space, run_id).label


def builder_page(runs: list[RunInfo], space: Workspace) -> str:
    """Chỗ ghép các kết luận đã có thành một báo cáo.

    **Chưa dựng.** Trang này nói thẳng điều đó thay vì hiện một khung trống:
    một trang trống trông y hệt một trang hỏng, và người dùng sẽ đi tìm nút
    không tồn tại.

    Nó liệt kê sẵn nguyên liệu sẽ dùng, để chủ hệ thống thấy được cái sắp dựng
    lấy gì làm đầu vào.
    """
    ready = []
    for run in runs:
        rounds = [
            other.run_id
            for other in retention.runs(space.settings)
            if other.run_id.startswith(run.run_id + ROUND_MARK)
        ]
        answered = sum(1 for round_id in rounds if space.answer(round_id) is not None)
        if answered:
            ready.append((run.run_id, answered))

    if ready:
        items = "".join(
            f'<li><a href="/bo/{safe(name)}">{safe(name)}</a> — {count} câu trả lời</li>'
            for name, count in ready
        )
        material = f"<p>Nguyên liệu đã có:</p><ul>{items}</ul>"
    else:
        material = (
            "<p class=muted>Chưa có câu trả lời nào để ghép. Hỏi vài câu ở một "
            "bộ dữ liệu trước đã.</p>"
        )

    return (
        "<div class=card><b>Chưa dựng xong.</b>"
        "<div class=muted>Đây sẽ là chỗ kéo thả các kết luận đã có thành một "
        "báo cáo để nộp: chọn câu trả lời nào đưa vào, sắp thứ tự, rồi xuất ra "
        "một tệp. Hiện tại mỗi phân tích tải riêng được Excel và Word.</div>"
        f"{material}</div>"
    )


def system_page(version: Version, update: Update, note: str = "") -> str:
    """Bản đang chạy, và nút lấy bản mới về.

    Trên một máy nhỏ đặt ở nhà, mỗi lần sửa xong lại phải SSH vào, `git pull`,
    rồi khởi động lại dịch vụ — ba bước cho một việc, và ba chỗ để gõ nhầm lúc
    nửa đêm.

    Xem có gì mới và áp dụng nó là **hai việc**, nên có hai nút. Xem thì gọi
    bao nhiêu lần cũng được, còn áp dụng thì đổi code đang chạy.
    """
    if not version.sha:
        return (
            '<div class="card err">Không đọc được kho git ở thư mục đang chạy. '
            "Cập nhật từ đây sẽ không dùng được; phải vào máy chủ bằng tay.</div>"
        )

    told = f'<div class="card lead">{safe(note)}</div>' if note else ""

    running = (
        "<h2>Bản đang chạy</h2><div class=card>"
        f"<b>{safe(version.sha)}</b> — {safe(version.subject)}"
        f"<div class=muted>nhánh {safe(version.branch)} · {safe(version.when)}</div></div>"
    )

    if version.dirty:
        # Noi ra ngay, vi day la ly do lat cap nhat se bi tu choi.
        running += (
            '<div class="card err">Trên máy chủ đang có thay đổi chưa lưu. '
            "Cập nhật sẽ bị từ chối cho tới khi chỗ đó được dọn — hệ thống "
            "không ghi đè lên thay đổi của bạn.</div>"
        )

    if update.problem:
        state = f'<div class="card err">Không kiểm được bản mới: {safe(update.problem)}</div>'
    elif update.available:
        rows = "".join(f"<li>{safe(line)}</li>" for line in update.commits[:20])
        more = (
            f"<li class=muted>… và {len(update.commits) - 20} commit nữa</li>"
            if len(update.commits) > 20
            else ""
        )
        state = (
            f'<div class="card wait"><b>Có {update.behind} commit mới.</b>'
            f"<ul>{rows}{more}</ul></div>"
        )
    else:
        state = "<div class=card>Đang chạy bản mới nhất.</div>"

    buttons = (
        '<form method=post action="/he-thong/kiem-tra" style="display:inline">'
        "<button>Kiểm tra lại</button></form> "
        '<form method=post action="/he-thong/cap-nhat" style="display:inline">'
        f"<button class=go{'' if update.available else ' disabled'}"
        f"{'' if update.available else ' disabled'}>Cập nhật ngay</button></form>"
    )

    return (
        told
        + running
        + "<h2>Cập nhật</h2>"
        + state
        + f"<p>{buttons}</p>"
        + "<p class=muted>Chỉ tua tới trên đúng nhánh đang theo dõi. Lịch sử rẽ "
        "nhánh hoặc có sửa tay trên máy chủ thì hệ thống dừng lại và nói ra, "
        "không tự trộn.</p>"
    )


def dataset_page(
    space: Workspace,
    run_id: str,
    rounds: list[tuple[str, str]],
    draft: str = "",
    note: str = "",
) -> str:
    """Toàn bộ một bộ dữ liệu trên một trang, theo đúng thứ tự người ta làm việc."""
    _, running, _ = split_rounds(space, rounds)
    parts = [
        _stale_names(space, run_id),
        _context_section(space, run_id, draft, note),
        _cleaning_section(space, run_id),
        _source_section(space, run_id),
        _ask_section(run_id, running),
        analyses_section(space, run_id, rounds),
    ]
    return "".join(part for part in parts if part)


def _stale_names(space: Workspace, run_id: str) -> str:
    """Bảng này làm sạch bằng bản cũ, và tên cột còn thứ hôm nay đã biết dọn.

    Bản sửa cách đọc tên cột **không quay lại sửa những bảng đã nằm trên đĩa**.
    Một bảng 96 cột làm sạch từ trước giữ nguyên 95 cái tên có dấu cách thừa ở
    đầu — rồi câu hỏi không khớp được cột, và không có gì trên màn hình nối hai
    chuyện đó lại với nhau. Đã mất một lượt chẩn đoán sai vì đúng chuyện này:
    lỗi bị quy cho tầng khớp chữ, trong khi tầng đó chạy đúng.

    Im lặng khi không có gì để nói — trường hợp thường gặp, và cũng là lý do
    cảnh báo này còn đáng đọc khi nó hiện ra.
    """
    try:
        table = space.clean_table(run_id) or space.staged_table(run_id)
    except ServiceError:
        return ""
    if table is None:
        return ""
    changes = would_change(list(table.columns))
    if not changes:
        return ""
    return (
        '<div class="card wait"><b>Bảng này được làm sạch bằng bản cũ.</b>'
        f"<div class=muted>Có {len(changes)} tên cột mà bản hiện tại đã biết dọn "
        "— ví dụ dấu cách thừa ở đầu tên. Tên cột lệch một ký tự vô hình thì câu "
        "hỏi của bạn có thể không khớp được cột, mà không báo gì. "
        "<b>Tải lại đúng tệp đó một lần nữa</b> để hệ thống làm sạch lại bằng bản "
        "mới.</div></div>"
    )


def _merged(current: str, draft: str) -> str:
    """Bối cảnh đang có, cộng thêm bản nháp — không đè lên nhau.

    Ô này người dùng gõ tay. Một bản nháp thay chỗ những gì họ vừa viết là mất
    dữ liệu mà không ai hỏi, nên bản nháp đi XUỐNG DƯỚI. Dòng nào đã có sẵn
    nguyên văn thì không chép lại: bấm hai lần không được sinh ra một bảng chú
    giải dài gấp đôi.
    """
    if not draft:
        return current
    if not current:
        return draft
    had = {line.strip() for line in current.splitlines()}
    fresh = [line for line in draft.splitlines() if line.strip() not in had]
    return current if not fresh else current.rstrip("\n") + "\n" + "\n".join(fresh)


def _context_section(space: Workspace, run_id: str, draft: str = "", note: str = "") -> str:
    """Bối cảnh dữ liệu, do người biết dữ liệu viết.

    Hệ thống KHÔNG đoán lĩnh vực. Một cái nhãn máy tự gán không đối chiếu được
    với gì cả, và đoán sai thì model nói bằng giọng chuyên gia về một lĩnh vực
    không phải của nó - sai mà nghe có thẩm quyền là kiểu sai đắt nhất.

    Người biết `Duration` nghĩa là gì chính là người vừa tải tệp lên.
    """
    try:
        current = space.context(run_id)
    except ServiceError:
        current = ""
    hint = (
        "Vài câu mô tả bộ dữ liệu này: nó ghi gì, thu thập khi nào, và các cột "
        "khó hiểu nghĩa là gì. Câu trả lời nào cũng đọc được phần này."
    )
    # Một dòng `Tên_cột = nghĩa` là thứ code đối chiếu được, khác hẳn văn xuôi
    # quanh nó: nhờ nó mà câu hỏi tiếng Việt gọi được tên cột, và hệ thống biết
    # lên tiếng khi cả câu trả lời không hề chạm tới cột được hỏi.
    glossary_hint = (
        "Muốn chắc hơn nữa, khai mỗi cột một dòng theo mẫu "
        "Tên_cột = nghĩa. Hệ thống dùng đúng những dòng này để báo khi câu "
        "trả lời không chạm tới cột bạn hỏi — nó không tự đoán."
    )
    return (
        "<h2>Bối cảnh dữ liệu</h2>"
        f"<p class=muted>{safe(hint)}</p>"
        f"<p class=muted>{safe(glossary_hint)}</p>"
        + (
            '<div class="card wait"><b>Bản nháp — CHƯA lưu.</b>'
            "<div class=muted>Máy đề xuất nghĩa tiếng Việt cho từng cột. Đọc "
            "lại, sửa chỗ nào sai, rồi bấm Lưu bối cảnh. Hệ thống đã bỏ mọi "
            "dòng trỏ tới cột không có thật.</div></div>"
            if draft
            else ""
        )
        + (f"<p class=err>{safe(note)}</p>" if note else "")
        + f'<form class=stack method=post action="/bo/{safe(run_id)}/boi-canh">'
        f'<textarea name=boi_canh placeholder="Ví dụ: Khảo sát 40 nhà đầu tư cá '
        f"nhân năm 2023.&#10;Duration = thời gian dự định giữ vốn&#10;"
        f'Source = kênh thông tin">{safe(_merged(current, draft))}</textarea>'
        "<button>Lưu bối cảnh</button></form>"
        f'<form method=post action="/bo/{safe(run_id)}/soan-chu-giai">'
        "<button>Máy soạn nháp chú giải</button></form>"
        "<p class=muted>Máy đọc TÊN CỘT — không đọc một dòng dữ liệu nào — rồi "
        "đề xuất nghĩa tiếng Việt. Bản nháp hiện ra để bạn sửa; không có gì "
        "được lưu cho tới khi bạn bấm Lưu bối cảnh.</p>"
    )


def _cleaning_section(space: Workspace, run_id: str) -> str:
    """Hệ thống đã xem dữ liệu và thấy gì — và chỗ để bạn nói lại."""
    gates = space.gates(run_id)
    verdicts = _verdicts(space, run_id)
    status = _cleaning_status(space, run_id)

    if not gates:
        if status or verdicts:
            body = (
                "<div class=card><ul>"
                + "".join(f"<li>{safe(line)}</li>" for line in verdicts)
                + "</ul></div>"
                if verdicts
                else ""
            )
            return f"<h2>Làm sạch</h2>{status}{body}"
        return ""

    # Moi gate deu tung hien duoi tieu de "Lam sach", ke ca gate duyet ket luan
    # cua Manager - kem mot o nhap "ten_luat:cot" khong lien quan gi. Nguoi dung
    # doc mot cai tieu de noi sai viec ho dang lam thi ho khong duyet, ho doan.
    blocks = [f"<h2>{safe(_gate_heading(gates))} — đang chờ bạn</h2>"]
    if verdicts:
        blocks.append(
            "<div class=card><b>Hệ thống đã xem dữ liệu:</b><ul>"
            + "".join(f"<li>{safe(line)}</li>" for line in verdicts)
            + "</ul></div>"
        )

    for gate in gates:
        # Nothing is ticked to begin with. A live run offered six rules, one of
        # which was "cast every column" - on a table whose first column is
        # student_id. Ticked by default, one click would have approved it. The
        # gate exists so that approving is something a person does, not
        # something that happens while they are agreeing to the rest.
        options = "".join(
            "<li><label>"
            f'<input type=checkbox name=chon value="{safe(option.option_id)}"> '
            f"<b>{safe(option.label)}</b></label>"
            + (f"<div class=muted>{safe(option.detail)}</div>" if option.detail else "")
            + "</li>"
            for option in gate.options
        )
        blocks.append(
            f'<div class="card wait"><b>{safe(gate.title)}</b>'
            f"<div class=muted>{safe(gate.question)}</div>"
            f'<form class=stack method=post action="/bo/{safe(run_id)}/duyet">'
            f'<input type=hidden name=gate_id value="{safe(gate.gate_id)}">'
            f"<ul>{options or '<li class=muted>Không có mục nào để duyệt.</li>'}</ul>"
            + (_extra_rules_box() if _is_cleaning(gate) else "")
            + "<div class=muted>"
            + safe(_tick_hint(gate))
            + " Không tích gì thì không có gì chạy.</div>"
            f"<button class=go>{safe(_button_label(gate))}</button></form></div>"
        )
    return "".join(blocks)


def _cleaning_status(space: Workspace, run_id: str) -> str:
    """Đang chạy, hay đã dừng — nói ra, đừng để người dùng đoán.

    Chủ hệ thống tích các mục làm sạch rồi ngồi nhìn một trang **không nói gì**:
    *"không biết hệ thống có đang chạy hay không hay dừng lại rồi"*. Lúc đó nó
    đã chết được năm phút — bước làm sạch hỏng, và trang vẫn hiện bảng dữ liệu
    với ô đặt câu hỏi như thể mọi thứ bình thường.

    Một trang im lặng nói hai điều cùng lúc, "đang chạy" và "đã xong", và người
    đọc không có cách nào tách chúng ra.
    """
    if space.running(run_id):
        return (
            f"<div class=card>{SPINNER}<b>Đang làm sạch dữ liệu…</b>"
            "<div class=muted>Bảng lớn thì lâu hơn. Trang tự cập nhật khi xong, "
            "bạn đi xem việc khác cũng được.</div></div>"
        )
    stopped = space.why_stopped(run_id)
    if stopped:
        # Cau nay den tu ErrorDetail cua chinh buoc bi hong, khong phai mot cau
        # chung chung - nguoi doc can biet HONG O DAU thi moi sua duoc.
        return (
            f'<div class="card err"><b>Làm sạch đã dừng — chưa xong.</b>'
            f"<div>{safe(stopped)}</div>"
            "<div class=muted>Dữ liệu gốc không bị đụng tới. Bỏ tích mục gây lỗi "
            "rồi duyệt lại, hoặc tải lại tệp để làm từ đầu.</div></div>"
        )
    return ""


# Ghe lam sach. Cac gate khac - duyet ket luan, duyet lap luan - la viec khac
# han, va goi chung bang mot cai ten la cach nguoi dung bam dong y cho mot thu
# ho tuong la thu khac.
CLEANER: Final[str] = "a3_cleaner"


def _is_cleaning(gate: GateReport) -> bool:
    """Gate nay có phải là duyệt cách làm sạch dữ liệu không."""
    return gate.agent_id == CLEANER


def _gate_heading(gates: list[GateReport]) -> str:
    """Tên cho việc đang chờ duyệt, gọi theo đúng việc đó."""
    if all(_is_cleaning(gate) for gate in gates):
        return "Làm sạch"
    if any(_is_cleaning(gate) for gate in gates):
        return "Chờ duyệt"
    return "Duyệt kết luận"


def _tick_hint(gate: GateReport) -> str:
    if _is_cleaning(gate):
        return "Tích vào những cách làm sạch bạn đồng ý."
    return "Tích vào những kết luận bạn muốn đưa vào báo cáo."


def _button_label(gate: GateReport) -> str:
    return "Đồng ý và làm sạch" if _is_cleaning(gate) else "Đồng ý và chạy tiếp"


def _extra_rules_box() -> str:
    """Chỗ để yêu cầu làm sạch thêm — chỉ có nghĩa ở gate làm sạch."""
    return (
        "<label>Muốn làm sạch thêm? Ghi ở đây, mỗi dòng một yêu cầu — "
        "<code>tên_luật:cột1,cột2</code></label>"
        '<textarea name=them placeholder="trim_whitespace:ten_khach&#10;'
        'replace_sentinel_with_null:ghi_chu"></textarea>'
    )


def _verdicts(space: Workspace, run_id: str) -> list[str]:
    """Những gì hệ thống thấy khi nhìn vào dữ liệu.

    Vẫn hiện sau khi đã duyệt: đó mới là lúc người ta hỏi rốt cuộc hệ thống
    đã làm gì với dữ liệu của mình.
    """
    try:
        return list(space.examination(run_id))
    except ServiceError:
        return []


def _source_section(space: Workspace, run_id: str) -> str:
    """Dữ liệu gốc, đúng như tệp được tải lên.

    Trang bộ dữ liệu nói về dữ liệu GỐC; bản sạch có trang riêng. Trước đây cả
    hai là một, nên bấm vào "Dữ liệu sạch" ở cây bên trái thì không có gì đổi.
    """
    table = space.staged_table(run_id)
    if table is None:
        return ""
    try:
        frame = space.table(table.uri, limit=15)
    except ServiceError:
        return ""
    return (
        "<h2>Dữ liệu gốc</h2>"
        f"<div class=muted>{table.rows:,} dòng · {len(table.columns)} cột · "
        "xem 15 dòng đầu, đúng như tệp bạn tải lên</div>"
        f"<div class=scroll>{_as_table(frame)}</div>"
    )


def clean_page(space: Workspace, run_id: str) -> str:
    """Trang chỉ có bản sạch, và đường tải nó về."""
    body = _preview_section(space, run_id)
    if not body:
        return (
            "<div class=card>Chưa có bản sạch. Hãy duyệt cách làm sạch ở trang "
            "bộ dữ liệu trước.</div>"
        )
    return body


def _preview_section(space: Workspace, run_id: str) -> str:
    """Bản sạch, để mắt người xem trước khi hỏi bất cứ điều gì."""
    table = space.clean_table(run_id)
    if table is None:
        return ""
    try:
        frame = space.table(table.uri, limit=15)
    except ServiceError:
        return ""
    return (
        f"<h2>Dữ liệu sạch</h2>"
        f"<div class=muted>{table.rows:,} dòng · {len(table.columns)} cột · "
        f"xem 15 dòng đầu</div>"
        f"<div class=scroll>{_as_table(frame)}</div>"
        f'<p class=muted><a href="/tai-ve/{safe(run_id)}">Tải bản sạch về (CSV)</a></p>'
    )


def _as_table(frame: pd.DataFrame) -> str:
    head = "".join(f"<th>{safe(name)}</th>" for name in frame.columns)
    rows = "".join(
        "<tr>" + "".join(f"<td>{safe(value)}</td>" for value in row) + "</tr>"
        for row in frame.itertuples(index=False, name=None)
    )
    return f"<table><tr>{head}</tr>{rows}</table>"


def _ask_section(run_id: str, running: list[tuple[str, str]] | None = None) -> str:
    """Chỗ đặt câu hỏi, và chỉ báo cho câu đang chạy.

    Chỉ báo nằm ngay dưới nút gửi, và nó đọc từ trạng thái trên đĩa chứ không
    từ trình duyệt — nên rời trang rồi quay lại thì nó vẫn còn, đúng như lúc đó
    câu hỏi vẫn đang chạy.
    """
    waiting = ""
    for _, question in running or []:
        waiting += (
            f"<div class=card>{SPINNER}<b>Đang xử lý:</b> {safe(question)}"
            "<div class=muted>Trang tự cập nhật khi xong. Bạn đi xem việc khác "
            "cũng được, câu hỏi vẫn chạy.</div></div>"
        )
    return (
        "<h2>Hỏi</h2>"
        f'<form class=stack method=post action="/bo/{safe(run_id)}/hoi">'
        '<textarea name=cau_hoi required placeholder="Ví dụ: Kênh nào có doanh thu cao nhất, '
        'và thấp nhất?"></textarea>'
        "<button class=go>Gửi câu hỏi</button></form>"
        + waiting
        + "<p class=muted>Hỏi bao nhiêu lần cũng được. Mỗi câu trả lời đều kèm nguồn "
        "của từng con số.</p>"
    )


def sidebar(root: Node, here: str = "") -> str:
    """Cây việc bên trái: đang đứng ở đâu, và có thể đi đâu.

    Một cuộn chat dài vô tận không cho người đọc biết mình đang ở mức nào.
    Cây thì có: bộ dữ liệu, bản sạch, rồi từng phân tích và phân tích con.
    """
    return f"<div class=muted>Bộ dữ liệu</div>{_branch([root], here)}"


def _branch(nodes: list[Node], here: str) -> str:
    if not nodes:
        return ""
    items = []
    for node in nodes:
        mark = " class=here" if node.run_id == here else ""
        number = f"<span class=no>{safe(node.number)}. </span>" if node.number else ""
        items.append(
            f'<li><a href="{safe(node.href)}"{mark}>{number}{safe(node.label)}</a>'
            + _branch(node.children, here)
            + "</li>"
        )
    return "<ul>" + "".join(items) + "</ul>"


def analyses_section(space: Workspace, dataset: str, rounds: list[tuple[str, str]]) -> str:
    """Danh sách phân tích - tên và trạng thái, không đổ hết câu trả lời ra.

    Chỉ những lượt thật sự ra được kết quả mới được đánh số "Phân tích N". Một
    lượt hỏng đứng chung danh sách và mang số thứ tự của riêng nó trông y hệt
    một phân tích thật, và chủ hệ thống đếm được hai trong khi chỉ hỏi một.

    Lượt hỏng vẫn hiện - gọn, dưới cùng, kèm lý do ngắn. Giấu hẳn thì người ta
    không hiểu vì sao câu mình vừa hỏi biến mất.
    """
    done, running, broken = split_rounds(space, rounds)

    blocks = []
    if done:
        rows = "".join(
            f'<li><a href="/bo/{safe(dataset)}/pt/{safe(run_id)}">'
            f"<b>Phân tích {index}</b> — {safe(question or run_id)}</a>"
            f"<div class=muted>{safe(_state_of(space, run_id))}</div></li>"
            for index, (run_id, question) in enumerate(done, 1)
        )
        blocks.append(f"<h2>Các phân tích</h2><ul>{rows}</ul>")
    if running:
        rows = "".join(
            f'<li><a href="/bo/{safe(dataset)}/pt/{safe(run_id)}">{safe(question or run_id)}</a>'
            f"<div class=muted>{SPINNER}Đang chạy…</div></li>"
            for run_id, question in running
        )
        blocks.append(f"<h2>Đang chạy</h2><ul>{rows}</ul>")
    if broken:
        rows = "".join(
            f'<li><a href="/bo/{safe(dataset)}/pt/{safe(run_id)}">{safe(question or run_id)}</a>'
            f"<div class=muted>{safe(_why_no_answer(space, run_id))}</div></li>"
            for run_id, question in broken
        )
        blocks.append(
            "<details class=gaps><summary>"
            f"{len(broken)} lượt hỏi không hoàn thành"
            f"</summary><ul>{rows}</ul></details>"
        )
    blocks.append(_tidy_up(dataset, [*done, *broken]))
    return "".join(blocks)


def _tidy_up(dataset: str, rounds: list[tuple[str, str]]) -> str:
    """Chỗ xoá hẳn những phân tích không cần nữa.

    Một bộ dữ liệu tích được mười bốn phân tích chỉ sau một buổi thử, và phần
    lớn là rác. Không có chỗ dọn thì danh sách chỉ dài thêm mãi.

    Nằm trong một khối gập lại, và không có nút nào ở ngoài: xoá là việc không
    lùi được, nên nó phải cần một cú bấm để mở ra và một cú nữa để làm — chứ
    không nằm cạnh chỗ người ta bấm hàng ngày.

    Lượt **đang chạy** không có trong danh sách này. Xoá một việc đang chạy thì
    nó vẫn chạy tiếp rồi ghi lại thư mục vừa bị xoá, và cái còn lại là một nửa
    lượt chạy không ai đọc được.
    """
    if not rounds:
        return ""
    items = "".join(
        "<li><label>"
        f'<input type=checkbox name=xoa value="{safe(run_id)}"> '
        f"{safe(question or run_id)}</label></li>"
        for run_id, question in rounds
    )
    return (
        "<details class=gaps><summary>Dọn bớt phân tích</summary>"
        "<div class=muted>Tích vào những phân tích không cần nữa. Xoá rồi thì "
        "không lấy lại được — câu trả lời, biểu đồ và bảng của lượt đó đều mất. "
        "Dữ liệu gốc và bản đã làm sạch thì không bị đụng tới.</div>"
        f'<form class=stack method=post action="/bo/{safe(dataset)}/xoa-phan-tich">'
        f"<ul>{items}</ul>"
        "<button>Xoá những mục đã tích</button></form></details>"
    )


def split_rounds(
    space: Workspace, rounds: list[tuple[str, str]]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[tuple[str, str]]]:
    """Chia lượt hỏi thành (ra được kết quả, đang chạy, không hoàn thành).

    Một hàm duy nhất, dùng cho cả cây bên trái lẫn danh sách giữa trang. Lần
    trước tôi chỉ sửa danh sách và để nguyên cây, nên danh sách nói có một phân
    tích còn cây nói có hai — cùng một câu hỏi, hai câu trả lời khác nhau trên
    cùng một màn hình.

    Thứ tự cũng ra từ đây, và là **cũ trước**. Cây đảo lại còn danh sách thì
    không, nên "Phân tích 1" ở hai bên là hai phân tích khác nhau. Cũ trước là
    thứ tự đúng: thêm một phân tích mới thì nó nhận số lớn nhất và các số cũ
    giữ nguyên. Đánh số mới trước thì mỗi lần hỏi là mọi cái tên đổi một lần.

    Args:
        space: nơi tra xem một lượt có ra được kết quả không.
        rounds: (mã lượt, câu hỏi) theo thứ tự nào cũng được.

    Returns:
        (ra được kết quả, đang chạy, không hoàn thành) — đều cũ trước.
    """
    return shared_split_rounds(space, rounds)


def _round_number(run_id: str) -> tuple[int, str]:
    """Số thứ tự của lượt hỏi, để xếp cũ trước.

    `finance_data__q10` phải đứng sau `__q9`, nên so bằng số chứ không bằng chữ.
    Mã không đọc được số thì xếp theo chữ, đứng sau - thà sai chỗ còn hơn biến
    mất.
    """
    _, mark, tail = run_id.partition(ROUND_MARK)
    if mark and tail.isdigit():
        return (int(tail), "")
    return (10**9, run_id)


def _has_result(space: Workspace, run_id: str) -> bool:
    """Lượt này có ra được cái gì để đọc không - câu trả lời, hoặc một gate đang chờ."""
    return round_has_result(space, run_id)


def _state_of(space: Workspace, run_id: str) -> str:
    """Một dòng nói lượt hỏi này đang ở đâu - kể cả khi nó hỏng."""
    return round_status(space, run_id).label


def _why_no_answer(space: Workspace, run_id: str) -> str:
    """Vì sao lượt này không có câu trả lời.

    "Chưa có câu trả lời." đứng một mình trông y hệt một câu hỏi bị lặp lại, và
    đó đúng là điều chủ hệ thống nhìn thấy: hai lần cùng một câu hỏi, một lần có
    đáp án, một lần không, không dòng nào nói vì sao.
    """
    try:
        reason = space.why_stopped(run_id)
    except ServiceError:
        return "Chưa có câu trả lời."
    # Rỗng nghĩa là: không hỏng, không báo gì, và cũng chưa có đáp án — tức là
    # nó đang chạy. Trước đây chỗ này in "Chưa có câu trả lời.", nên chủ hệ
    # thống gửi một câu hỏi, mở trang ra và thấy đúng câu đó, trông y hệt một
    # lỗi. Một lượt vừa bắt đầu thì chưa có trạng thái trên đĩa, nên
    # `running()` cũng chưa nói được gì.
    return reason


def analysis_page(space: Workspace, dataset: str, run_id: str, question: str) -> str:
    """Một phân tích, trọn vẹn trên trang của riêng nó."""
    head = f"<h2>{safe(question or run_id)}</h2>"
    if _pending_count(space, run_id):
        return head + "<div class=card>Đang chờ bạn duyệt.</div>" + _gate_here(space, run_id)

    answer = space.answer(run_id)
    if answer is None:
        why = _why_no_answer(space, run_id)
        if not why:
            return head + (
                f"<div class=card>{SPINNER}<b>Đang phân tích…</b>"
                "<div class=muted>Trang tự cập nhật khi xong. Bạn đi xem việc "
                "khác cũng được, câu hỏi vẫn chạy.</div></div>"
            )
        return head + f'<div class="card err">{safe(why)}</div>'
    if not answer.claims:
        return head + "<div class=card>Không rút ra được kết luận nào từ dữ liệu này.</div>"

    measured = space.measured(run_id)
    parts = [head, _risk_banner(answer), _direct_answer(answer)]
    for index, claim in enumerate(answer.claims, 1):
        parts.append(_one_claim(dataset, run_id, index, claim, measured))
    parts.append(_blocked(answer))
    parts.append(_repaired(answer))
    parts.append(_gaps(answer))
    parts.append(_estimates(measured))
    parts.append(_take_away(dataset, run_id))
    return "".join(parts)


def _estimates(measured: dict[str, float]) -> str:
    """Ước lượng kỳ tới — dưới hết, và trong thẻ của riêng nó.

    Nó **không phải** một kết luận và không được đứng lẫn vào đám kết luận: mọi
    con số phía trên truy ngược được về một dòng dữ liệu, còn con số này truy
    về một đường thẳng. Để chung một chỗ là xoá đúng cái ranh giới khiến những
    con số kia đáng tin.

    Không có trục thời gian thì phần này không hiện gì cả — im lặng, chứ không
    phải một thẻ rỗng nói "chưa có dữ liệu".
    """
    rows: list[str] = []
    for found in forecast_values(measured):
        rows.append(
            f"<li><b>{safe(found.name)}</b>: kỳ sau {safe(found.last_period)} "
            f"ước chừng trong khoảng <b>{found.low:,.2f} – {found.high:,.2f}</b> "
            f"<span class=muted>(khớp đường thẳng R² = {found.r2:.2f}, "
            f"dựa trên {found.periods} kỳ đã có)</span></li>"
        )
    if not rows:
        return ""
    return (
        "<div class=card><b>Ước lượng kỳ tới — KHÔNG phải số đo</b>"
        "<div class=muted>Đây là phép kéo dài theo đường thẳng từ các kỳ đã có. "
        "Nó giả định mọi thứ tiếp tục như cũ, và không có kết luận nào ở trên "
        "dựa vào nó.</div>"
        f"<ul>{''.join(rows)}</ul></div>"
    )


def _take_away(dataset: str, run_id: str) -> str:
    """Mang cau tra loi nay di dau.

    Chup man hinh thi mat canh bao, mat metric key, mat phan khong xac lap
    duoc - tuc la mat dung nhung thu khien con so dang tin. Hai tep nay giu
    lai het.
    """
    base = f"/bo/{safe(dataset)}/pt/{safe(run_id)}/tai"
    return (
        "<div class=card><b>Mang di</b>"
        "<div class=muted>Ca hai tep deu giu canh bao do tin cay, chi so da dung "
        "va phan chua xac lap duoc.</div>"
        f'<p><a href="{base}/excel">Tai Excel (.xlsx)</a> &nbsp; '
        f'<a href="{base}/word">Tai Word (.docx)</a></p></div>'
    )


# Vi sao mot ket luan bi chan, noi bang tieng nguoi doc. Tung nhom mot cau,
# vi ba loai nay khac han nhau: mot cai la NOI SAI, mot cai la khong chung
# minh duoc, mot cai la lac de.
BLOCKED_KINDS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    (
        "nói sai so với dữ liệu",
        "Hệ thống đối chiếu lại với số đã đo và thấy không khớp.",
        ("nhung nhom cao nhat that su", "nhưng nhóm cao nhất thật sự"),
    ),
    (
        "không dẫn được về chỉ số nào",
        "Mọi con số phải truy được về một phép đo. Câu này gõ số thẳng vào, "
        "hoặc dẫn tới một chỉ số không tồn tại.",
        ("go truc tiep", "gõ trực tiếp", "metric_keys", "placeholder"),
    ),
    (
        "không trả lời câu hỏi đã hỏi",
        "Đúng nhưng lạc đề.",
        ("khong tra loi cau hoi", "không trả lời câu hỏi", "khong lien quan"),
    ),
)


def _blocked_kind(line: str) -> tuple[str, str]:
    """Câu này bị chặn vì loại lý do nào."""
    lowered = line.lower()
    for title, explain, marks in BLOCKED_KINDS:
        if any(mark.lower() in lowered for mark in marks):
            return title, explain
    return "bị chặn vì lý do khác", ""


def _direct_answer(answer: Any) -> str:
    """Câu trả lời thẳng, đứng trước mọi bằng chứng.

    Chủ hệ thống đọc một trang toàn số liệu đúng và không thấy câu trả lời đâu:
    *"hệ thống đang hành xử giống một cỗ máy in báo cáo thống kê hơn là một
    chuyên gia phân tích"*. Hỏi *"poutcome hay campaign ảnh hưởng mạnh hơn"* thì
    người ta chờ nghe **"poutcome mạnh hơn"** — ba đoạn số liệu đúng mà thiếu
    câu đó là bắt người đọc tự làm nốt việc hệ thống đáng lẽ làm hộ.

    Nó nằm **sau** khối cảnh báo độ tin cậy và **trước** các luận điểm. Thứ tự
    đó có chủ ý: một câu chốt đọc trước khi biết dữ liệu mỏng là một câu chốt
    được tin nhầm, và cảnh báo đọc sau khi đã tin thì đã muộn.
    """
    said = str(getattr(answer, "summary", "") or "").strip()
    if said:
        return f'<div class="card lead"><b>Trả lời:</b> {safe(said)}</div>'

    # Khong co cau chot thi o nay VAN PHAI NOI GI DO. Da xay ra that: model viet
    # dung cau tra loi can viet, go thang mot con so vao, va code bo CA CAU -
    # cho duoc doc nhieu nhat trang tro nen trong tron, khong mot chu nao noi vi
    # sao. Chu he thong doc xong ket luan la he thong ne cau hoi.
    #
    # Bo cau chot van dung: mot con so go tay khong truy nguoc duoc ve phep do
    # nao. Nhung "bo trong im lang" thi khong dung, va do la hai chuyen khac
    # nhau.
    refused = refusals(getattr(answer, "rejected", ()))
    if refused:
        return (
            '<div class="card wait"><b>Chưa có câu trả lời thẳng.</b>'
            f"<div class=muted>{safe(plainly(refused[0]))} "
            "Các kết luận bên dưới vẫn đầy đủ và vẫn dẫn nguồn được.</div></div>"
        )
    return (
        '<div class="card wait"><b>Chưa có câu trả lời thẳng.</b>'
        "<div class=muted>Hệ thống không chốt được một câu trả lời trực tiếp cho "
        "câu hỏi này. Hãy đọc các kết luận bên dưới — chúng vẫn dẫn nguồn được "
        "về từng phép đo.</div></div>"
    )


def _repaired(answer: Any) -> str:
    """Những kết luận hệ thống đã **sửa nhẹ rồi giữ lại**.

    Chúng đi chung một danh sách với các kết luận bị loại thật, nên người đọc
    đếm cả cụm là "đã bị trảm" — và chủ hệ thống đã đọc đúng như vậy, rồi từ đó
    đề nghị nới lỏng một lớp bảo vệ vốn đã nới sẵn.

    Sửa và loại là hai việc khác nhau, nên chúng phải nằm hai chỗ khác nhau.
    """
    lines = [line for line in getattr(answer, "rejected", ()) if was_repaired(line)]
    if not lines:
        return ""
    return (
        "<details class=more><summary>"
        f"{len(lines)} kết luận đã được dọn lại và VẪN GIỮ</summary>"
        "<div class=muted>Model gõ thêm đơn vị ngay sau chỗ hệ thống tự chèn "
        "đơn vị. Hệ thống bỏ phần gõ thừa và giữ nguyên kết luận — không có "
        "kết luận nào mất vì chuyện này.</div><ul>"
        + "".join(f"<li>{safe(line)}</li>" for line in lines)
        + "</ul></details>"
    )


def _blocked(answer: Any) -> str:
    """Những kết luận hệ thống đã chặn, và vì sao.

    Chủ hệ thống đếm được hai phân tích trong khi chỉ hỏi một, và kết luận là
    Manager bỏ dở việc. Thật ra Manager đã trả lời đủ - nó nói sai ba lần, lớp
    kiểm duyệt xóa cả ba, và không ai nói cho người hỏi biết.

    Xóa im lặng thì đúng về số liệu mà sai về lòng tin: người đọc thấy câu hỏi
    của mình cụt mất mà không hiểu vì sao.
    """
    # Dong sua nhe di rieng: mot ket luan duoc don lai roi GIU khong phai
    # mot ket luan bi loai, va de chung thi nguoi doc dem ca cum la da bi tram.
    blocked = [line for line in (getattr(answer, "rejected", ()) or ()) if not was_repaired(line)]
    if not blocked:
        return ""

    groups: dict[str, list[str]] = {}
    explains: dict[str, str] = {}
    for line in blocked:
        title, explain = _blocked_kind(str(line))
        groups.setdefault(title, []).append(str(line))
        explains[title] = explain

    summary = ", ".join(f"{len(items)} {title}" for title, items in groups.items())
    body = "".join(
        f"<h3>{safe(title)} ({len(items)})</h3>"
        + (f"<p class=muted>{safe(explains[title])}</p>" if explains[title] else "")
        + "<ul>"
        + "".join(f"<li class=muted>{safe(item)}</li>" for item in items)
        + "</ul>"
        for title, items in groups.items()
    )
    return (
        "<details class=gaps><summary>"
        f"Hệ thống đã chặn {len(blocked)} kết luận: {safe(summary)}"
        "</summary>"
        "<p class=muted>Những câu này KHÔNG nằm trong câu trả lời ở trên. "
        "Chúng hiện ra ở đây để bạn biết chúng đã từng tồn tại.</p>" + body + "</details>"
    )


def _gate_here(space: Workspace, run_id: str) -> str:
    """Man duyet cho chinh luot hoi nay, neu con gate nao dang cho."""
    return _cleaning_section(space, run_id)


def _risk_banner(answer: Any) -> str:
    """Cảnh báo độ tin cậy, đặt TRƯỚC kết luận chứ không sau.

    Đặt sau thì người đọc đã tin xong rồi mới đọc tới. Đặt trong một khối gấp
    lại thì phần lớn không ai mở. Những dòng này nói *"con số dưới đây mỏng tới
    mức đừng tin vội"*, và biết điều đó sau khi đã tin là biết muộn.

    Code gắn vào, không nhờ model nhớ.
    """
    lines = list(getattr(answer, "warnings", ()) or ())
    if not lines:
        return ""
    return (
        '<div class="card wait"><b>Đọc con số bên dưới với mức tin cậy này:</b><ul>'
        + "".join(f"<li>{safe(line)}</li>" for line in lines)
        + "</ul></div>"
    )


def _one_claim(
    dataset: str,
    run_id: str,
    index: int,
    claim: Any,
    measured: dict[str, float] | None = None,
) -> str:
    """Một kết luận, biểu đồ của nó, và chỗ hỏi tiếp về đúng nó.

    Chủ hệ thống mô tả đúng việc này: câu hỏi A cho ra A1, A2, A3, và người phân
    tích muốn khai thác A1 trước rồi mới tới A2. Trước đây muốn thế thì phải gõ
    lại cả bối cảnh vào ô hỏi chung ở cuối trang.
    """
    # SVG truoc: chu net khi phong to, chon duoc de sao chep, doi theo nen sang
    # toi. PNG van giu lam duong lui - va van la thu di vao ban Word, noi mot
    # tep nhung SVG mo ra la mot o trong tren nhieu may.
    chart = ""
    drawn = chart_for(
        pairs_from(measured or {}, list(getattr(claim, "metric_keys", ()))),
        title=str(claim.claim)[:60],
    )
    if drawn:
        chart = f"<p>{drawn}</p>"
    elif getattr(claim, "chart_ref", ""):
        name = str(claim.chart_ref).rsplit("/", 1)[-1]
        chart = f'<p><img src="/anh/{safe(name)}" alt=""></p>'
    text = safe(claim.claim)
    return (
        f"<div class=claim><b>{index}.</b> {text}{chart}"
        "<details class=more><summary>Hỏi tiếp về kết luận này</summary>"
        f'<form class=stack method=post action="/bo/{safe(dataset)}/hoi">'
        f'<input type=hidden name=tu value="{safe(run_id)}">'
        f'<input type=hidden name=luan_diem value="{text}">'
        "<textarea name=cau_hoi required "
        'placeholder="Ví dụ: chia nhỏ con số này theo từng nhóm"></textarea>'
        "<button class=go>Hỏi tiếp</button></form></details></div>"
    )


# Dong chi noi voi NGUOI CAU HINH he thong, khong phai nguoi doc bao cao. Chung
# nhac toi mot khoa trong tep cau hinh ma tu dashboard khong dat duoc, nen voi
# nguoi dung chung la mot loi khuyen khong lam theo duoc:
#
#   "khong tu chay hoi quy - chon bien giai thich la mot nhan dinh, phai duoc
#    khai ro trong 'tests.regressions'"
#
# Chu he thong yeu cau bo chung khoi man hinh nhung GIU LAI trong du lieu:
#
#   "no bi vo nghia nen moi bao ban bo no di khong can hien cho user xem nhung
#    van se giu lai thong tin cho he thong dung luc can"
#
# Nen viec loc nam o day, tang trinh bay - artifact, dong lenh va cac buoc sau
# van nhan duoc day du.
FOR_OPERATORS: Final[tuple[str, ...]] = ("tests.regressions", "'tests'")


def for_operators_only(line: str) -> bool:
    """Dòng này nói với người cấu hình hệ thống, không phải người đọc."""
    return any(mark in line for mark in FOR_OPERATORS)


# Nhung gi he thong KHONG ket luan, chia theo dung hai loai khac nhau. Truoc day
# ca hai nam chung mot khoi ten "Khong ket luan duoc", nen viec he thong tu gioi
# han de tranh ket luan sai trong y het mot that bai.
GAP_KINDS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    (
        "Đã giới hạn để tránh kết luận sai",
        "Chạy càng nhiều phép kiểm thì càng dễ có kết quả trông có ý nghĩa "
        "nhưng thật ra là ngẫu nhiên, nên hệ thống tự dừng ở 8 phép mỗi loại.",
        ("chỉ chạy", "ngẫu nhiên"),
    ),
    (
        "Dữ liệu chưa đủ để nói",
        "Các nhóm quá ít dòng thì con số trung bình của nhóm không nói lên điều gì.",
        ("quá ít", "đủ lớn", "cần ít nhất", "không đổi"),
    ),
)


def _gaps(answer: Any) -> str:
    """Những gì không kết luận được, chia loại và gấp lại.

    Chủ hệ thống nói thẳng là khối này không giúp gì cho việc phân tích, và
    đúng: mười một dòng chữ máy mở sẵn giữa trang đẩy kết luận thật xuống dưới.
    Nó vẫn phải còn - một con số vắng mặt và một con số không ai được báo trông
    giống hệt nhau - nhưng nó là chú thích, không phải nội dung.
    """
    lines = [
        line
        for line in list(answer.unanswered) + [need.ask for need in answer.needs]
        if not for_operators_only(line)
    ]
    if not lines:
        return ""

    groups: dict[str, list[str]] = {}
    for line in lines:
        groups.setdefault(_kind_of(line), []).append(line)

    blocks = []
    for title, explain, _ in GAP_KINDS:
        found = groups.get(title)
        if not found:
            continue
        blocks.append(
            f"<h3>{safe(title)}</h3><p class=muted>{safe(explain)}</p>"
            "<ul>" + "".join(f"<li class=muted>{safe(item)}</li>" for item in found) + "</ul>"
        )
    other = groups.get("")
    if other:
        blocks.append(
            "<h3>Ghi chú khác</h3><ul>"
            + "".join(f"<li class=muted>{safe(item)}</li>" for item in other)
            + "</ul>"
        )
    return (
        "<details class=gaps><summary>"
        f"Hệ thống đã không kết luận {len(lines)} điều — xem vì sao"
        "</summary>" + "".join(blocks) + "</details>"
    )


def _kind_of(line: str) -> str:
    """Dòng này thuộc loại nào trong ba loại."""
    lowered = line.lower()
    for title, _, marks in GAP_KINDS:
        if any(mark in lowered for mark in marks):
            return title
    return ""
