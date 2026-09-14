"""A0: nhin mot dong file va noi cai nao di toi agent nao.

Until now somebody had to know. `asys clean --input phieu.csv` works because a
person looked at the file and picked the command; hand the same person a folder
of forty files and the knowing has to happen forty times.

This is that knowing, written down. It reads the first bytes of each file, says
what the file actually is, and names the agent that can read it - and it does
none of the reading itself, so a folder can be surveyed for the price of a few
bytes per file rather than the price of extracting all of them.

**No model.** Which reader opens a PDF is not a judgement, it is a lookup, and a
model asked would answer confidently and occasionally differently.

Two refusals matter more than the routing:

* A file nothing can read is said so, by name, rather than dropped from the
  list. A folder that quietly surveys thirty-eight of forty files is worse than
  one that refuses, because the two missing ones are never noticed.
* A PDF with no text layer is routed to the image reader, not the PDF reader,
  and the plan says why. Sending it to E1 produces an empty extraction and a
  confusing refusal much later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

from analysis_system.services.extraction import ExtractionError, detect

# Which agent reads what. A lookup, kept in one place so adding a reader means
# adding a line here and nothing else.
BY_KIND: Final[dict[str, str]] = {
    "pdf": "e1_pdf",
    "image": "e2_image",
    "audio": "e3_audio",
    "zip": "e4_document",
    "table": "a1_ingest",
    "text": "a1_ingest",
}

# Extensions that a table reader handles even though the bytes are plain text.
# The bytes cannot tell a CSV from a letter, and this is the one place a name is
# allowed to matter - after the format has already been decided from content.
TABLE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".csv", ".tsv", ".jsonl", ".ndjson", ".json", ".xlsx", ".xls", ".parquet"}
)

# The document reader also handles anything that decodes as markup or mail.
DOCUMENT_SUFFIXES: Final[frozenset[str]] = frozenset({".html", ".htm", ".eml", ".msg"})

MAX_FILES: Final[int] = 500
# Past this a file is worth mentioning before somebody sets a reader on it. The
# event log in this project's own raw layer is 711 MB, and routing that to a
# text reader without a word would be a long silence.
LARGE_FILE_MB: Final[int] = 100


@dataclass(frozen=True)
class Route:
    """One file, what it turned out to be, and who can read it."""

    path: str
    detected: str
    label: str
    agent: str
    size_bytes: int
    warnings: tuple[str, ...] = ()

    @property
    def routable(self) -> bool:
        """True when some agent can read this."""
        return bool(self.agent)


@dataclass(frozen=True)
class RoutingPlan:
    """What a folder of files turned out to hold."""

    routes: tuple[Route, ...] = ()
    declined: tuple[str, ...] = ()

    @property
    def unroutable(self) -> tuple[Route, ...]:
        """The files nothing here can read, kept rather than dropped."""
        return tuple(route for route in self.routes if not route.routable)

    def by_agent(self) -> dict[str, list[str]]:
        """Which files each agent would be given."""
        grouped: dict[str, list[str]] = {}
        for route in self.routes:
            if route.routable:
                grouped.setdefault(route.agent, []).append(route.path)
        return grouped


def route_one(path: Path) -> Route:
    """Work out what one file is and who reads it.

    The bytes decide the format; the name is consulted only afterwards, and only
    to separate two things the bytes genuinely cannot tell apart - a CSV and a
    letter are both text, and a Word file and a spreadsheet are both zips.
    """
    size = path.stat().st_size if path.is_file() else 0
    try:
        kind = detect(path)
    except ExtractionError as error:
        return Route(str(path), "unknown", "khong mo duoc", "", size, (str(error),))

    warnings: list[str] = []
    agent = BY_KIND.get(kind.kind, "")
    suffix = path.suffix.lower()

    if kind.kind == "text":
        if suffix in TABLE_SUFFIXES:
            agent = "a1_ingest"
        elif suffix in DOCUMENT_SUFFIXES:
            agent = "e4_document"
        else:
            agent = "e4_document"
            warnings.append(
                "text khong ro la bang hay van xuoi - dua cho e4_document doc nhu van ban. "
                "Neu day la bang thi doi duoi thanh .csv."
            )
    elif kind.kind == "zip":
        # A .docx and an .xlsx are both zips. Which one is settled by looking
        # inside, and the readers already do that - so the name decides here,
        # after the format has not.
        agent = "a1_ingest" if suffix in {".xlsx", ".xls"} else "e4_document"
    elif kind.kind == "ole" and suffix == ".xls":
        # Excel 97-2003 that: bo doc bang nhan, va noi ro can gi de doc no.
        agent = "a1_ingest"

    if not agent:
        warnings.append(f"khong agent nao doc duoc loai {kind.label!r}.")
    if size == 0:
        warnings.append("file rong.")
    elif size > LARGE_FILE_MB * 1024 * 1024:
        megabytes = size / 1024 / 1024
        warnings.append(f"file lon ({megabytes:,.0f} MB) - doc het se lau va ton bo nho.")

    return Route(
        path=str(path),
        detected=kind.kind,
        label=kind.label,
        agent=agent,
        size_bytes=size,
        warnings=tuple(warnings),
    )


def route(paths: list[Path], max_files: int = MAX_FILES) -> RoutingPlan:
    """Survey these files and say who reads each one.

    Reads a few bytes of each, never the whole file: a folder is surveyed for
    almost nothing, and the extraction happens later and only for what is
    wanted.
    """
    files = sorted(path for path in paths if path.is_file())
    declined: list[str] = []
    if len(files) > max_files:
        declined.append(
            f"co {len(files)} file, chi xet {max_files} dau tien. "
            "Chia nho thu muc ra hoac tang max_files."
        )
        files = files[:max_files]

    routes = tuple(route_one(path) for path in files)
    unreadable = [item for item in routes if not item.routable]
    if unreadable:
        # Named, one by one. A survey that quietly covers thirty-eight of forty
        # files is worse than one that refuses: nobody notices the two.
        declined.append(
            f"{len(unreadable)} file khong doc duoc: "
            + ", ".join(Path(item.path).name for item in unreadable[:10])
        )
    return RoutingPlan(routes=routes, declined=tuple(declined))
