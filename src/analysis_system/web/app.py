"""Tang 1: dashboard cho nguoi dieu hanh.

Every route here calls `Workspace` and renders what comes back. Nothing decides
anything: the rules about what may run, what must be approved and what may be
claimed live one layer down, where they are already tested, and a second copy
of any of them would be a second answer waiting to disagree with the first.

That was the point of `api.py` returning values and printing nothing. The
command line was the first presenter of it; this is the second.

`asys serve` starts it. It refuses to start without a password.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.status import HTTP_303_SEE_OTHER

from analysis_system.api import ServiceError, Workspace
from analysis_system.services import retention
from analysis_system.web.auth import AuthError, Credential, session_secret, stored_credential
from analysis_system.web.render import page, run_detail, runs_table, sign_in

SESSION_COOKIE: Final[str] = "asys_session"
# Sessions live in memory, so restarting the server ends them. For one operator
# on one machine that is the whole requirement, and it avoids a session store
# that would have to be secured and cleaned up in its own right.
_SESSIONS: dict[str, str] = {}


@dataclass(frozen=True)
class Guard:
    """Who may look at this dashboard."""

    credential: Credential
    secret: str

    def issue(self) -> str:
        """A new session token for somebody who just proved who they are."""
        token = secrets.token_urlsafe(32)
        _SESSIONS[token] = self.secret
        return token

    def admits(self, token: str | None) -> bool:
        """True when this token belongs to a session this server issued."""
        return bool(token) and _SESSIONS.get(token or "") == self.secret


def build(workspace: Workspace | None = None, guard: Guard | None = None) -> FastAPI:
    """The dashboard, bound to one workspace.

    Raises:
        AuthError: no password is configured. Refusing to start is the point:
            a dashboard that comes up without one exposes every run to whoever
            finds the port.
    """
    space = workspace or Workspace()
    keeper = guard or Guard(credential=stored_credential(), secret=session_secret())
    api = FastAPI(title="Analysis System", docs_url=None, redoc_url=None)

    def signed_in(request: Request) -> bool:
        return keeper.admits(request.cookies.get(SESSION_COOKIE))

    def to_sign_in() -> RedirectResponse:
        return RedirectResponse("/dang-nhap", status_code=HTTP_303_SEE_OTHER)

    @api.get("/dang-nhap", response_class=HTMLResponse)
    def sign_in_form(request: Request) -> Response:
        if signed_in(request):
            return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)
        return HTMLResponse(sign_in())

    @api.post("/dang-nhap", response_class=HTMLResponse)
    def sign_in_submit(password: str = Form(default="")) -> Response:
        if not keeper.credential.matches(password):
            # One message for a wrong password, and nothing about which part
            # was wrong. There is only one account, so "sai mat khau" is all
            # there is to say.
            return HTMLResponse(sign_in(error="Sai mat khau."), status_code=401)
        answer = RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)
        answer.set_cookie(
            SESSION_COOKIE,
            keeper.issue(),
            httponly=True,
            samesite="strict",
            # Not `secure=True`: this is served over plain HTTP on a machine the
            # operator owns. Put it behind TLS before it leaves that machine.
        )
        return answer

    @api.post("/dang-xuat")
    def sign_out(request: Request) -> Response:
        _SESSIONS.pop(request.cookies.get(SESSION_COOKIE) or "", None)
        answer = to_sign_in()
        answer.delete_cookie(SESSION_COOKIE)
        return answer

    @api.get("/", response_class=HTMLResponse)
    def home(request: Request) -> Response:
        if not signed_in(request):
            return to_sign_in()
        return HTMLResponse(page("Cac lan chay", runs_table(retention.runs(space.settings), space)))

    @api.get("/lan-chay/{run_id}", response_class=HTMLResponse)
    def one_run(request: Request, run_id: str) -> Response:
        if not signed_in(request):
            return to_sign_in()
        try:
            detail = run_detail(space, run_id)
        except ServiceError as error:
            return HTMLResponse(page("Khong xem duoc", f"<p class=err>{error.message}</p>"), 404)
        return HTMLResponse(page(run_id, detail))

    @api.post("/lan-chay/{run_id}/duyet")
    def approve(
        request: Request,
        run_id: str,
        gate_id: str = Form(default=""),
        chon: str = Form(default=""),
        tu_choi: str = Form(default=""),
    ) -> Response:
        if not signed_in(request):
            return to_sign_in()
        picked = [item for item in chon.split(",") if item.strip()]
        refused = [item for item in tu_choi.split(",") if item.strip()]
        try:
            space.approve(run_id, gate_id, tuple(picked), tuple(refused))
        except ServiceError as error:
            return HTMLResponse(page("Khong duyet duoc", f"<p class=err>{error.message}</p>"), 400)
        return RedirectResponse(f"/lan-chay/{run_id}", status_code=HTTP_303_SEE_OTHER)

    @api.get("/anh/{name}")
    def chart(request: Request, name: str) -> Response:
        """Serve one chart a run produced.

        The name is checked against what the artifacts layer actually holds
        rather than joined onto a path: a name arriving from a URL must never
        be able to walk out of the directory it is supposed to address.
        """
        if not signed_in(request):
            return to_sign_in()
        root = Path(space.settings.layers.artifacts)
        wanted = root / Path(name).name
        if wanted.suffix != ".png" or not wanted.is_file():
            return Response(status_code=404)
        return Response(wanted.read_bytes(), media_type="image/png")

    return api


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the dashboard.

    Binds to localhost by default. Anything wider needs a deliberate choice and
    a look at what is in front of it, because there is one password here and no
    rate limiting behind it.

    Raises:
        AuthError: no password configured.
    """
    import uvicorn

    uvicorn.run(build(), host=host, port=port, log_level="warning")


__all__ = ["AuthError", "Guard", "build", "serve"]
