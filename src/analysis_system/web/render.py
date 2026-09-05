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
from typing import Any

import pandas as pd

from analysis_system.api import ServiceError, Workspace
from analysis_system.services.retention import RunInfo
from analysis_system.web.naming import describe, phase_of

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
"""


def safe(value: Any) -> str:
    """Bất cứ thứ gì, dưới dạng văn bản không thể trở thành mã."""
    return escape(str(value), quote=True)


def page(title: str, body: str, subtitle: str = "") -> str:
    """Một trang, trong cùng một khung với mọi trang khác."""
    head = f"<div><h1>{safe(title)}</h1>"
    if subtitle:
        head += f"<div class=muted>{safe(subtitle)}</div>"
    head += "</div>"
    return (
        "<!doctype html><html lang=vi><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{safe(title)}</title><style>{STYLE}</style></head><body>"
        f"<div class=top>{head}"
        '<form method=post action="/dang-xuat"><button>Đăng xuất</button></form></div>'
        f"{body}</body></html>"
    )


def sign_in(error: str = "") -> str:
    """Trang duy nhất ai cũng xem được khi chưa đăng nhập."""
    warning = f"<p class=err>{safe(error)}</p>" if error else ""
    return (
        "<!doctype html><html lang=vi><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>Đăng nhập</title><style>{STYLE}</style></head><body>"
        '<div style="max-width:20rem;margin:6rem auto">'
        "<h1>Hệ thống phân tích dữ liệu</h1>"
        f'{warning}<form class=stack method=post action="/dang-nhap">'
        "<label>Mật khẩu</label>"
        "<input type=password name=password autofocus autocomplete=current-password>"
        "<button class=go>Vào</button></form></div></body></html>"
    )


# --- trang chủ: đưa dữ liệu vào, và những gì đã có --------------------------------


def home(runs: list[RunInfo], space: Workspace) -> str:
    """Nơi bắt đầu: thả một tệp vào, hoặc mở lại việc đang làm dở."""
    upload = (
        "<h2>Đưa dữ liệu vào</h2>"
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
        return upload + '<p class=muted style="margin-top:2rem">Chưa có việc nào.</p>'

    rows = []
    for run in runs:
        named = describe(run.run_id, run.started)
        waiting = _pending_count(space, run.run_id)
        mark = (
            '<span class="tag wait">chờ bạn duyệt</span>'
            if waiting
            else f'<span class="tag ok">{safe(phase_of(run.phase))}</span>'
        )
        rows.append(
            f'<tr><td><a href="/bo/{safe(run.run_id)}"><b>{safe(named.title)}</b></a>'
            f"<div class=muted>{safe(named.subtitle)}</div></td>"
            f"<td>{mark}</td>"
            f"<td class=num>{run.bytes_used / 1024:,.0f} KB</td></tr>"
        )
    listing = (
        "<h2>Đang làm</h2><div class=scroll><table>"
        "<tr><th>Việc<th>Trạng thái<th>Dung lượng</tr>" + "".join(rows) + "</table></div>"
    )
    return upload + listing


def _pending_count(space: Workspace, run_id: str) -> int:
    """Còn bao nhiêu việc đang chờ người duyệt, hoặc 0 nếu không đọc được."""
    try:
        return len(space.gates(run_id))
    except ServiceError:
        return 0


# --- một bộ dữ liệu: làm sạch, xem, rồi hỏi ---------------------------------------


def dataset_page(space: Workspace, run_id: str, rounds: list[tuple[str, str]]) -> str:
    """Toàn bộ một bộ dữ liệu trên một trang, theo đúng thứ tự người ta làm việc."""
    parts = [
        _cleaning_section(space, run_id),
        _preview_section(space, run_id),
        _ask_section(run_id),
        _rounds_section(space, rounds),
    ]
    return "".join(part for part in parts if part)


def _cleaning_section(space: Workspace, run_id: str) -> str:
    """Hệ thống đã xem dữ liệu và thấy gì — và chỗ để bạn nói lại."""
    gates = space.gates(run_id)
    verdicts = _verdicts(space, run_id)

    if not gates:
        if verdicts:
            body = "".join(f"<li>{safe(line)}</li>" for line in verdicts)
            return f"<h2>Làm sạch</h2><div class=card><ul>{body}</ul></div>"
        return ""

    blocks = ["<h2>Làm sạch — đang chờ bạn</h2>"]
    if verdicts:
        blocks.append(
            "<div class=card><b>Hệ thống đã xem dữ liệu:</b><ul>"
            + "".join(f"<li>{safe(line)}</li>" for line in verdicts)
            + "</ul></div>"
        )

    for gate in gates:
        options = "".join(
            "<li><label>"
            f'<input type=checkbox name=chon value="{safe(option.option_id)}" checked> '
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
            "<label>Muốn làm sạch thêm? Ghi ở đây, mỗi dòng một yêu cầu — "
            "<code>tên_luật:cột1,cột2</code></label>"
            '<textarea name=them placeholder="trim_whitespace:ten_khach&#10;'
            'replace_sentinel_with_null:ghi_chu"></textarea>'
            "<button class=go>Đồng ý và làm sạch</button></form></div>"
        )
    return "".join(blocks)


def _verdicts(space: Workspace, run_id: str) -> list[str]:
    """Những gì hệ thống thấy khi nhìn vào dữ liệu.

    Vẫn hiện sau khi đã duyệt: đó mới là lúc người ta hỏi rốt cuộc hệ thống
    đã làm gì với dữ liệu của mình.
    """
    try:
        return list(space.examination(run_id))
    except ServiceError:
        return []


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


def _ask_section(run_id: str) -> str:
    """Chỗ đặt câu hỏi. Lý do cả trang này tồn tại."""
    return (
        "<h2>Hỏi</h2>"
        f'<form class=stack method=post action="/bo/{safe(run_id)}/hoi">'
        '<textarea name=cau_hoi required placeholder="Ví dụ: Kênh nào có doanh thu cao nhất, '
        'và thấp nhất?"></textarea>'
        "<button class=go>Gửi câu hỏi</button></form>"
        "<p class=muted>Hỏi bao nhiêu lần cũng được. Mỗi câu trả lời đều kèm nguồn "
        "của từng con số.</p>"
    )


def _rounds_section(space: Workspace, rounds: list[tuple[str, str]]) -> str:
    """Những gì đã hỏi và đã trả lời, mới nhất trước."""
    if not rounds:
        return ""
    blocks = ["<h2>Đã hỏi</h2>"]
    for run_id, question in rounds:
        blocks.append(f"<div class=qa><div class=q>{safe(question or run_id)}</div>")
        blocks.append(_one_answer(space, run_id))
        blocks.append("</div>")
    return "".join(blocks)


def _one_answer(space: Workspace, run_id: str) -> str:
    """Một câu trả lời: kết luận, chỗ không kết luận được, và biểu đồ."""
    waiting = _pending_count(space, run_id)
    if waiting:
        return (
            f"<div class=muted>Đang chờ bạn duyệt kết luận. "
            f'<a href="/bo/{safe(run_id)}">Mở ra xem</a></div>'
        )
    answer = space.answer(run_id)
    if answer is None:
        return "<div class=muted>Chưa có câu trả lời.</div>"

    parts = []
    if answer.claims:
        parts.append(
            "<ul>" + "".join(f"<li>{safe(claim.claim)}</li>" for claim in answer.claims) + "</ul>"
        )
    if answer.unanswered:
        parts.append(
            "<div class=muted><b>Không kết luận được:</b><ul>"
            + "".join(f"<li>{safe(item)}</li>" for item in answer.unanswered)
            + "</ul></div>"
        )
    if answer.needs:
        parts.append(
            "<div class=muted><b>Cần thêm để trả lời chính xác hơn:</b><ul>"
            + "".join(f"<li>{safe(need.ask)}</li>" for need in answer.needs)
            + "</ul></div>"
        )
    for claim in answer.claims:
        if claim.chart_ref:
            name = claim.chart_ref.rsplit("/", 1)[-1]
            parts.append(f'<p><img src="/anh/{safe(name)}" alt=""></p>')
    return "".join(parts) or "<div class=muted>Không có kết luận nào.</div>"
