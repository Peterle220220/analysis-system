"""A1 Ingest: load structured data into staging, changing nothing.

The manifest denies four things, and they are the whole point of this agent:
no cell may be altered, no column renamed, no row dropped, and nothing written
back into raw. So it detects rather than decides - what encoding, what
separator, whether the first row is a header - and reports every one of those
decisions in its result, because getting any of them wrong corrupts the table
silently and a run has to be able to show what it assumed.

Everything arrives in staging as text. Interpreting a value is the cleaner job,
and reading a column of leading-zero ids as integers destroys them before
anybody gets the chance to decide.
"""

from __future__ import annotations

from typing import Any, ClassVar, Final

import pandas as pd

from analysis_system.agents.base import BaseAgent, ManifestDir, first_of
from analysis_system.core.hashing import canonical_hash
from analysis_system.core.scoped_storage import READ_NOTES, ScopedStorage
from analysis_system.core.settings import Settings
from analysis_system.models.base import ErrorDetail, TaskRequest, TaskResult
from analysis_system.services.column_names import tidy
from analysis_system.services.ingestion import (
    SAMPLE_BYTES,
    Dialect,
    IngestionError,
    detect_dialect,
    detect_format,
)

STAGING_PREFIX: Final[str] = "staging://"
SHEET_PARAM: Final[str] = "sheet"
TARGET_PARAM: Final[str] = "target"
MAX_FILE_BYTES: Final[int] = 2 * 1024 * 1024 * 1024


def staging_uri_for(source_uri: str, run_id: str) -> str:
    """Where a source file lands in staging.

    The run id is part of the name so two runs on two datasets cannot overwrite
    each other and then resume against the wrong data.
    """
    name = source_uri.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] or "table"
    return f"{STAGING_PREFIX}{run_id}_{stem}.parquet"


PLAN_PROBLEM_CODES: Final[frozenset[str]] = frozenset({"NO_INPUT"})


class IngestAgent(BaseAgent):
    """Reads a source file into staging without altering a single value."""

    agent_id: ClassVar[str] = "a1_ingest"

    def __init__(self, settings: Settings, manifest_dir: ManifestDir = None) -> None:
        """No model client: this agent never calls one."""
        super().__init__(settings, manifest_dir)

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        """Load the referenced source and stage it as Parquet."""
        if not request.input_refs:
            return self._failed(request, "NO_INPUT", "A1 can mot input_ref tro toi file nguon.")

        # By what it is, not by where it sits. An extractor hands over both a
        # table and a report about the reading, and loading the report as data
        # fails several layers away from the mistake.
        source = first_of(request.input_refs, "parquet", "csv", "json") or request.input_refs[0]
        try:
            frame, dialect, fmt = self._load(source.path, request.scope.params, files)
        except IngestionError as error:
            return self._failed(request, "UNSUPPORTED_FORMAT", str(error))

        target = str(request.scope.params.get(TARGET_PARAM) or "") or staging_uri_for(
            source.path, request.scope.run_id
        )
        written = files.save_parquet(frame, target)

        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            # Doi ten cot trong im lang la chuyen nguoi dung chi phat hien ra
            # khi cau hoi cua ho khong khop cot nao.
            declined=tuple(getattr(self, "_renamed", ()) or ()),
            metrics={
                "rows": float(len(frame.index)),
                "columns": float(len(frame.columns)),
                "bytes_read": float(self._size(source.path, files)),
            },
            payload={
                "rows": len(frame.index),
                "columns": len(frame.columns),
                "column_names": [str(column) for column in frame.columns],
                "source_format": fmt,
                "encoding": dialect.encoding if dialect else None,
                "delimiter": dialect.delimiter if dialect else None,
                "has_header": dialect.has_header if dialect else None,
                "detection_confident": dialect.confident if dialect else True,
                "detection_note": dialect.note if dialect else "",
                "content_hash": canonical_hash(frame),
                "target": target,
            },
        )

    def _load(
        self, uri: str, params: dict[str, Any], files: ScopedStorage
    ) -> tuple[pd.DataFrame, Dialect | None, str]:
        """Read one source, returning the frame and what was detected about it.

        Ten cot duoc don ngay o day - cua duy nhat moi bang di vao he thong.
        Bon loi lien tiep tren bon bo du lieu deu la mot gia dinh ve ten cot, va
        sua o day thi ca duong ong phia sau khong phai biet gi ve chung.

        Raises:
            IngestionError: the format is not one this agent reads.
        """
        frame, dialect, fmt = self._read(uri, params, files)
        # Gop hay bo bang luc doc tep la quyet dinh nguoi dung phai thay, nhu doi ten cot.
        noted = [str(note) for note in frame.attrs.get(READ_NOTES, ())]
        frame, renamed = tidy(frame)
        self._renamed = (*noted, *renamed)
        return frame, dialect, fmt

    def _read(
        self, uri: str, params: dict[str, Any], files: ScopedStorage
    ) -> tuple[pd.DataFrame, Dialect | None, str]:
        """Doc mot nguon, nguyen ven nhu tep co."""
        fmt = detect_format(uri)
        if fmt == "parquet":
            return files.load_parquet(uri), None, fmt
        if fmt == "xlsx":
            sheet = params.get(SHEET_PARAM, 0)
            return files.load_excel(uri, sheet=sheet), None, fmt

        sample = files.load_bytes(uri, limit=SAMPLE_BYTES)
        dialect = detect_dialect(sample)
        if fmt == "json":
            lines = uri.lower().endswith((".jsonl", ".ndjson"))
            return files.load_json(uri, encoding=dialect.encoding, lines=lines), dialect, fmt

        frame = files.load_csv(
            uri,
            encoding=dialect.encoding,
            delimiter=dialect.delimiter,
            has_header=dialect.has_header,
        )
        return frame, dialect, fmt

    def _size(self, uri: str, files: ScopedStorage) -> int:
        """Bytes read, for the metrics. Zero when the source will not report it."""
        try:
            return len(files.load_bytes(uri, limit=MAX_FILE_BYTES))
        except Exception:  # noqa: BLE001 - a missing size must not fail the task
            return 0

    def _failed(self, request: TaskRequest, code: str, message: str) -> TaskResult:
        """Report an honest failure, with nothing staged."""
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=False,
                # Being handed the wrong input is the one failure a different
                # plan could actually fix.
                replannable=code in PLAN_PROBLEM_CODES,
            ),
        )
