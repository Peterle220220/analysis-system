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

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from analysis_system.api import ServiceError, Workspace
from analysis_system.services import retention, updater
from analysis_system.services.export_answer import to_excel, to_word
from analysis_system.services.job_error import clear_error, read_error, write_error
from analysis_system.web.auth import AuthError, Credential, session_secret, stored_credential
from analysis_system.web.naming import ROUND_MARK, describe
from analysis_system.web.render import (
    analysis_page,
    builder_page,
    clean_page,
    data_page,
    dataset_page,
    home,
    page,
    safe,
    sidebar,
    sign_in,
    split_rounds,
    system_page,
)
from analysis_system.web.tree import (
    CLEAN_SUFFIX,
    Node,
    build_tree,
    read_lineage,
    write_lineage,
)

SESSION_COOKIE: Final[str] = "asys_session"
# Phiên đăng nhập nằm trong bộ nhớ, nên khởi động lại máy chủ là hết. Với một
# người dùng trên một máy thì đó là toàn bộ yêu cầu, và nó tránh được một kho
# lưu phiên mà chính nó lại phải được bảo vệ và dọn dẹp.
_SESSIONS: dict[str, str] = {}

# Tên bộ dữ liệu do người dùng đặt. Nó trở thành mã lần chạy và một phần đường
# dẫn tệp, nên chỉ nhận chữ, số và gạch dưới.
# Moi trang phai tu noi no de lam gi. Nguoi dung bi day toi mot trang trong
# ma khong biet no de lam gi thi ho khong dung, ho doan.
CLEAN_PURPOSE: Final[str] = "Dữ liệu sau khi đã làm sạch theo đúng những gì bạn duyệt. Tải về được."

ANALYSIS_PURPOSE: Final[str] = (
    "Kết quả của một câu hỏi. Dưới mỗi kết luận có chỗ hỏi tiếp về đúng kết luận đó."
)

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


# Cau tra loi con phai di tiep: dan vao mot ban trinh bay, gui cho nguoi khong
# co tai khoan, mo lai sau sau thang. Chup man hinh thi mat moi thu nam sau con
# so - canh bao, metric key, nhung gi khong xac lap duoc.
FORMATS: Final[dict[str, tuple[str, str]]] = {
    "excel": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "word": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
}


class _Held:
    """Một thứ giữ lại giữa hai request, trong bộ nhớ tiến trình này.

    Kết quả kiểm bản mới và câu báo sau khi cập nhật đều là **của lần bấm vừa
    rồi**, không phải trạng thái lâu dài của hệ thống. Ghi ra đĩa thì phải nghĩ
    chuyện dọn, chuyện cũ mèm, chuyện hai tiến trình cùng ghi — cho một câu chữ
    sống đúng vài giây.

    Mất khi khởi động lại, và điều đó **đúng**: khởi động lại xong thì câu
    "đang khởi động lại" không còn nghĩa gì nữa.
    """

    def __init__(self, empty: Any) -> None:
        self._empty = empty
        self._value = empty

    def put(self, value: Any) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value

    def take(self) -> Any:
        """Đọc một lần rồi quên - câu báo không được đứng lại sau khi tải lại trang."""
        value, self._value = self._value, self._empty
        return value


