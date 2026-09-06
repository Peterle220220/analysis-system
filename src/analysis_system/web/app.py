"""Tầng 1: nơi người điều hành làm việc.

Mọi route ở đây gọi `Workspace` rồi trình bày cái trả về. Không route nào quyết
định gì cả: luật về cái gì được chạy, cái gì phải duyệt, cái gì được tuyên bố
đều nằm một tầng dưới, nơi chúng đã có test — và một bản sao của bất kỳ luật
nào trong số đó là một câu trả lời thứ hai đang chờ để mâu thuẫn với câu thứ
nhất.

Đó là lý do `api.py` được viết để trả về giá trị và không in gì. Dòng lệnh là
người trình bày thứ nhất; đây là người thứ hai.

Luồng làm việc, đúng như chủ hệ thống mô tả: thả tệp vào, hệ thống đọc và nói
nó thấy gì, người dùng duyệt hoặc yêu cầu thêm, xem bản sạch, rồi hỏi — hỏi
bao nhiêu lần cũng được.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from analysis_system.api import ServiceError, Workspace
from analysis_system.services import retention
from analysis_system.web.auth import AuthError, Credential, session_secret, stored_credential
from analysis_system.web.naming import ROUND_MARK, describe
from analysis_system.web.render import dataset_page, home, page, safe, sign_in

SESSION_COOKIE: Final[str] = "asys_session"
# Phiên đăng nhập nằm trong bộ nhớ, nên khởi động lại máy chủ là hết. Với một
# người dùng trên một máy thì đó là toàn bộ yêu cầu, và nó tránh được một kho
# lưu phiên mà chính nó lại phải được bảo vệ và dọn dẹp.
_SESSIONS: dict[str, str] = {}

# Tên bộ dữ liệu do người dùng đặt. Nó trở thành mã lần chạy và một phần đường
# dẫn tệp, nên chỉ nhận chữ, số và gạch dưới.
# Moi trang phai tu noi no de lam gi. Nguoi dung bi day toi mot trang trong
# ma khong biet no de lam gi thi ho khong dung, ho doan.
DATASET_PURPOSE: Final[str] = (
    "Xem hệ thống đã làm gì với dữ liệu, xem bản sạch, rồi đặt câu hỏi. "
    "Hỏi bao nhiêu lần cũng được."
)

SAFE_NAME: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9_]+")
MAX_NAME: Final[int] = 40


# Truong form khai bang Annotated, MOI THAM SO MOT DOI TUONG RIENG.
#
# Truoc day o day co ba hang so dung chung - OPTIONAL_FILE, TEXT_FIELD,
# LIST_FIELD - de tranh mot canh bao cua linter ve "goi ham trong gia tri mac
# dinh". Chung khien ca dashboard chet mot cach im lang: FastAPI ghi alias
# thang vao chinh doi tuong Form do, nen moi tham so dung chung TEXT_FIELD deu
# tro toi CUNG MOT o cua form - o dau tien duoc dang ky, la `password`.
#
# Ket qua: `gate_id`, `them`, `ten` va `cau_hoi` deu doc o `password`, luon
# rong. Bam "Dong y va lam sach" thi bao "Khong tim thay gate ''", dat ten bo du
# lieu thi ten bi bo qua, va go cau hoi thi khong co gi xay ra. Mot cai sua cho
# linter da lam hong ba chuc nang.
#
# Do duoc: gui {gate_id: "gate_t3_clean", them: ""} vao mot ham dung chung mot
# Form() thi nhan lai {gate_id: "gate_t3_clean", them: "gate_t3_clean"}; moi
# tham so mot Form() rieng thi nhan dung.
#
# Annotated la cach FastAPI khuyen dung, va no dat loi goi trong phan chu thich
# chu khong phai trong gia tri mac dinh - nen linter cung khong con gi de noi.


@dataclass(frozen=True)
class Guard:
    """Ai được phép nhìn vào đây."""

    credential: Credential
    secret: str

    def issue(self) -> str:
        """Một phiên mới cho người vừa chứng minh được họ là ai."""
        token = secrets.token_urlsafe(32)
        _SESSIONS[token] = self.secret
        return token

    def admits(self, token: str | None) -> bool:
        """True khi phiên này do chính máy chủ đang chạy cấp ra."""
        return bool(token) and _SESSIONS.get(token or "") == self.secret


def dataset_name(raw: str, filename: str) -> str:
    """Mã lần chạy cho một tệp vừa tải lên.

    Tên người dùng gõ nếu có, không thì lấy theo tên tệp. Chỉ giữ chữ, số và
    gạch dưới: cái tên này đi thẳng vào đường dẫn tệp và mã lần chạy, và một
    tên chứa dấu gạch chéo là một tên trỏ ra ngoài thư mục nó thuộc về.
    """
    chosen = (raw or Path(filename).stem or "du_lieu").strip().lower()
    cleaned = SAFE_NAME.sub("_", chosen).strip("_")[:MAX_NAME]
    return cleaned or "du_lieu"


def added_rules(text: str) -> tuple[dict[str, Any], ...]:
    """Những yêu cầu làm sạch người dùng tự ghi thêm.

    Mỗi dòng một yêu cầu, dạng `tên_luật:cột1,cột2`. Dòng trống bỏ qua. Tên
    luật sai thì `decide` từ chối — kiểm tra đó thuộc về tầng dưới, và làm lại
    ở đây là làm hai lần một việc để rồi hai bên nói khác nhau.
    """
    rules: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        entry = line.strip()
        if not entry:
            continue
        rule_id, _, columns = entry.partition(":")
        named = tuple(name.strip() for name in columns.split(",") if name.strip())
        rules.append(
            {
                "rule_id": rule_id.strip(),
                "columns": named,
                "reason": "người dùng yêu cầu trực tiếp tại cổng duyệt",
            }
        )
    return tuple(rules)


def build(workspace: Workspace | None = None, guard: Guard | None = None) -> FastAPI:
    """Dashboard, gắn với một workspace.

    Raises:
        AuthError: chưa đặt mật khẩu. Từ chối khởi động là chủ ý: một dashboard
            lên được mà không có mật khẩu thì mở toàn bộ dữ liệu cho bất kỳ ai
            tìm ra cổng.
    """
    space = workspace or Workspace()
    keeper = guard or Guard(credential=stored_credential(), secret=session_secret())
    api = FastAPI(title="Hệ thống phân tích dữ liệu", docs_url=None, redoc_url=None)

    def signed_in(request: Request) -> bool:
        return keeper.admits(request.cookies.get(SESSION_COOKIE))

    def to_sign_in() -> RedirectResponse:
        return RedirectResponse("/dang-nhap", status_code=HTTP_303_SEE_OTHER)

    def back_to(run_id: str) -> RedirectResponse:
        return RedirectResponse(f"/bo/{run_id}", status_code=HTTP_303_SEE_OTHER)

    # --- đăng nhập ---------------------------------------------------------

    @api.get("/dang-nhap", response_class=HTMLResponse)
    def sign_in_form(request: Request) -> Response:
        if signed_in(request):
            return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)
        return HTMLResponse(sign_in())

    @api.post("/dang-nhap", response_class=HTMLResponse)
    def sign_in_submit(password: Annotated[str, Form()] = "") -> Response:
        if not keeper.credential.matches(password):
            # Một câu duy nhất, không nói phần nào sai. Chỉ có một tài khoản,
            # nên "sai mật khẩu" là tất cả những gì đáng nói.
            return HTMLResponse(sign_in(error="Sai mật khẩu."), status_code=401)
        answer = RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)
        answer.set_cookie(SESSION_COOKIE, keeper.issue(), httponly=True, samesite="strict")
        return answer

    @api.post("/dang-xuat")
    def sign_out(request: Request) -> Response:
        _SESSIONS.pop(request.cookies.get(SESSION_COOKIE) or "", None)
        answer = to_sign_in()
        answer.delete_cookie(SESSION_COOKIE)
        return answer

    # --- trang chủ và tải lên ----------------------------------------------

    @api.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        if not signed_in(request):
            return to_sign_in()
        runs = [run for run in retention.runs(space.settings) if ROUND_MARK not in run.run_id]
        # (tieu de va cau noi ro trang nay de lam gi o ngay duoi)
        return HTMLResponse(
            page("Hệ thống phân tích dữ liệu", home(runs, space), "Đưa dữ liệu vào rồi hỏi")
        )

    @api.post("/tai-len")
    async def upload(
        request: Request,
        # Optional on purpose. Declared as required, FastAPI validates the body
        # - and therefore reads the uploaded file - before the handler runs, so
        # a stranger's upload is parsed before anybody checks whether they are
        # allowed to upload. The check belongs first.
        tep: Annotated[UploadFile | None, File()] = None,
        ten: Annotated[str, Form()] = "",
    ) -> Response:
        if not signed_in(request):
            return to_sign_in()
        if tep is None:
            return HTMLResponse(page("Chưa chọn tệp", "<p class=err>Hãy chọn một tệp.</p>"), 400)
        name = dataset_name(ten, tep.filename or "")
        suffix = Path(tep.filename or "").suffix
        target = Path(space.settings.layers.raw) / f"{name}{suffix}"
        try:
            target.write_bytes(await tep.read())
            space.clean(target, run_id=name)
        except (OSError, ServiceError) as error:
            message = error.message if isinstance(error, ServiceError) else str(error)
            return HTMLResponse(
                page("Không đọc được tệp", f"<p class=err>{safe(message)}</p>"), 400
            )
        return back_to(name)

    # --- một bộ dữ liệu -----------------------------------------------------

    @api.get("/bo/{run_id}", response_class=HTMLResponse)
    def dataset(request: Request, run_id: str) -> Response:
        if not signed_in(request):
            return to_sign_in()
        # Mot luot hoi khong co trang rieng. Truoc day co, va no la mot ngo cut:
        # duyet xong thi bi day toi mot trang chi co moi o nhap cau hoi, khong
        # noi minh la trang gi, khong co cau tra loi vua duyet, khong co duong
        # quay lai. Cuoc hoi dap song o trang bo du lieu, nen dua nguoi dung ve
        # dung do.
        dataset_id, mark, _ = run_id.partition(ROUND_MARK)
        if mark:
            return back_to(dataset_id)
        try:
            body = dataset_page(space, run_id, _rounds_of(space, run_id))
        except ServiceError as error:
            return HTMLResponse(
                page("Không xem được", f"<p class=err>{safe(error.message)}</p>"), 404
            )
        return HTMLResponse(page(describe(run_id).title, body, DATASET_PURPOSE))

    @api.post("/bo/{run_id}/duyet")
    def approve(
        request: Request,
        run_id: str,
        gate_id: Annotated[str, Form()] = "",
        chon: Annotated[list[str] | None, Form()] = None,
        them: Annotated[str, Form()] = "",
    ) -> Response:
        if not signed_in(request):
            return to_sign_in()
        try:
            space.approve(run_id, gate_id, tuple(chon or ()), added=added_rules(them))
            space.resume(run_id)
        except ServiceError as error:
            return HTMLResponse(
                page("Không duyệt được", f"<p class=err>{safe(error.message)}</p>"), 400
            )
        return back_to(run_id)

    @api.post("/bo/{run_id}/hoi")
    def ask(request: Request, run_id: str, cau_hoi: Annotated[str, Form()] = "") -> Response:
        if not signed_in(request):
            return to_sign_in()
        if not cau_hoi.strip():
            return back_to(run_id)
        try:
            space.ask(run_id, cau_hoi.strip())
        except ServiceError as error:
            return HTMLResponse(
                page("Không trả lời được", f"<p class=err>{safe(error.message)}</p>"), 400
            )
        return back_to(run_id)

    @api.get("/tai-ve/{run_id}")
    def download(request: Request, run_id: str) -> Response:
        if not signed_in(request):
            return to_sign_in()
        table = space.clean_table(run_id)
        if table is None:
            return Response(status_code=404)
        frame = space.table(table.uri)
        return Response(
            frame.to_csv(index=False).encode("utf-8-sig"),
            media_type="text/csv",
            headers={"content-disposition": f'attachment; filename="{run_id}_sach.csv"'},
        )

    @api.get("/anh/{name}")
    def chart(request: Request, name: str) -> Response:
        """Một biểu đồ do lần chạy sinh ra.

        Tên được đối chiếu với những gì tầng artifacts thật sự có, chứ không
        ghép thẳng vào đường dẫn: một cái tên đến từ URL không bao giờ được
        phép đi ra khỏi thư mục nó được phép đọc.
        """
        if not signed_in(request):
            return to_sign_in()
        wanted = Path(space.settings.layers.artifacts) / Path(name).name
        if wanted.suffix != ".png" or not wanted.is_file():
            return Response(status_code=404)
        return Response(wanted.read_bytes(), media_type="image/png")

    return api


def _rounds_of(space: Workspace, run_id: str) -> list[tuple[str, str]]:
    """Các lượt hỏi đặt trên bộ dữ liệu này, mới nhất trước."""
    return [
        (run.run_id, _question_of(space, run.run_id))
        for run in retention.runs(space.settings)
        if run.run_id.startswith(run_id + ROUND_MARK)
    ]


def _question_of(space: Workspace, run_id: str) -> str:
    """Câu hỏi của một lượt, đọc từ chính kế hoạch nó chạy."""
    path = Path(space.settings.layers.runs) / run_id / "plan.json"
    if not path.is_file():
        return ""
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return ""
    for task in plan.get("tasks", []):
        question = (task.get("params") or {}).get("question")
        if question:
            return str(question)
    return ""


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Chạy dashboard.

    Mặc định chỉ nghe trên máy này. Mở rộng ra ngoài cần một quyết định có ý
    thức và một cái nhìn vào thứ đứng trước nó, vì ở đây chỉ có một mật khẩu và
    không có gì đếm số lần đoán.

    Raises:
        AuthError: chưa cấu hình mật khẩu.
    """
    import uvicorn

    uvicorn.run(build(), host=host, port=port, log_level="warning")


__all__ = ["AuthError", "Guard", "build", "serve"]
