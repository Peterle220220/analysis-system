"""Tầng API: nơi giao diện gọi vào.

Mọi route gọi `Workspace` rồi trình bày cái trả về. Không route nào quyết định gì cả:
luật về cái gì được chạy, cái gì phải duyệt, cái gì được tuyên bố đều nằm tầng dưới, nơi
chúng đã có test, và một bản sao của bất kỳ luật nào trong số đó là một câu trả lời thứ
hai đang chờ để mâu thuẫn với câu thứ nhất.

File này chỉ ghép các nhóm route lại. Mỗi nhóm nằm trong `routers/`, và những gì nhiều
nhóm cùng cần thì ở `session.py` (ai được phép), `replies.py` (hình dạng câu trả lời),
`once.py` (một thao tác gửi hai lần vẫn chạy một lần) và `inputs.py` (nắn đầu vào).
Trước tái cấu trúc DDD, tất cả nằm trong một hàm `build()` dài hơn 900 dòng.
"""

from __future__ import annotations

from fastapi import FastAPI

from analysis_system.api.auth import AuthError, session_secret, stored_credential
from analysis_system.api.routers import bi, dashboards, datasets, runs
from analysis_system.api.routers import session as session_routes
from analysis_system.api.routers import system as system_routes
from analysis_system.api.session import SESSION_COOKIE, Guard
from analysis_system.application.workspace import Workspace


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
    api.include_router(session_routes.router(keeper))
    api.include_router(system_routes.router(space, keeper))
    api.include_router(datasets.router(space, keeper))
    api.include_router(runs.router(space, keeper))
    api.include_router(bi.router(space, keeper))
    api.include_router(dashboards.router(space, keeper))
    return api


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


__all__ = ["SESSION_COOKIE", "AuthError", "Guard", "build", "serve"]