# Ket qua kiem ban moi gan nhat, va cau bao sau lan cap nhat gan nhat.
_LAST_CHECK = _Held(updater.Update())
_NOTE = _Held("")


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
            page(
                "Hệ thống phân tích dữ liệu",
                home(runs, space),
                "Đưa dữ liệu vào rồi hỏi",
                here="/",
            )
        )

    @api.get("/du-lieu", response_class=HTMLResponse)
    def data(request: Request) -> Response:
        """Moi bo du lieu, va bo nao dang o dau.

        Trang chu tron hai viec: cho tai tep len, va danh sach viec dang chay.
        Danh sach do dai dan theo moi tep moi, va cho tai len bi day xuong duoi.
        """
        if not signed_in(request):
            return to_sign_in()
        runs = [run for run in retention.runs(space.settings) if ROUND_MARK not in run.run_id]
        return HTMLResponse(
            page(
                "Dữ liệu",
                data_page(runs, space),
                "Các bộ dữ liệu đã và đang xử lý",
                here="/du-lieu",
            )
        )

    @api.get("/he-thong", response_class=HTMLResponse)
    def system(request: Request) -> Response:
        """Ban dang chay, va cho lay ban moi ve.

        Chi doc: xem lich su tai cho, khong cham toi mang. Kiem ban moi la mot
        nut rieng, vi no phai di ra Internet va co the cham.
        """
        if not signed_in(request):
            return to_sign_in()
        repo = updater.repo_root()
        return HTMLResponse(
            page(
                "Hệ thống",
                system_page(updater.current(repo), _LAST_CHECK.get(), _NOTE.take()),
                "Phiên bản đang chạy và cập nhật code mới",
                here="/he-thong",
            )
        )

    @api.post("/he-thong/kiem-tra")
    def check_updates(request: Request) -> Response:
        """Hoi kho tu xa xem co gi moi. Khong dung toi cay lam viec."""
        if not signed_in(request):
            return to_sign_in()
        _LAST_CHECK.put(updater.check(updater.repo_root()))
        return RedirectResponse("/he-thong", status_code=HTTP_303_SEE_OTHER)

    @api.post("/he-thong/cap-nhat")
    def apply_update(request: Request) -> Response:
        """Lay code moi ve roi khoi dong lai.

        Moi lop chan nam trong `updater.apply`, va deu dung TRUOC lenh ghi dau
        tien: hong thi khong co gi bi doi.
        """
        if not signed_in(request):
            return to_sign_in()
        repo = updater.repo_root()
        done = updater.apply(repo)
        if done.problem:
            _NOTE.put(f"Chưa cập nhật được: {done.problem}")
        elif not done.moved:
            _NOTE.put("Không có gì mới — đang chạy bản mới nhất.")
        else:
            _LAST_CHECK.put(updater.Update())
            _NOTE.put(f"{done.was} → {done.now}. " + updater.restart_after_reply())
        return RedirectResponse("/he-thong", status_code=HTTP_303_SEE_OTHER)

    @api.get("/bang-dieu-khien", response_class=HTMLResponse)
    def builder(request: Request) -> Response:
        if not signed_in(request):
            return to_sign_in()
        runs = [run for run in retention.runs(space.settings) if ROUND_MARK not in run.run_id]
        return HTMLResponse(
            page(
                "Dashboard",
                builder_page(runs, space),
                "Ghép các kết luận thành một báo cáo",
                here="/bang-dieu-khien",
            )
        )

    @api.post("/tai-len")
    async def upload(
        request: Request,
        background: BackgroundTasks,
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
        except OSError as error:
            return HTMLResponse(
                page("Không lưu được tệp", f"<p class=err>{safe(str(error))}</p>"), 400
            )

        # Tra trang NGAY, roi moi lam sach. Truoc day viec lam sach chay ngay
        # trong request va mat hon bon phut: trinh duyet quay vong vong roi tu
        # bo cuoc, trong khi may chu van dang lam - "toi khong biet no co dang
        # chay hay khong". Gio nguoi dung ve thang trang bo du lieu va thay
        # chi bao dang chay o do.
        clear_error(Path(space.settings.layers.runs) / name)
        background.add_task(_clean_quietly, space, target, name)
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
        rounds = _rounds_of(space, run_id)
        failed = read_error(Path(space.settings.layers.runs) / run_id)
        try:
            body = dataset_page(space, run_id, rounds)
        except ServiceError as error:
            if failed:
                # Viec chay nen hong truoc khi kip ghi duoc gi. Noi ro ly do,
                # khong tra ve mot trang 404 trong.
                return HTMLResponse(
                    page("Không đọc được tệp", f"<p class=err>{safe(failed)}</p>"), 400
                )
            return HTMLResponse(
                page("Không xem được", f"<p class=err>{safe(error.message)}</p>"), 404
            )
        if failed:
            body = (
                f"<div class=card><b class=err>Không đọc được tệp:</b> {safe(failed)}</div>" + body
            )
        aside = sidebar(_tree_for(space, run_id, rounds), here=run_id)
        return HTMLResponse(
            page(
                describe(run_id).title,
                body,
                DATASET_PURPOSE,
                aside,
                refresh=_refresh_for(space, rounds),
                here="/du-lieu",
            )
        )

    @api.get("/bo/{run_id}/sach", response_class=HTMLResponse)
    def clean_data(request: Request, run_id: str) -> Response:
        """Chỉ bản sạch, trên trang của riêng nó."""
        if not signed_in(request):
            return to_sign_in()
        rounds = _rounds_of(space, run_id)
        try:
            body = clean_page(space, run_id)
        except ServiceError as error:
            return HTMLResponse(
                page("Không xem được", f"<p class=err>{safe(error.message)}</p>"), 404
            )
        aside = sidebar(_tree_for(space, run_id, rounds), here=f"{run_id}{CLEAN_SUFFIX}")
        return HTMLResponse(
            page(
                "Dữ liệu sạch",
                body,
                CLEAN_PURPOSE,
                aside,
                refresh=_refresh_for(space, rounds),
                here="/du-lieu",
            )
        )

    @api.get("/bo/{dataset}/pt/{run_id}", response_class=HTMLResponse)
    def analysis(request: Request, dataset: str, run_id: str) -> Response:
        """Một phân tích, trên trang của riêng nó.

        Cuộn chat dài vô tận khong cho nguoi doc biet minh dang o dau, nen moi
        phan tich duoc mot trang, va cay ben trai noi no nam cho nao.
        """
        if not signed_in(request):
            return to_sign_in()
        rounds = _rounds_of(space, dataset)
        question = dict(rounds).get(run_id)
        if question is None:
            return HTMLResponse(
                page("Không xem được", "<p class=err>Không có phân tích này.</p>"), 404
            )
        body = analysis_page(space, dataset, run_id, question)
        aside = sidebar(_tree_for(space, dataset, rounds), here=run_id)
        return HTMLResponse(
            page(
                _short_title(question),
                body,
                ANALYSIS_PURPOSE,
                aside,
                refresh=_refresh_for(space, rounds),
                here="/du-lieu",
            )
        )

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

    @api.post("/bo/{dataset}/xoa-phan-tich")
    def forget_rounds(
        request: Request,
        dataset: str,
        xoa: Annotated[list[str] | None, Form()] = None,
    ) -> Response:
        """Xoa han nhung phan tich khong con can.

        Chi POST, va chi nhan ma thuoc bo dang mo - lop chan do nam trong
        `Workspace.forget_rounds`, khong phai o day: mot ma den tu trinh duyet
        khong duoc phep xoa thu cua bo khac chi vi no doan dung cai ten.
        """
        if not signed_in(request):
            return to_sign_in()
        chosen = [item for item in (xoa or []) if item]
        if not chosen:
            # Khong tich gi thi khong xoa gi. Im lang quay lai, khong bao loi:
            # khong chon gi khong phai mot loi.
            return back_to(dataset)
        # Viec dang chay thi khong xoa: no van chay tiep roi ghi lai thu muc
        # vua bi xoa, va cai con lai la mot nua luot chay khong ai doc duoc.
        busy = [item for item in chosen if space.running(item)]
        if busy:
            return HTMLResponse(
                page(
                    "Chưa xoá được",
                    "<p class=err>Có phân tích đang chạy trong số bạn chọn: "
                    f"{safe(', '.join(busy))}. Đợi nó xong rồi xoá.</p>",
                    here="/du-lieu",
                ),
                409,
            )
        try:
            space.forget_rounds(dataset, chosen)
        except ServiceError as error:
            return HTMLResponse(
                page("Không xoá được", f"<p class=err>{safe(error.message)}</p>", here="/du-lieu"),
                400,
            )
        return back_to(dataset)

    @api.post("/bo/{run_id}/boi-canh")
    def set_context(
        request: Request, run_id: str, boi_canh: Annotated[str, Form()] = ""
    ) -> Response:
        """Ghi bối cảnh cho bộ dữ liệu. Để trống cũng hợp lệ - đó là cách xoá."""
        if not signed_in(request):
            return to_sign_in()
        try:
            space.set_context(run_id, boi_canh)
        except ServiceError as error:
            return HTMLResponse(
                page("Không lưu được", f"<p class=err>{safe(error.message)}</p>"), 400
            )
        return back_to(run_id)

    @api.post("/bo/{run_id}/hoi")
    def ask(
        request: Request,
        run_id: str,
        cau_hoi: Annotated[str, Form()] = "",
        tu: Annotated[str, Form()] = "",
        luan_diem: Annotated[str, Form()] = "",
    ) -> Response:
        if not signed_in(request):
            return to_sign_in()
        if not cau_hoi.strip():
            return back_to(run_id)
        # Hoi tiep tu mot ket luan thi ket luan do di theo cau hoi, chu khong
        # chi duoc ghi lai o mot cho nguoi dung khong thay: neu khong noi ra thi
        # Manager tra loi mot cau hoi treo lo lung.
        asked = _with_context(cau_hoi.strip(), luan_diem.strip())
        try:
            report = space.ask(run_id, asked)
            if tu.strip():
                write_lineage(
                    Path(space.settings.layers.runs) / report.round_id,
                    parent=tu.strip(),
                    claim=luan_diem.strip(),
                )
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

    @api.get("/bo/{dataset}/pt/{run_id}/tai/{kind}")
    def export_answer(request: Request, dataset: str, run_id: str, kind: str) -> Response:
        if not signed_in(request):
            return to_sign_in()
        chosen = FORMATS.get(kind)
        if chosen is None:
            return Response(status_code=404)
        # Lan chay phai thuoc dung bo du lieu dang mo. Mot run_id den tu URL
        # khong duoc phep doc cau tra loi cua bo khac chi vi no doan dung ten.
        if run_id not in dict(_rounds_of(space, dataset)):
            return Response(status_code=404)
        found = space.answer(run_id)
        if found is None:
            return Response(status_code=404)
        suffix, media = chosen
        body = to_excel(found) if kind == "excel" else to_word(found)
        return Response(
            body,
            media_type=media,
            headers={"content-disposition": f'attachment; filename="{run_id}.{suffix}"'},
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


# Bao lau tai lai mot lan khi con viec dang chay. Nam giay: du de nguoi ta
# thay ket qua vua xong, va thua du xa de khong ai coi la mot vong lap.
REFRESH_SECONDS: Final[int] = 5


def _refresh_for(space: Workspace, rounds: list[tuple[str, str]]) -> int:
    """Số giây tự tải lại, hoặc 0 khi không còn gì đang chạy.

    Máy chủ quyết định, không phải trình duyệt: xong việc thì trang thôi tự
    tải, không ai phải nhớ tắt nó đi.
    """
    _, running, _ = split_rounds(space, rounds)
    return REFRESH_SECONDS if running else 0


def _clean_quietly(space: Workspace, source: Path, run_id: str) -> None:
    """Làm sạch ở chỗ không ai đang nhìn, và ghi lại nếu hỏng.

    Chạy sau khi trang đã được trả về, nên không còn request nào để trả lỗi.
    `raise` ở đây chỉ vào nhật ký máy chủ - nơi người dùng không bao giờ đọc -
    nên lỗi được ghi thành tệp cạnh lần chạy để họ quay lại còn thấy.
    """
    try:
        space.clean(source, run_id=run_id)
    except (OSError, ServiceError) as error:
        message = error.message if isinstance(error, ServiceError) else str(error)
        write_error(Path(space.settings.layers.runs) / run_id, message)


def _tree_for(space: Workspace, dataset: str, rounds: list[tuple[str, str]]) -> Node:
    """Cây việc của một bộ dữ liệu.

    Chỉ những lượt ra được kết quả. Cùng một luật với danh sách giữa trang, và
    cùng một hàm - hai bản sao của một luật là hai câu trả lời đang chờ để mâu
    thuẫn với nhau.
    """
    done, _, _ = split_rounds(space, rounds)
    runs_root = Path(space.settings.layers.runs)
    lineage = {run_id: read_lineage(runs_root / run_id) for run_id, _ in done}
    return build_tree(dataset, done, lineage)


def _with_context(question: str, claim: str) -> str:
    """Câu hỏi tiếp, mang theo kết luận nó đào sâu."""
    if not claim:
        return question
    return f"Về kết luận «{claim}» — {question}"


def _short_title(question: str, limit: int = 60) -> str:
    text = " ".join(question.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
