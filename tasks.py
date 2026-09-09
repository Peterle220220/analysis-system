#!/usr/bin/env python3
"""Task runner: the single source of truth for project commands.

The Makefile is a thin wrapper that delegates every target here, so the two can
never drift apart. This module intentionally has no third-party dependency: it
must run before the virtualenv exists.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_BIN = ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin")
PYTHON = VENV_BIN / ("python.exe" if os.name == "nt" else "python")
RUFF = VENV_BIN / "ruff"
MYPY = VENV_BIN / "mypy"
PYTEST = VENV_BIN / "pytest"
NPM = shutil.which("npm") or "npm"

# Deterministic runs (S1): a randomised hash seed changes set/dict iteration
# order, which can leak into generated output.
FIXED_ENV = {"PYTHONHASHSEED": "0"}

CACHE_DIRS = (".pytest_cache", ".mypy_cache", ".ruff_cache", "htmlcov")


def _require_venv() -> None:
    """Abort with a Vietnamese message if the virtualenv is missing."""
    if not PYTHON.exists():
        sys.exit(
            "Chua co virtualenv tai .venv\n"
            "  Chay:  python3 -m venv .venv && "
            './.venv/bin/pip install -e ".[dev]"'
        )


def run_cmd(argv: Sequence[str | Path]) -> int:
    """Run a command from the project root with the deterministic environment."""
    print("$ " + " ".join(str(a) for a in argv), flush=True)
    env = os.environ.copy()
    env.update(FIXED_ENV)
    return subprocess.call([str(a) for a in argv], cwd=ROOT, env=env)


def run_frontend_cmd(argv: Sequence[str | Path]) -> int:
    """Run a frontend command from the Next.js project directory."""
    print("$ " + " ".join(str(a) for a in argv), flush=True)
    env = os.environ.copy()
    env.update(FIXED_ENV)
    return subprocess.call([str(a) for a in argv], cwd=ROOT / "frontend", env=env)


def task_lint() -> int:
    """Static style checks: ruff lint rules, then formatting."""
    _require_venv()
    rc = run_cmd([RUFF, "check", "."])
    if rc != 0:
        return rc
    # spec_tmp.py is a scratch note kept for local experiments, not a source
    # file that belongs to the production formatting gate.
    return run_cmd([RUFF, "format", "--check", ".", "--exclude", "spec_tmp.py"])


def task_typecheck() -> int:
    """Strict mypy over src, tests, scripts and this file."""
    _require_venv()
    return run_cmd([MYPY])


def task_test() -> int:
    """Run the test suite with coverage over the package."""
    _require_venv()
    return run_cmd([PYTEST, "--cov=analysis_system", "--cov-report=term-missing"])


def task_web_build() -> int:
    """Build the production Next.js artifact used by deployment."""
    frontend = ROOT / "frontend"
    if not (frontend / "package.json").is_file():
        sys.exit("Khong tim thay frontend/package.json")
    if not (frontend / "node_modules").is_dir():
        sys.exit("Chua cai frontend dependencies\n  Chay:  cd frontend && npm ci")
    return run_frontend_cmd([NPM, "run", "build"])


def task_check() -> int:
    """Lint + typecheck + test + frontend build."""
    for task in (task_lint, task_typecheck, task_test, task_web_build):
        rc = task()
        if rc != 0:
            return rc
    print("\nOK - tat ca kiem tra da qua.")
    return 0


def task_setup() -> int:
    """Prepare the data layers and the CLI demo input."""
    _require_venv()
    return run_cmd([PYTHON, "-m", "analysis_system.cli", "setup"])


def task_run(extra: Sequence[str]) -> int:
    """Run the pipeline end to end."""
    _require_venv()
    return run_cmd([PYTHON, "-m", "analysis_system.cli", "run", *extra])


def task_cli(extra: Sequence[str]) -> int:
    """Forward any command to the CLI, using the virtualenv interpreter.

    Saves having to remember either the venv path or the working directory:
    `python3 tasks.py cli gates r1` works from the project root with the system
    Python, because tasks.py knows where the real interpreter lives.
    """
    _require_venv()
    return run_cmd([PYTHON, "-m", "analysis_system.cli", *extra])


def task_clean() -> int:
    """Delete caches only. Never touches anything under the data layers."""
    for name in CACHE_DIRS:
        target = ROOT / name
        if target.exists():
            print(f"xoa {target}")
            shutil.rmtree(target)
    coverage = ROOT / ".coverage"
    if coverage.exists():
        print(f"xoa {coverage}")
        coverage.unlink()
    for pycache in ROOT.rglob("__pycache__"):
        if ".venv" not in pycache.parts:
            shutil.rmtree(pycache)
    print("Da don sach cache.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the target name and dispatch."""
    parser = argparse.ArgumentParser(description="Task runner cua analysis-system")
    parser.add_argument(
        "target",
        choices=[
            "check",
            "lint",
            "typecheck",
            "test",
            "web-build",
            "run",
            "cli",
            "setup",
            "clean",
        ],
    )
    parser.add_argument("extra", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if args.target == "run":
        return task_run(args.extra)
    if args.target == "cli":
        return task_cli(args.extra)
    dispatch = {
        "check": task_check,
        "lint": task_lint,
        "typecheck": task_typecheck,
        "test": task_test,
        "web-build": task_web_build,
        "setup": task_setup,
        "clean": task_clean,
    }
    return dispatch[args.target]()


if __name__ == "__main__":
    raise SystemExit(main())
