"""Offline ask-to-answer contract using the same Workspace as production.

The browser smoke uses the artefacts this flow writes. A small cassette keeps
the test deterministic and avoids sending fixture data to a live model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.api import Workspace
from analysis_system.services import storage
from analysis_system.settings import LAYER_NAMES, LayerPaths, load_settings, resolve

HAS_RELEVANCE_MODEL = (Path.home() / ".cache" / "huggingface").is_dir()
NEEDS_RELEVANCE_MODEL = pytest.mark.skipif(
    not HAS_RELEVANCE_MODEL, reason="chua tai model do do lien quan"
)


@NEEDS_RELEVANCE_MODEL
def test_cassette_ask_reaches_answer_artifact(tmp_path: Path) -> None:
    """A real Workspace ask completes without a network model call."""
    roots = {name: tmp_path / name for name in LAYER_NAMES}
    for root in roots.values():
        root.mkdir(parents=True, exist_ok=True)
    base = load_settings()
    settings = base.model_copy(
        update={
            "layers": LayerPaths(**roots),
            "llm": base.llm.model_copy(
                update={"provider": "cassette", "cassette_dir": "tests/cassettes/web_flow"}
            ),
        }
    )

    run_dir = Path(settings.layers.runs) / "r_web"
    run_dir.mkdir(parents=True)
    moment = "2026-09-09T00:00:00+00:00"
    (run_dir / "state.json").write_text(
        json.dumps(
            {
                "run_id": "r_web",
                "phase": "COMPLETED",
                "tasks": {
                    "t3_clean": {
                        "task_id": "t3_clean",
                        "agent_id": "a3_cleaner",
                        "phase": "OK",
                        "attempts": 1,
                        "input_hashes": [],
                        "params_hash": "0" * 64,
                        "output_refs": [
                            {
                                "path": "clean://r_web.parquet",
                                "format": "parquet",
                                "content_hash": "c" * 64,
                                "schema_version": "1",
                            }
                        ],
                        "metrics": {},
                        "error": None,
                        "updated_at": moment,
                    }
                },
                "created_at": moment,
                "updated_at": moment,
            }
        ),
        encoding="utf-8",
    )
    storage.write_parquet(
        pd.DataFrame({"city": ["Seattle", "Boston", "Seattle"], "price": ["10", "20", "30"]}),
        resolve("clean://r_web.parquet", settings),
    )

    report = Workspace(settings=settings).ask("r_web", "gia theo thanh pho")

    assert report.run.status == "completed", report.run.escalation
    assert report.answer is not None
    assert report.answer.claims
    assert (Path(settings.layers.artifacts) / f"{report.round_id}_answer.json").is_file()
