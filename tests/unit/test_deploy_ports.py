"""Chỉ Next.js mở ra mạng; backend Python chỉ nghe nội bộ.

Quyết định 3 của plans/refactor-ddd.md: giao diện HTML cũ của Python đã bỏ, nên cổng của
nó không còn gì để phục vụ người dùng. Để nó mở ra mạng là để lộ backend, không qua cửa
nào cả. Test này giữ cả hai cách chạy (systemd và Docker) cùng một luật.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _lines(name: str) -> list[str]:
    return (ROOT / name).read_text(encoding="utf-8").splitlines()


def test_the_backend_listens_only_on_this_machine() -> None:
    start = next(line for line in _lines("deploy/asys.service") if line.startswith("ExecStart="))
    assert "--host 127.0.0.1" in start
    assert "0.0.0.0" not in start


def test_next_is_the_door_from_the_network_and_calls_the_backend_locally() -> None:
    lines = _lines("deploy/asys-web.service")
    assert "Environment=HOSTNAME=0.0.0.0" in lines
    assert "Environment=ASYS_BACKEND_URL=http://127.0.0.1:8020" in lines


def test_docker_publishes_only_the_frontend() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert compose.count("ports:") == 1
    assert '"8020:3000"' in compose
