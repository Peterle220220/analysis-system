"""Checking a citation, which is not the same as reading one.

A7 once cited mart://frame.parquet and mart://cumulative_net_worth_eur.parquet.
Every number in those findings was real - the placeholder machinery guarantees
that - but both paths were invented. Criterion S4 asks for a conclusion that can
be traced back, and a path pointing at nothing traces nowhere.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from analysis_system.contracts.base import EvidenceRef, ScopeToken, TaskResult
from analysis_system.services.boundary import load_manifest, postcheck
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import LAYER_NAMES, LayerPaths, Settings, load_settings, resolve

NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
MANIFEST_DIR = Path(__file__).resolve().parents[2] / "config" / "manifests"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    return load_settings().model_copy(update={"layers": LayerPaths(**roots)})


def token() -> ScopeToken:
    """A token that may read the mart, and nothing else."""
    return ScopeToken(
        run_id="r_cite",
        task_id="t_cite",
        agent_id="a7_analyst",
        allow_read=("mart://**",),
        allow_write=("artifacts://**",),
        allow_tools=("pandas",),
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=10),
    )


def write(settings: Settings, uri: str) -> None:
    path = resolve(uri, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"noi dung gia")


# --- storage answers whether a citation points at anything ---------------------


def test_a_citation_to_a_real_readable_file_holds(settings: Settings) -> None:
    write(settings, "mart://co_that.parquet")
    assert ScopedStorage(token(), settings).citation_exists("mart://co_that.parquet")


def test_a_citation_to_a_file_nothing_ever_wrote_fails(settings: Settings) -> None:
    # The actual bug, in one line.
    assert not ScopedStorage(token(), settings).citation_exists("mart://frame.parquet")


def test_a_citation_outside_the_granted_scope_fails(settings: Settings) -> None:
    # It exists, but this token was never allowed to look there - so as a
    # citation it is worth exactly as much as one pointing at nothing.
    write(settings, "raw://bi_mat.csv")
    assert not ScopedStorage(token(), settings).citation_exists("raw://bi_mat.csv")


@pytest.mark.parametrize("cited", ["price.mean", "", "khong-co-lop", "mart://"])
def test_something_that_is_not_a_path_fails(settings: Settings, cited: str) -> None:
    # Gemini once cited "price.mean" - the name of a metric, not a source.
    assert not ScopedStorage(token(), settings).citation_exists(cited)


def test_checking_a_citation_never_raises(settings: Settings) -> None:
    # It is asked once per finding while deciding what to keep. Throwing would
    # turn one bad citation into a failed task.
    storage = ScopedStorage(token(), settings)
    for cited in ("clean://x.parquet", "khong_hop_le", "mart://../../etc/passwd"):
        assert storage.citation_exists(cited) is False


# --- post-check refuses a citation the token never covered ---------------------


def result_citing(source: str) -> TaskResult:
    return TaskResult(
        task_id="t_cite",
        agent_id="a7_analyst",
        status="OK",
        payload={"source": "mart://x.parquet", "question": "?", "findings": []},
        evidence=(EvidenceRef(source=source, locator="price.mean", value="mot ket luan"),),
    )


def test_a_citation_within_scope_passes_post_check() -> None:
    manifest = load_manifest("a7_analyst", MANIFEST_DIR)
    assert postcheck(result_citing("mart://houses.parquet"), manifest, token()) == []


def test_a_citation_outside_scope_is_a_boundary_problem() -> None:
    # A second, independent check: this one is pure contract and touches no
    # disk, so neither check covers for the other going wrong.
    manifest = load_manifest("a7_analyst", MANIFEST_DIR)
    problems = postcheck(result_citing("raw://bi_mat.csv"), manifest, token())
    assert any("ngoai pham vi duoc doc" in problem for problem in problems)


def test_a_citation_that_is_not_a_uri_never_gets_that_far() -> None:
    # EvidenceRef refuses it at construction, so post-check never sees one.
    # Worth pinning down: it means the scope check above only ever has to judge
    # real URIs, and a change to that rule would break this test first.
    with pytest.raises(ValidationError, match="Phai la URI"):
        result_citing("price.mean")
