"""Dung HTML cho dashboard. Khong quyet dinh gi, chi trinh bay.

Hand-written strings rather than a template engine, for one reason: a template
engine is a dependency, and this is four pages. If it grows past that, the
right move is Jinja and not more of this.

Everything that came from data goes through `safe()` first. A run id, a column
name, a finding - all of them originate outside this system, and a dashboard
that pastes them into a page unescaped is a dashboard that runs whatever the
data says.
"""

from __future__ import annotations

from html import escape
from typing import Any

from analysis_system.api import ServiceError, Workspace
from analysis_system.services.retention import RunInfo

STYLE = """
:root { color-scheme: light dark; }
body { font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 2rem;
       max-width: 70rem; margin-inline: auto; }
h1 { font-size: 1.4rem; margin: 0 0 1.5rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .6rem; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid #8883; }
th { font-weight: 600; font-size: .85rem; text-transform: uppercase; opacity: .7; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
a { color: inherit; }
.err { color: #c0392b; }
.tag { font-size: .75rem; padding: .1rem .45rem; border-radius: .5rem;
       border: 1px solid #8886; }
.wait { border-color: #d68910; color: #d68910; }
form.signin { max-width: 20rem; margin: 6rem auto; }
input { width: 100%; padding: .5rem; font: inherit; margin: .4rem 0 1rem; }
button { padding: .5rem 1rem; font: inherit; cursor: pointer; }
ul { padding-left: 1.2rem; }
img { max-width: 100%; border: 1px solid #8883; }
.muted { opacity: .65; font-size: .9rem; }
"""


def safe(value: Any) -> str:
    """Anything, as text that cannot become markup."""
    return escape(str(value), quote=True)


def page(title: str, body: str) -> str:
    """One page, wrapped in the same shell as every other."""
    return (
        "<!doctype html><html lang=vi><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{safe(title)}</title><style>{STYLE}</style></head><body>"
        f'<h1><a href="/">Analysis System</a> · {safe(title)}</h1>{body}'
        '<form method=post action="/dang-xuat" style="margin-top:3rem">'
        "<button>Dang xuat</button></form>"
        "</body></html>"
    )


def sign_in(error: str = "") -> str:
    """The one page anybody may see without being signed in."""
    warning = f"<p class=err>{safe(error)}</p>" if error else ""
    return page(
        "Dang nhap",
        f'{warning}<form class=signin method=post action="/dang-nhap">'
        "<label>Mat khau</label>"
        "<input type=password name=password autofocus autocomplete=current-password>"
        "<button>Vao</button></form>",
    )


def runs_table(runs: list[RunInfo], space: Workspace) -> str:
    """Every run, and which of them are waiting on a person.

    The waiting ones are why this page exists: a run that has paused for an
    approval is doing nothing until somebody looks, and on a terminal that
    fact was only visible to whoever remembered to check.
    """
    if not runs:
        return "<p class=muted>Chua co lan chay nao.</p>"
    rows = []
    for run in runs:
        waiting = _pending_count(space, run.run_id)
        mark = f'<span class="tag wait">cho duyet {waiting}</span>' if waiting else ""
        rows.append(
            f'<tr><td><a href="/lan-chay/{safe(run.run_id)}">{safe(run.run_id)}</a></td>'
            f"<td>{safe(run.phase)} {mark}</td>"
            f"<td class=num>{run.tasks}</td>"
            f"<td class=num>{run.bytes_used / 1024:,.0f} KB</td>"
            f"<td class=num>{run.age_days} ngay</td></tr>"
        )
    return (
        "<table><tr><th>Lan chay<th>Trang thai<th>Task<th>Dung luong<th>Tuoi</tr>"
        + "".join(rows)
        + "</table>"
    )


def _pending_count(space: Workspace, run_id: str) -> int:
    """How many approvals this run is waiting on, or zero if it cannot say."""
    try:
        return len(space.gates(run_id))
    except ServiceError:
        return 0


def run_detail(space: Workspace, run_id: str) -> str:
    """One run: what it is waiting for, what it concluded, what it would not say.

    Raises:
        ServiceError: there is no such run.
    """
    parts = [_gates_section(space, run_id), _answer_section(space, run_id)]
    return "".join(part for part in parts if part) or "<p class=muted>Chua co gi de xem.</p>"


def _gates_section(space: Workspace, run_id: str) -> str:
    gates = space.gates(run_id)
    if not gates:
        return ""
    blocks = []
    for gate in gates:
        options = "".join(
            f"<li><code>{safe(option.option_id)}</code> — {safe(option.label)}"
            + (f"<div class=muted>{safe(option.detail)}</div>" if option.detail else "")
            + "</li>"
            for option in gate.options
        )
        blocks.append(
            f"<h2>{safe(gate.title)} <span class='tag wait'>cho duyet</span></h2>"
            f"<p>{safe(gate.question)}</p><ul>{options}</ul>"
            f'<form method=post action="/lan-chay/{safe(run_id)}/duyet">'
            f'<input type=hidden name=gate_id value="{safe(gate.gate_id)}">'
            "<label>Duyet nhung muc nay (ngan cach bang dau phay)</label>"
            "<input name=chon>"
            "<label>Tu choi nhung muc nay</label>"
            "<input name=tu_choi>"
            "<button>Ghi quyet dinh</button></form>"
        )
    return "".join(blocks)


def _answer_section(space: Workspace, run_id: str) -> str:
    answer = space.answer(run_id)
    if answer is None:
        return ""
    claims = "".join(f"<li>{safe(claim.claim)}</li>" for claim in answer.claims)
    needs = "".join(
        f"<li>{safe(need.ask)}<div class=muted>{safe(need.unlocks)}</div></li>"
        for need in answer.needs
    )
    charts = "".join(
        f'<p><img src="/anh/{safe(claim.chart_ref.rsplit("/", 1)[-1])}" alt=""></p>'
        for claim in answer.claims
        if claim.chart_ref
    )
    blocks = [f"<h2>Ket luan</h2><ul>{claims}</ul>" if claims else ""]
    if answer.unanswered:
        gaps = "".join(f"<li>{safe(item)}</li>" for item in answer.unanswered)
        # Shown as prominently as the conclusions. A dashboard that lists what
        # was found and hides what could not be is the failure this whole
        # system is arranged against.
        blocks.append(f"<h2>Khong ket luan duoc</h2><ul>{gaps}</ul>")
    if needs:
        blocks.append(f"<h2>Manager hoi lai</h2><ul>{needs}</ul>")
    if charts:
        blocks.append(f"<h2>Bieu do</h2>{charts}")
    return "".join(blocks)
