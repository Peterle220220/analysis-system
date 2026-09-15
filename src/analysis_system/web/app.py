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
import time
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Final

from fastapi import BackgroundTasks, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from analysis_system.api import ServiceError, Workspace
from analysis_system.core import updater
from analysis_system.core.job_error import clear_error, read_error, write_error
from analysis_system.core.settings import resolve
from analysis_system.services.bi_query import BiQuery, BiQueryError, field_values
from analysis_system.services.bi_query import run_query as run_bi_query
from analysis_system.services.bi_schema import FileSchema, schema_of_file
from analysis_system.services.bi_views import (
    ViewError,
    ViewState,
    delete_view,
    list_views,
    save_view,
)
from analysis_system.services.dashboards import (
    DashboardError,
    Widget,
    WidgetDraft,
    add_widget,
    create_dashboard,
    delete_dashboard,
    get_dashboard,
    list_dashboards,
    replace_dashboard,
)
from analysis_system.services.dataset_labels import display_label, record_label
from analysis_system.services.dataset_origin import record_origin
from analysis_system.services.export_answer import to_excel, to_word
from analysis_system.services.glossary_draft import duplicate_meanings
from analysis_system.services.group_means import with_group_means
from analysis_system.web.auth import AuthError, Credential, session_secret, stored_credential
from analysis_system.web.tree import (
    write_lineage,
)
from analysis_system.web.view import (
    clean_payload,
    dataset_payload,
    display_words,
    gate_report,
    round_payload,
    round_state,
    round_status_payload,
    rows_payload,
    run_report,
    session_payload,
)
from analysis_system.web.view import (
    dashboard as dashboard_payload,
)
from analysis_system.web.view import (
    data_page as data_payload,
)
from analysis_system.web.view import (
    home as home_payload,
)
from analysis_system.web.view import (
    round_runs as payload_round_runs,
)
from analysis_system.web.view import (
    system as system_payload,
)

SESSION_COOKIE: Final[str] = "asys_session"
# Phiên đăng nhập nằm trong bộ nhớ, nên khởi động lại máy chủ là hết. Với một
# người dùng trên một máy thì đó là toàn bộ yêu cầu, và nó tránh được một kho
# lưu phiên mà chính nó lại phải được bảo vệ và dọn dẹp.
_SESSIONS: dict[str, str] = {}

# Tên bộ dữ liệu do người dùng đặt. Nó trở thành mã lần chạy và một phần đường
# dẫn tệp, nên chỉ nhận chữ, số và gạch dưới.
SAFE_NAME: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9_]+")
SAFE_ID: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9_]+$")
MAX_NAME: Final[int] = 40
MAX_ID: Final[int] = 128
# Gioi han kich thuoc tep tai len. Phai KHOP voi middlewareClientMaxBodySize trong
# frontend/next.config.ts va MAX_UPLOAD_BYTES trong frontend/src/lib/api.ts.
# Khong co gioi han thi mot tep lon bi doc tron vao bo nho; con o tang proxy, mot
# tep vuot muc bi cat cut roi treo toi khi het gio - va bao sai nguyen nhan.
MAX_UPLOAD_BYTES: Final[int] = 200 * 1024 * 1024
REQUEST_KEY: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
REQUEST_STALE_SECONDS: Final[int] = 3600


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
    chosen = _without_marks((raw or Path(filename).stem or "du_lieu").strip()).lower()
    cleaned = SAFE_NAME.sub("_", chosen).strip("_")[:MAX_NAME]
    return cleaned or "du_lieu"


