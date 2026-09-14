"""Working out what a file actually is, before anything tries to read it.

A1 is forbidden from changing a single cell, so everything here is detection
only: what encoding the bytes are in, what separates the fields, whether the
first row is a header. Getting any of these wrong silently corrupts the whole
table, which is why each one reports what it decided and why, rather than just
returning a frame.

Nothing here guesses in silence. When the evidence is weak the caller is told,
so the decision can be recorded and argued with later.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Final

# Tried in order. utf-8-sig first so a byte order mark is consumed rather than
# turning into a stray character at the start of the first column name.
ENCODING_CANDIDATES: Final[tuple[str, ...]] = ("utf-8-sig", "utf-8", "cp1258", "cp1252", "latin-1")

DELIMITER_CANDIDATES: Final[tuple[str, ...]] = (",", ";", "\t", "|")

SAMPLE_BYTES: Final[int] = 64 * 1024

FORMAT_BY_SUFFIX: Final[dict[str, str]] = {
    ".csv": "csv",
    ".tsv": "csv",
    ".txt": "csv",
    ".parquet": "parquet",
    ".json": "json",
    ".jsonl": "json",
    ".ndjson": "json",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    # Duoi .xls khong noi len noi dung that: Excel 97-2003 nhi phan, mot .xlsx
    # doi ten, hay (rat hay gap o bao cao tai chinh tai tu web) mot trang HTML
    # hoac SpreadsheetML 2003. storage.read_excel nhin byte de chon cach doc.
    ".xls": "xlsx",
}


class IngestionError(RuntimeError):
    """The file cannot be read as any format this agent understands."""


@dataclass(frozen=True)
class Dialect:
    """What was detected about a delimited text file, and how sure it is."""

    encoding: str
    delimiter: str
    has_header: bool
    confident: bool
    note: str = ""


def detect_format(name: str) -> str:
    """Decide the format from the file name.

    Raises:
        IngestionError: the suffix is not one this agent can read.
    """
    lowered = name.lower()
    for suffix, fmt in FORMAT_BY_SUFFIX.items():
        if lowered.endswith(suffix):
            return fmt
    known = ", ".join(sorted(FORMAT_BY_SUFFIX))
    raise IngestionError(f"Khong doc duoc dinh dang cua {name!r}. Chi ho tro: {known}")


def detect_encoding(sample: bytes) -> str:
    """Return the first candidate encoding that decodes the sample cleanly.

    Raises:
        IngestionError: none of the candidates decode the bytes.
    """
    for encoding in ENCODING_CANDIDATES:
        try:
            sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    raise IngestionError(
        "Khong giai ma duoc noi dung file voi bat ky bang ma nao trong: "
        + ", ".join(ENCODING_CANDIDATES)
    )


def _score(text: str, delimiter: str) -> tuple[int, bool]:
    """How many fields a delimiter yields, and whether it yields the same count on every line."""
    lines = [line for line in text.splitlines() if line.strip()][:20]
    if not lines:
        return 0, False
    counts = [len(line.split(delimiter)) for line in lines]
    return counts[0], len(set(counts)) == 1 and counts[0] > 1


def detect_delimiter(text: str) -> tuple[str, bool]:
    """Pick the field separator, and say whether the evidence was strong.

    A separator is convincing when it splits every sampled line into the same
    number of fields, and that number is more than one. Where several qualify,
    the one producing the most columns wins.
    """
    consistent: list[tuple[int, str]] = []
    for delimiter in DELIMITER_CANDIDATES:
        fields, stable = _score(text, delimiter)
        if stable:
            consistent.append((fields, delimiter))
    if consistent:
        consistent.sort(key=lambda item: (-item[0], DELIMITER_CANDIDATES.index(item[1])))
        return consistent[0][1], True

    try:
        sniffed = csv.Sniffer().sniff(text[:4096], delimiters="".join(DELIMITER_CANDIDATES))
    except csv.Error:
        return ",", False
    return str(sniffed.delimiter), False


def detect_header(text: str, delimiter: str) -> bool:
    """True when the first row looks like column names rather than data.

    Two tests, and the second exists because the first one is not enough. A
    header row is text in every field while a data row almost always carries a
    number - which decides most files, and decides wrongly for a file that is
    text all the way down. `emotions.txt` is 16,000 lines of "sentence;label",
    every field text, and this said "header": the first sentence became a
    column name and the row was gone.

    So also: a column name does not appear again further down its own column.
    "sadness" turns up 4,665 times below, and no header does that.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    first = [cell.strip().strip('"') for cell in lines[0].split(delimiter)]
    if not first or any(not cell for cell in first):
        return False
    if len(set(first)) != len(first):
        return False
    if any(_looks_numeric(cell) for cell in first):
        return False
    return not _repeats_below(first, lines[1:], delimiter)


def _repeats_below(first: list[str], rest: list[str], delimiter: str) -> bool:
    """True when a first-row cell turns up again in its own column.

    A value that repeats in the column beneath it is a value, not a name. The
    last line of a sample is usually cut mid-row, so it is dropped rather than
    compared against.
    """
    if len(rest) < 2:
        return False
    below: list[set[str]] = [set() for _ in first]
    for line in rest[:-1]:
        cells = [cell.strip().strip('"') for cell in line.split(delimiter)]
        if len(cells) != len(first):
            continue
        for column, cell in zip(below, cells, strict=True):
            column.add(cell)
    return any(cell in column for cell, column in zip(first, below, strict=True))


def _looks_numeric(value: str) -> bool:
    """True when a field parses as a plain number."""
    try:
        float(value.replace(",", ""))
    except ValueError:
        return False
    return True


def detect_dialect(sample: bytes) -> Dialect:
    """Work out encoding, delimiter and header from the first bytes of a file."""
    encoding = detect_encoding(sample)
    text = sample.decode(encoding, errors="replace")
    delimiter, confident = detect_delimiter(text)
    header = detect_header(text, delimiter)
    note = (
        ""
        if confident
        else "So cot khong dong nhat giua cac dong mau - dau phan cach la phong doan."
    )
    return Dialect(
        encoding=encoding,
        delimiter=delimiter,
        has_header=header,
        confident=confident,
        note=note,
    )
