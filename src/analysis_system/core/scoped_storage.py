"""Scope-checked I/O: the only filesystem access an agent is given.

This is the wrapper Phase 1 adds around the Phase 0 storage module. The Phase 0
functions are untouched and still take a plain path; everything here takes a
layer URI, authorises it against the ScopeToken, and only then delegates.

Agents never receive a path and never import storage directly - an AST test
enforces that. They receive an instance of this class instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pandas as pd

from analysis_system.contracts.base import DataRef, ScopeToken
from analysis_system.core import storage
from analysis_system.core.boundary import (
    BoundaryViolation,
    authorise_read,
    authorise_tool,
    authorise_write,
)
from analysis_system.core.hashing import canonical_hash
from analysis_system.core.settings import ConfigError, Settings, resolve

# Khoa trong frame.attrs noi luc doc tep da quyet dinh gi (gop bang, bo bang).
# Dat lai o day vi agent khong duoc import storage.
READ_NOTES: Final[str] = storage.READ_NOTES


class ScopedStorage:
    """Filesystem access bounded by one ScopeToken."""

    def __init__(self, scope: ScopeToken, settings: Settings) -> None:
        """Bind the accessor to a single token and configuration."""
        self._scope = scope
        self._settings = settings

    @property
    def scope(self) -> ScopeToken:
        """The token this accessor enforces."""
        return self._scope

    def _read_path(self, uri: str) -> Path:
        """Authorise a read and resolve the URI to a real path."""
        authorise_read(self._scope, uri)
        return resolve(uri, self._settings)

    def _write_path(self, uri: str) -> Path:
        """Authorise a write, resolve it, and make sure its directory exists.

        The directory is created only after the scope check has passed, and only
        inside a layer the token already grants, so this widens nothing.
        """
        authorise_write(self._scope, uri)
        path = resolve(uri, self._settings)
        storage.ensure_directory(path.parent)
        return path

    def use_tool(self, tool: str) -> None:
        """Declare use of a tool, so an unlisted one is refused."""
        authorise_tool(self._scope, tool)

    def citation_exists(self, uri: str) -> bool:
        """Whether a cited path is real and readable under this token.

        For checking a citation, never for reading one. A citation outside the
        granted scope and a citation pointing at nothing are both invalid *as
        citations*, so they collapse into one answer here rather than being
        told apart - the caller is asking whether a claim can be traced, not
        trying to open a file.
        """
        if not uri or "://" not in uri:
            return False
        try:
            return self._read_path(uri).is_file()
        except (BoundaryViolation, ConfigError):
            return False

    def load_csv(
        self,
        uri: str,
        *,
        encoding: str = "utf-8",
        delimiter: str = ",",
        keep_all_as_text: bool = True,
        has_header: bool = True,
    ) -> pd.DataFrame:
        """Read a CSV from inside the granted read scope.

        Encoding, delimiter and whether there is a header row are passed in
        rather than assumed, because A1 detects all three from the file and has
        to be able to act on what it found. The header was detected and then
        ignored for a long time, which cost the first row of every headerless
        file.
        """
        return storage.read_csv(
            self._read_path(uri),
            encoding=encoding,
            delimiter=delimiter,
            keep_all_as_text=keep_all_as_text,
            has_header=has_header,
        )

    def load_parquet(self, uri: str) -> pd.DataFrame:
        """Read a Parquet file from inside the granted read scope."""
        return storage.read_parquet(self._read_path(uri))

    def load_bytes(self, uri: str, *, limit: int | None = None) -> bytes:
        """Read raw bytes from inside the granted read scope.

        Used to detect encoding and delimiter before anything tries to decode.
        """
        return storage.read_bytes(self._read_path(uri), limit=limit)

    def load_json(self, uri: str, *, encoding: str = "utf-8", lines: bool = False) -> pd.DataFrame:
        """Read a JSON or JSON Lines file from inside the granted read scope."""
        return storage.read_json(self._read_path(uri), encoding=encoding, lines=lines)

    def load_excel(self, uri: str, *, sheet: str | int = 0) -> pd.DataFrame:
        """Read one worksheet from inside the granted read scope."""
        return storage.read_excel(self._read_path(uri), sheet=sheet)

    def excel_sheets(self, uri: str) -> list[str]:
        """List the worksheets of a workbook inside the granted read scope."""
        return storage.excel_sheets(self._read_path(uri))

    def load_text(self, uri: str) -> str:
        """Read a text artefact from inside the granted read scope."""
        return storage.read_text(self._read_path(uri))

    def save_parquet(self, frame: pd.DataFrame, uri: str) -> DataRef:
        """Write a frame inside the granted write scope.

        Returns:
            A reference carrying the canonical content hash, so the Manager can
            reason about the output without ever opening the file.
        """
        storage.write_parquet(frame, self._write_path(uri))
        return DataRef(
            path=uri,
            format="parquet",
            content_hash=canonical_hash(frame),
            row_count=len(frame.index),
        )

    def save_bytes(self, payload: bytes, uri: str) -> DataRef:
        """Write binary content inside the granted write scope."""
        path = self._write_path(uri)
        storage.write_bytes(payload, path)
        return DataRef(path=uri, format="blob", content_hash=storage.sha256_file(path))

    def save_text(self, text: str, uri: str, *, data_format: str = "json") -> DataRef:
        """Write text inside the granted write scope."""
        path = self._write_path(uri)
        storage.write_text(text, path)
        return DataRef(
            path=uri,
            format="json" if data_format == "json" else "blob",
            content_hash=storage.sha256_file(path),
        )