def _without_marks(text: str) -> str:
    """Bỏ dấu tiếng Việt: "báo cáo" thành "bao cao", "đ" thành "d".

    Trước đây mọi chữ có dấu bị lọc thành "_", nên "báo cáo tài chính" thành
    "b_o_c_o_t_i_ch_nh": mất chữ, và tên không còn đọc được.
    """
    plain = unicodedata.normalize("NFD", text)
    kept = "".join(char for char in plain if unicodedata.category(char) != "Mn")
    return kept.replace("đ", "d").replace("Đ", "D")


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

    # --- JSON: phiên (cho giao diện Next.js) --------------------------------
    # Giao dien Next dang nhap qua day. Phien la cookie do Guard cap, nam trong bo nho.

    @api.get("/api/session")
    def api_session(request: Request) -> Response:
        """Trạng thái phiên, để trang biết vẽ màn hình nào mà không cần redirect."""
        return JSONResponse(session_payload(signed_in(request)))

    @api.post("/api/session")
    async def api_session_sign_in(request: Request) -> Response:
        """Đăng nhập bằng JSON: đúng thì cấp cookie, sai thì 401 kèm lỗi."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        password = str(body.get("password") or "")
        if not keeper.credential.matches(password):
            # Cùng câu duy nhất như form HTML, để không có hai lời giải thích.
            return JSONResponse(
                session_payload(False) | {"error": "Sai mật khẩu."}, status_code=401
            )
        answer = JSONResponse(session_payload(True))
        answer.set_cookie(SESSION_COOKIE, keeper.issue(), httponly=True, samesite="strict")
        return answer

    @api.delete("/api/session")
    def api_session_sign_out(request: Request) -> Response:
        """Đăng xuất bằng JSON: xoá phiên trong bộ nhớ và cookie trên trình duyệt."""
        _SESSIONS.pop(request.cookies.get(SESSION_COOKIE) or "", None)
        answer = JSONResponse(session_payload(False))
        answer.delete_cookie(SESSION_COOKIE)
        return answer

    def api_requires_sign_in(request: Request) -> JSONResponse | None:
        """Trả lỗi JSON nếu chưa đăng nhập, hoặc None khi được phép đọc."""
        if signed_in(request):
            return None
        return JSONResponse(
            {
                "error": {
                    "code": "unauthorized",
                    "message": "Bạn cần đăng nhập để xem bảng điều khiển.",
                    "hint": "Đăng nhập rồi thử lại.",
                }
            },
            status_code=401,
        )

    @api.get("/api/health")
    def api_health() -> JSONResponse:
        """Liveness check không cần đăng nhập, cho proxy và service."""
        return JSONResponse({"ok": True, "service": "analysis-system"})

    @api.get("/api/home")
    def api_home(request: Request) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        return JSONResponse(home_payload(space))

    @api.get("/api/data")
    def api_data(request: Request) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        return JSONResponse(data_payload(space))

    @api.get("/api/dashboard")
    def api_dashboard(request: Request) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        return JSONResponse(dashboard_payload(space))

    @api.get("/api/system")
    def api_system(request: Request) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        repo = updater.repo_root()
        return JSONResponse(
            system_payload(
                updater.current(repo), _LAST_CHECK.get(), _NOTE.get(), updater.stale(repo)
            )
        )

    @api.post("/api/system/check")
    def api_check_updates(request: Request) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        repo = updater.repo_root()
        _LAST_CHECK.put(updater.check(repo))
        return JSONResponse(
            system_payload(
                updater.current(repo), _LAST_CHECK.get(), _NOTE.get(), updater.stale(repo)
            )
        )

    @api.post("/api/system/apply")
    def api_apply_update(request: Request) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        repo = updater.repo_root()
        done = updater.apply(repo)
        if done.problem:
            return api_error("update_failed", done.problem, 409)
        _LAST_CHECK.put(updater.Update())
        _NOTE.put(f"{done.was} → {done.now}. " + updater.restart_after_reply())
        return JSONResponse(
            system_payload(
                updater.current(repo), _LAST_CHECK.get(), _NOTE.get(), updater.stale(repo)
            )
        )

    def api_error(code: str, message: str, status_code: int, hint: str = "") -> JSONResponse:
        body: dict[str, Any] = {"code": code, "message": message}
        if hint:
            body["hint"] = hint
        return JSONResponse({"error": body}, status_code=status_code)

    def api_id_is_safe(value: str) -> bool:
        """URL ids may name run directories, so reject path syntax explicitly."""
        return bool(value) and len(value) <= MAX_ID and SAFE_ID.fullmatch(value) is not None

    def api_invalid_id(value: str) -> JSONResponse:
        return api_error("invalid_id", f"Mã không hợp lệ: {value!r}.", 400)

    def api_dataset_is_known(dataset: str) -> bool:
        """A safe id is not automatically an existing dataset."""
        run_dir = Path(space.settings.layers.runs) / dataset
        if run_dir.is_dir() or read_error(run_dir):
            return True
        raw_root = Path(space.settings.layers.raw)
        return any(path.is_file() for path in raw_root.glob(f"{dataset}.*"))

    def api_require_dataset(dataset: str) -> JSONResponse | None:
        if api_dataset_is_known(dataset):
            return None
        return api_error("dataset_not_found", "Không có bộ dữ liệu này.", 404)

    async def api_body(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except Exception:
            return {}
        return body if isinstance(body, dict) else {}

    def api_request_key(raw: Any) -> str:
        """A client-generated key used to replay an accepted mutation safely."""
        value = str(raw or "").strip()
        return value if REQUEST_KEY.fullmatch(value) else ""

    def api_claim_request(
        operation: str, key: str
    ) -> tuple[Path | None, dict[str, Any] | None, bool]:
        """Claim a mutation key, or return its saved response/in-progress state."""
        if not key:
            return None, None, False
        root = Path(space.settings.layers.artifacts) / ".api_requests"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{operation}_{key}.json"
        try:
            path.open("x", encoding="utf-8").close()
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > REQUEST_STALE_SECONDS:
                    path.unlink()
                    path.open("x", encoding="utf-8").close()
                else:
                    stored = json.loads(path.read_text(encoding="utf-8"))
                    if stored.get("status") == "done" and isinstance(stored.get("payload"), dict):
                        return None, stored["payload"], False
                    return None, None, True
            except (OSError, ValueError, FileExistsError):
                return None, None, True
        path.write_text(json.dumps({"status": "processing"}), encoding="utf-8")
        return path, None, False

    def api_finish_request(path: Path | None, payload: dict[str, Any]) -> None:
        if path is None:
            return
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"status": "done", "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(path)

    def api_release_request(path: Path | None) -> None:
        if path is None:
            return
        with suppress(FileNotFoundError):
            path.unlink()

    @api.post("/api/datasets")
    async def api_upload(
        request: Request,
        background: BackgroundTasks,
        tep: Annotated[UploadFile | None, File()] = None,
        ten: Annotated[str, Form()] = "",
        client_request_id: Annotated[str, Form()] = "",
        nguon: Annotated[str, Form()] = "",
    ) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if tep is None:
            return api_error("missing_file", "Hãy chọn một tệp.", 400)
        too_large = _too_large(tep)
        if too_large:
            return api_error("file_too_large", too_large, 413)
        raw_key = str(client_request_id or "").strip()
        if raw_key and not REQUEST_KEY.fullmatch(raw_key):
            return api_error("invalid_request_id", "Mã request không hợp lệ.", 400)
        request_path, replay, in_progress = api_claim_request("upload", raw_key)
        if replay is not None:
            return JSONResponse(replay, status_code=202)
        if in_progress:
            return api_error("request_in_progress", "Yêu cầu này đang được xử lý.", 409)
        name = dataset_name(ten, tep.filename or "")
        suffix = Path(tep.filename or "").suffix
        target = Path(space.settings.layers.raw) / f"{name}{suffix}"
        try:
            target.write_bytes(await tep.read())
        except OSError as error:
            api_release_request(request_path)
            return api_error("upload_failed", "Không lưu được tệp.", 400, str(error))
        clear_error(Path(space.settings.layers.runs) / name)
        # Ghi loi vao (trang Tu phan tich hay muc Du lieu). Ghi hong thi bo nay
        # chi bi xep vao nhom muc Du lieu; viec tai len van tiep tuc.
        with suppress(OSError):
            record_origin(Path(space.settings.layers.runs), name, nguon)
        # Ma bo bo dau cho duong dan; ten hien thi giu dung chu nguoi dung go.
        with suppress(OSError):
            record_label(
                Path(space.settings.layers.runs), name, display_label(ten, tep.filename or "")
            )
        background.add_task(_clean_quietly, space, target, name)
        payload = {"dataset_id": name, "status": "running", "running": True}
        api_finish_request(request_path, payload)
        return JSONResponse(payload, status_code=202)

    @api.get("/api/datasets/{dataset}/status")
    def api_dataset_status(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        failed = read_error(Path(space.settings.layers.runs) / dataset)
        starting = not (
            Path(space.settings.layers.runs) / dataset
        ).is_dir() and api_dataset_is_known(dataset)
        try:
            running = space.running(dataset) or starting
            gates = [] if starting else [gate_report(gate) for gate in space.gates(dataset)]
            state = data_payload(space)
            found = next((item for item in state["datasets"] if item["run_id"] == dataset), None)
        except ServiceError as error:
            return api_error("dataset_unreadable", error.message, 404, error.hint)
        if found is None and not failed and not starting:
            return api_error("dataset_not_found", "Không có bộ dữ liệu này.", 404)
        phase = (
            str(found.get("phase") or "")
            if found
            else "RUNNING"
            if starting
            else "FAILED"
            if failed
            else "UNKNOWN"
        )
        return JSONResponse(
            {
                "dataset_id": dataset,
                "phase": phase,
                "running": running,
                "state": found["state"]
                if found
                else {"key": "running", "label": "đang bắt đầu làm sạch"}
                if starting
                else {"key": "failed", "label": "không đọc được"},
                "gates": gates,
                "error": failed,
            }
        )

    @api.get("/api/datasets/{dataset}")
    def api_dataset(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        try:
            payload = dataset_payload(space, dataset)
        except ServiceError as error:
            return api_error("dataset_unreadable", error.message, 404, error.hint)
        failed = read_error(Path(space.settings.layers.runs) / dataset)
        if failed:
            payload["error"] = failed
        return JSONResponse(payload)

    @api.get("/api/datasets/{dataset}/clean")
    def api_clean(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        try:
            return JSONResponse(clean_payload(space, dataset))
        except ServiceError as error:
            return api_error("clean_unreadable", error.message, 404, error.hint)

    @api.get("/api/datasets/{dataset}/rows")
    def api_rows(
        request: Request, dataset: str, which: str = "clean", offset: int = 0, limit: int = 200
    ) -> Response:
        """Mot khoi dong cua bang, cho bang cuon ao: chi xin phan dang can xem."""
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        # Chi hai bang co ten, anh xa ngay tai day: trinh duyet khong bao gio
        # gui duoc mot duong dan tep tuy y.
        if which not in ("clean", "staged"):
            return api_error("unknown_table", "Chỉ có bảng 'clean' hoặc 'staged'.", 400, "")
        try:
            table = space.clean_table(dataset) if which == "clean" else space.staged_table(dataset)
            if table is None:
                return api_error("table_missing", "Chưa có bảng này.", 404, "")
            return JSONResponse(rows_payload(space, table, offset, limit))
        except ServiceError as error:
            return api_error("table_unreadable", error.message, 404, error.hint)
        except (OSError, ValueError) as error:
            return api_error("table_unreadable", str(error), 404, "")

    # --- Tu phan tich (keo tha) -------------------------------------------------
    # Moi con so o day do DuckDB tinh tu bang sach; khong buoc nao goi model.

    def bi_source(request: Request, dataset: str) -> tuple[Path, FileSchema] | Response:
        """Tep Parquet cua bang sach va schema cua no, hoac mot phan hoi loi."""
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        try:
            table = space.clean_table(dataset)
            if table is None:
                return api_error(
                    "clean_not_ready",
                    "Bộ dữ liệu này chưa có bảng sạch. Hãy duyệt bước làm sạch trước.",
                    409,
                    "",
                )
            source = resolve(table.uri, space.settings)
            return source, schema_of_file(source)
        except (OSError, ValueError) as error:
            return api_error("clean_unreadable", str(error), 404, "")

    @api.get("/api/bi/{dataset}/schema")
    def api_bi_schema(request: Request, dataset: str) -> Response:
        """Cac cot cua bang sach, da chia Dimension/Measure, cho thanh ben keo tha."""
        found = bi_source(request, dataset)
        if isinstance(found, Response):
            return found
        _, schema = found
        return JSONResponse(
            {
                "dataset_id": dataset,
                "rows": schema.rows,
                "fields": [field.as_dict() for field in schema.fields],
            }
        )

    @api.get("/api/bi/{dataset}/values")
    def api_bi_values(request: Request, dataset: str, field: str = "") -> Response:
        """Gia tri de chon trong bo loc cua mot cot."""
        found = bi_source(request, dataset)
        if isinstance(found, Response):
            return found
        source, schema = found
        chosen = next((item for item in schema.fields if item.name == field), None)
        if chosen is None:
            return api_error("unknown_field", f"Bảng không có cột '{field}'.", 404, "")
        try:
            return JSONResponse(field_values(source, chosen))
        except BiQueryError as error:
            return api_error("bi_failed", str(error), 400, "")

    @api.post("/api/bi/{dataset}/query")
    async def api_bi_query(request: Request, dataset: str) -> Response:
        """Mot cau hinh keo tha thanh mot ket qua san de ve."""
        found = bi_source(request, dataset)
        if isinstance(found, Response):
            return found
        source, schema = found
        try:
            query = BiQuery.model_validate(await request.json())
        except ValueError as error:
            return api_error("bad_query", "Cấu hình kéo thả không hợp lệ.", 400, str(error)[:300])
        try:
            return JSONResponse(run_bi_query(source, query, list(schema.fields)))
        except BiQueryError as error:
            return api_error("bi_failed", str(error), 400, "")

    # Ban tu phan tich da luu: moi ban mot cau hinh keo tha co ten, theo bo du lieu.
    view_key = re.compile(r"[0-9a-f]{12}")

    def views_dir(request: Request, dataset: str) -> Path | Response:
        """Thu muc cua bo du lieu (noi luu cac ban), hoac mot phan hoi loi."""
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        return Path(space.settings.layers.runs) / dataset

    @api.get("/api/bi/{dataset}/views")
    def api_bi_views(request: Request, dataset: str) -> Response:
        found = views_dir(request, dataset)
        if isinstance(found, Response):
            return found
        views = [view.model_dump() for view in list_views(found)]
        return JSONResponse({"dataset_id": dataset, "views": views})

    @api.post("/api/bi/{dataset}/views")
    async def api_bi_save_view(request: Request, dataset: str) -> Response:
        """Tao ban moi (khong co `id`) hoac ghi de dung ban co `id`."""
        found = views_dir(request, dataset)
        if isinstance(found, Response):
            return found
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("can mot object")
            state = ViewState.model_validate(body.get("state"))
        except ValueError as error:
            return api_error("bad_view", "Bản phân tích không hợp lệ.", 400, str(error)[:300])
        view_id = body.get("id") or None
        if view_id is not None and (
            not isinstance(view_id, str)
            or not view_key.fullmatch(view_id)
            or all(view.id != view_id for view in list_views(found))
        ):
            return api_error("unknown_view", "Không có bản phân tích này.", 404, "")
        try:
            saved = save_view(found, str(body.get("name") or ""), state, view_id=view_id)
        except ViewError as error:
            return api_error("bad_view", str(error), 400, "")
        return JSONResponse(saved.model_dump(), status_code=201 if view_id is None else 200)

    @api.delete("/api/bi/{dataset}/views/{view_id}")
    def api_bi_delete_view(request: Request, dataset: str, view_id: str) -> Response:
        found = views_dir(request, dataset)
        if isinstance(found, Response):
            return found
        if not view_key.fullmatch(view_id) or not delete_view(found, view_id):
            return api_error("unknown_view", "Không có bản phân tích này.", 404, "")
        return JSONResponse({"deleted": view_id})

    # --- Dashboard: trang trinh bay ghep widget tu ca hai luong ----------------
    # Widget chi giu nguon (cau hinh keo tha, luot hoi + so thu tu ket luan, van
    # ban); trang tinh lai moi lan mo. So ghi o goc thu muc runs.

    def boards_root() -> Path:
        return Path(space.settings.layers.runs)

    def board_missing() -> Response:
        return api_error("unknown_dashboard", "Không có Dashboard này.", 404, "")

    @api.get("/api/dashboards")
    def api_dashboards(request: Request) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        boards = [
            {
                "id": board.id,
                "name": board.name,
                "widgets": len(board.widgets),
                "updated_at": board.updated_at,
            }
            for board in list_dashboards(boards_root())
        ]
        return JSONResponse({"dashboards": boards})

    @api.post("/api/dashboards")
    async def api_create_dashboard(request: Request) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        try:
            body = await request.json()
            name = str(body.get("name") or "") if isinstance(body, dict) else ""
            board = create_dashboard(boards_root(), name)
        except DashboardError as error:
            return api_error("bad_dashboard", str(error), 400, "")
        except ValueError:
            return api_error("bad_dashboard", "Yêu cầu không hợp lệ.", 400, "")
        return JSONResponse(board.model_dump(), status_code=201)

    @api.get("/api/dashboards/{board_id}")
    def api_dashboard_one(request: Request, board_id: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        board = get_dashboard(boards_root(), board_id) if view_key.fullmatch(board_id) else None
        return board_missing() if board is None else JSONResponse(board.model_dump())

    @api.put("/api/dashboards/{board_id}")
    async def api_save_dashboard(request: Request, board_id: str) -> Response:
        """Ghi lai ten va toan bo widget: doi cho, doi co, sua chu, xoa widget."""
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not view_key.fullmatch(board_id):
            return board_missing()
        try:
            body = await request.json()
            if not isinstance(body, dict) or not isinstance(body.get("widgets"), list):
                raise ValueError("can name va widgets")
            widgets = [Widget.model_validate(item) for item in body["widgets"]]
        except ValueError as error:
            return api_error("bad_dashboard", "Dashboard không hợp lệ.", 400, str(error)[:300])
        try:
            board = replace_dashboard(boards_root(), board_id, str(body.get("name") or ""), widgets)
        except DashboardError as error:
            missing = get_dashboard(boards_root(), board_id) is None
            return board_missing() if missing else api_error("bad_dashboard", str(error), 400, "")
        return JSONResponse(board.model_dump())

    @api.post("/api/dashboards/{board_id}/widgets")
    async def api_pin_widget(request: Request, board_id: str) -> Response:
        """Ghim: them mot widget vao cuoi luoi cua Dashboard nay."""
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not view_key.fullmatch(board_id) or get_dashboard(boards_root(), board_id) is None:
            return board_missing()
        try:
            draft = WidgetDraft.model_validate(await request.json())
        except ValueError as error:
            return api_error("bad_widget", "Widget không hợp lệ.", 400, str(error)[:300])
        try:
            board = add_widget(boards_root(), board_id, draft)
        except DashboardError as error:
            return api_error("bad_widget", str(error), 400, "")
        return JSONResponse(board.model_dump(), status_code=201)

    @api.delete("/api/dashboards/{board_id}")
    def api_delete_dashboard(request: Request, board_id: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not view_key.fullmatch(board_id) or not delete_dashboard(boards_root(), board_id):
            return board_missing()
        return JSONResponse({"deleted": board_id})

    @api.put("/api/datasets/{dataset}/context")
    async def api_set_context(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        body = await api_body(request)
        try:
            saved = space.set_context(dataset, str(body.get("context") or ""))
        except ServiceError as error:
            return api_error("context_failed", error.message, 400, error.hint)
        return JSONResponse({"dataset_id": dataset, "context": saved})

    @api.post("/api/datasets/{dataset}/glossary-draft")
    def api_draft_glossary(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        try:
            lines, dropped = space.draft_glossary(dataset)
        except ServiceError as error:
            return api_error("glossary_failed", error.message, 400, error.hint)
        # MANG cac dong, dung kieu ban Next cho (). Truoc day tra
        # nguyen mot chuoi - dang trang Python can de do vao o soan - va trang Next
        # goi  tren chuoi, vo o JavaScript, roi bao chung chung "Khong soan
        # duoc chu giai" trong khi model da soan xong du 96 dong.
        return JSONResponse(
            {
                "dataset_id": dataset,
                "lines": lines.splitlines(),
                "dropped": dropped,
                "conflicts": duplicate_meanings(lines),
            }
        )

    @api.get("/api/datasets/{dataset}/glossary")
    def api_glossary(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        # Ban da luu, doc lai moi lan mo trang. Truoc day trang Next khong doc
        # lai no: quay lai chi con nut soan nhap, va soan lai la noi vao ban cu.
        try:
            rows = space.glossary_table(dataset)
        except ServiceError as error:
            return api_error("glossary_unreadable", error.message, 404, error.hint)
        return JSONResponse(_glossary_payload(dataset, rows))

    @api.put("/api/datasets/{dataset}/glossary")
    async def api_set_glossary(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        body = await api_body(request)
        raw = body.get("rows")
        if not isinstance(raw, list):
            return api_error("invalid_glossary", "Bảng chú giải không hợp lệ.", 400)
        rows = [
            (str(item.get("column") or ""), str(item.get("meaning") or ""))
            for item in raw
            if isinstance(item, dict)
        ]
        # Chi dong cua cot phan loai mang o Nhan gia tri. Khong dong nao mang no
        # thi nhan da khai giu nguyen.
        values = {
            str(item.get("column") or ""): str(item.get("values") or "")
            for item in raw
            if isinstance(item, dict) and "values" in item
        }
        try:
            saved, moved = space.set_glossary(dataset, rows, values or None)
        except ServiceError as error:
            return api_error("glossary_failed", error.message, 400, error.hint)
        payload = _glossary_payload(dataset, space.glossary_table(dataset))
        return JSONResponse({**payload, "moved": moved, "conflicts": duplicate_meanings(saved)})

    @api.post("/api/datasets/{dataset}/approve")
    async def api_approve(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        body = await api_body(request)
        gate_id = str(body.get("gate_id") or "")
        chosen = body.get("chosen") or body.get("approved") or []
        if not isinstance(chosen, list):
            return api_error("invalid_approval", "Danh sách lựa chọn không hợp lệ.", 400)
        raw_added = body.get("added_rules") or body.get("added") or ""
        if isinstance(raw_added, str):
            extra = added_rules(raw_added)
        elif isinstance(raw_added, list):
            extra = tuple(item for item in raw_added if isinstance(item, dict))
        else:
            return api_error("invalid_approval", "Quy tắc thêm không hợp lệ.", 400)
        raw_key = str(body.get("client_request_id") or body.get("request_id") or "").strip()
        if raw_key and not REQUEST_KEY.fullmatch(raw_key):
            return api_error("invalid_request_id", "Mã request không hợp lệ.", 400)
        request_path, replay, in_progress = api_claim_request("approve_dataset_" + dataset, raw_key)
        if replay is not None:
            return JSONResponse(replay)
        if in_progress:
            return api_error("request_in_progress", "Yêu cầu này đang được xử lý.", 409)
        try:
            space.approve(dataset, gate_id, tuple(str(item) for item in chosen), added=extra)
            report = space.resume(dataset)
        except ServiceError as error:
            api_release_request(request_path)
            return api_error("approval_failed", error.message, 400, error.hint)
        payload = {
            "dataset_id": dataset,
            "run": run_report(report),
            "gates": [gate_report(gate) for gate in space.gates(dataset)],
        }
        api_finish_request(request_path, payload)
        return JSONResponse(payload)

    @api.post("/api/datasets/{dataset}/rounds/{run_id}/approve")
    async def api_approve_round(request: Request, dataset: str, run_id: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset) or not api_id_is_safe(run_id):
            return api_invalid_id(run_id if not api_id_is_safe(run_id) else dataset)
        try:
            round_payload(space, dataset, run_id)
        except ServiceError as error:
            return api_error("round_not_found", error.message, 404, error.hint)
        body = await api_body(request)
        gate_id = str(body.get("gate_id") or "")
        chosen = body.get("chosen") or body.get("approved") or []
        if not isinstance(chosen, list):
            return api_error("invalid_approval", "Danh sách lựa chọn không hợp lệ.", 400)
        raw_added = body.get("added_rules") or body.get("added") or ""
        if isinstance(raw_added, str):
            extra = added_rules(raw_added)
        elif isinstance(raw_added, list):
            extra = tuple(item for item in raw_added if isinstance(item, dict))
        else:
            return api_error("invalid_approval", "Quy tắc thêm không hợp lệ.", 400)
        raw_key = str(body.get("client_request_id") or body.get("request_id") or "").strip()
        if raw_key and not REQUEST_KEY.fullmatch(raw_key):
            return api_error("invalid_request_id", "Mã request không hợp lệ.", 400)
        request_path, replay, in_progress = api_claim_request(
            f"approve_round_{dataset}_{run_id}", raw_key
        )
        if replay is not None:
            return JSONResponse(replay)
        if in_progress:
            return api_error("request_in_progress", "Yêu cầu này đang được xử lý.", 409)
        try:
            space.approve(run_id, gate_id, tuple(str(item) for item in chosen), added=extra)
            space.resume(run_id)
        except ServiceError as error:
            api_release_request(request_path)
            return api_error("approval_failed", error.message, 400, error.hint)
        payload = round_payload(space, dataset, run_id)
        api_finish_request(request_path, payload)
        return JSONResponse(payload)

    @api.post("/api/datasets/{dataset}/ask")
    async def api_ask(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        body = await api_body(request)
        raw_key = str(body.get("client_request_id") or body.get("request_id") or "").strip()
        if raw_key and not REQUEST_KEY.fullmatch(raw_key):
            return api_error("invalid_request_id", "Mã request không hợp lệ.", 400)
        request_path, replay, in_progress = api_claim_request(f"ask_{dataset}", raw_key)
        if replay is not None:
            return JSONResponse(replay, status_code=202)
        if in_progress:
            return api_error("request_in_progress", "Yêu cầu này đang được xử lý.", 409)
        question = str(body.get("question") or "").strip()
        parent = str(body.get("from") or "").strip()
        claim = str(body.get("claim") or "").strip()
        if not question:
            api_release_request(request_path)
            return api_error("empty_question", "Hãy nhập một câu hỏi.", 400)
        asked = _with_context(question, claim)
        try:
            report = space.ask(dataset, asked)
            if parent:
                write_lineage(
                    Path(space.settings.layers.runs) / report.round_id,
                    parent=parent,
                    claim=claim,
                )
        except ServiceError as error:
            api_release_request(request_path)
            return api_error("ask_failed", error.message, 400, error.hint)
        payload = {
            "dataset_id": dataset,
            "round_id": report.round_id,
            "question": report.question,
            "state": round_state(space, report.round_id),
            "running": space.running(report.round_id),
        }
        api_finish_request(request_path, payload)
        return JSONResponse(payload, status_code=202)

    @api.get("/api/datasets/{dataset}/rounds/{run_id}")
    def api_round(request: Request, dataset: str, run_id: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset) or not api_id_is_safe(run_id):
            return api_invalid_id(run_id if not api_id_is_safe(run_id) else dataset)
        try:
            return JSONResponse(round_payload(space, dataset, run_id))
        except ServiceError as error:
            return api_error("round_not_found", error.message, 404, error.hint)

    @api.get("/api/datasets/{dataset}/rounds/{run_id}/status")
    def api_round_status(request: Request, dataset: str, run_id: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset) or not api_id_is_safe(run_id):
            return api_invalid_id(run_id if not api_id_is_safe(run_id) else dataset)
        try:
            return JSONResponse(round_status_payload(space, dataset, run_id))
        except ServiceError as error:
            return api_error("round_not_found", error.message, 404, error.hint)

    @api.get("/api/datasets/{dataset}/clean.csv")
    def api_download_clean(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        try:
            table = space.clean_table(dataset)
        except (OSError, ServiceError):
            table = None
        if table is None:
            return api_error("clean_not_found", "Chưa có bảng sạch để tải.", 404)
        frame = space.table(table.uri)
        return Response(
            frame.to_csv(index=False).encode("utf-8-sig"),
            media_type="text/csv",
            headers={"content-disposition": f'attachment; filename="{dataset}_sach.csv"'},
        )

    @api.get("/api/datasets/{dataset}/rounds/{run_id}/export/{kind}")
    def api_export_answer(request: Request, dataset: str, run_id: str, kind: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset) or not api_id_is_safe(run_id):
            return api_invalid_id(run_id if not api_id_is_safe(run_id) else dataset)
        chosen = FORMATS.get(kind)
        round_ids = {item.run_id for item in payload_round_runs(space, dataset)}
        if chosen is None or run_id not in round_ids:
            return api_error("export_not_found", "Không có định dạng hoặc phân tích này.", 404)
        found = space.answer(run_id)
        if found is None:
            return api_error("answer_not_found", "Phân tích chưa có câu trả lời.", 404)
        suffix, media = chosen
        labels, names, aliases = display_words(space, dataset)
        found = with_group_means(found, space.measured(run_id), labels, names)
        body = to_excel(found, aliases) if kind == "excel" else to_word(found, aliases)
        return Response(
            body,
            media_type=media,
            headers={"content-disposition": f'attachment; filename="{run_id}.{suffix}"'},
        )

    @api.get("/api/charts/{name:path}")
    def api_chart(request: Request, name: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        wanted = Path(space.settings.layers.artifacts) / Path(name).name
        if wanted.suffix != ".png" or not wanted.is_file():
            return api_error("chart_not_found", "Không có biểu đồ này.", 404)
        return Response(wanted.read_bytes(), media_type="image/png")

    @api.post("/api/datasets/{dataset}/rounds/delete")
    async def api_forget_rounds(request: Request, dataset: str) -> Response:
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        body = await api_body(request)
        selected = body.get("round_ids") or body.get("rounds") or []
        if not isinstance(selected, list):
            return api_error("invalid_rounds", "Danh sách phân tích không hợp lệ.", 400)
        chosen = [str(item) for item in selected if str(item).strip()]
        busy = [item for item in chosen if space.running(item)]
        if busy:
            return api_error(
                "round_running",
                "Có phân tích đang chạy trong số bạn chọn.",
                409,
                ", ".join(busy),
            )
        try:
            deleted = space.forget_rounds(dataset, chosen)
        except ServiceError as error:
            return api_error("delete_failed", error.message, 400, error.hint)
        return JSONResponse({"dataset_id": dataset, "deleted": deleted})

    def api_still_starting(dataset: str) -> bool:
        """Vừa tải lên, việc làm sạch chạy nền chưa kịp tạo thư mục chạy.

        Có hạn: việc nền chết giữa chừng (máy chủ khởi động lại) thì tệp gốc nằm
        đó mãi, và chính tệp hỏng đó là thứ người dùng cần xoá được.
        """
        run_dir = Path(space.settings.layers.runs) / dataset
        if run_dir.is_dir() or read_error(run_dir):
            return False
        limit = space.STALE_AFTER_MINUTES * 60
        raw_root = Path(space.settings.layers.raw)
        return any(
            time.time() - path.stat().st_mtime < limit
            for path in raw_root.glob(f"{dataset}.*")
            if path.is_file()
        )

    @api.delete("/api/datasets/{dataset}")
    def api_forget_dataset(request: Request, dataset: str) -> Response:
        """Xoá hẳn một bộ dữ liệu, để người dùng tự bỏ được tệp hỏng."""
        denied = api_requires_sign_in(request)
        if denied is not None:
            return denied
        if not api_id_is_safe(dataset):
            return api_invalid_id(dataset)
        missing = api_require_dataset(dataset)
        if missing is not None:
            return missing
        busy = space.dataset_busy(dataset)
        if busy or api_still_starting(dataset):
            return api_error(
                "dataset_running",
                "Bộ dữ liệu này đang được xử lý. Đợi xong rồi xoá.",
                409,
                ", ".join(busy),
            )
        try:
            removed = space.forget_dataset(dataset)
        except ServiceError as error:
            return api_error("delete_failed", error.message, 400, error.hint)
        return JSONResponse({"dataset_id": dataset, "removed": removed})

    return api


def _too_large(tep: UploadFile) -> str:
    """Câu báo nếu tệp vượt giới hạn, hoặc rỗng.

    Kiểm TRƯỚC khi đọc tệp vào bộ nhớ. Kích thước lấy từ chính phần multipart
    máy chủ đã nhận, không tin một con số trình duyệt tự khai.
    """
    size = tep.size or 0
    if size <= MAX_UPLOAD_BYTES:
        return ""
    return (
        f"Tệp nặng {size / 1048576:.1f} MB, vượt giới hạn "
        f"{MAX_UPLOAD_BYTES // 1048576} MB. Hãy chia nhỏ tệp hoặc bỏ bớt cột "
        "không cần rồi tải lại."
    )


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


def _with_context(question: str, claim: str) -> str:
    """Câu hỏi tiếp, mang theo kết luận nó đào sâu."""
    if not claim:
        return question
    return f"Về kết luận «{claim}»: {question}"


def serve(host: str = "127.0.0.1", port: int = 8020) -> None:
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


def _glossary_payload(dataset: str, rows: list[dict[str, object]]) -> dict[str, object]:
    """Mỗi cột một dòng, theo thứ tự của bảng; `saved` là đã có ít nhất một nghĩa."""
    return {
        "dataset_id": dataset,
        "rows": rows,
        "saved": any(str(row.get("meaning") or "").strip() for row in rows),
    }
