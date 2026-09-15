"""The single I/O gateway of the system.

Every read and write in the codebase goes through this module. Phase 1 wraps
these functions with a ScopeToken check; it does not replace them, and no other
module is allowed to touch the filesystem directly.

Writes are atomic: content lands in a temporary file inside the destination
directory and is renamed into place only once it is complete, so a process
killed mid-write never leaves a half-written artefact behind.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Final
from xml.etree import ElementTree

import pandas as pd

_HASH_CHUNK_BYTES: Final[int] = 1 << 20


class StorageError(RuntimeError):
    """A read or write could not be completed."""


def _require_directory(path: Path) -> Path:
    """Return the parent directory of the target, or fail if it does not exist."""
    parent = path.parent
    if not parent.is_dir():
        raise StorageError(
            f"Thu muc dich khong ton tai: {parent}\n"
            "Storage khong tu tao thu muc - hay kiem tra config/settings.yaml."
        )
    return parent


def ensure_writable_directory(path: Path) -> Path:
    """Reject a directory explicitly marked read-only before opening a file.

    Some Windows environments let an administrator write through a directory
    whose POSIX mode bits are ``0555``. The application still needs to honour
    that mode because the same directory is intentionally mounted read-only in
    deployment.
    """
    if not path.is_dir():
        raise StorageError(f"Thu muc dich khong ton tai: {path}")
    try:
        if path.stat().st_mode & 0o222 == 0:
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), str(path))
    except OSError as exc:
        if isinstance(exc, PermissionError):
            raise
        raise StorageError(f"Khong kiem tra duoc quyen ghi {path}: {exc}") from exc
    return path


def _apply_default_permissions(path: Path) -> None:
    """Give a temp file the permissions a normally created file would have.

    tempfile.mkstemp creates its file 0600 for security, and rename preserves
    that, so without this every artefact the pipeline writes would be readable
    only by the user who ran it.
    """
    umask = os.umask(0)
    os.umask(umask)
    path.chmod(0o666 & ~umask)


def _atomic_write(path: Path, writer: Callable[[Path], None]) -> Path:
    """Write via a temporary file in the same directory, then rename into place.

    Args:
        path: final destination.
        writer: callback that writes the full content to the path it is given.

    Returns:
        The destination path.

    Raises:
        StorageError: the destination directory does not exist.
    """
    parent = _require_directory(path)
    handle, temp_name = tempfile.mkstemp(dir=parent, prefix=f".{path.name}.", suffix=".tmp")
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        writer(temp_path)
        _apply_default_permissions(temp_path)
        temp_path.replace(path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return path


def read_csv(
    path: Path,
    *,
    encoding: str = "utf-8",
    delimiter: str = ",",
    keep_all_as_text: bool = True,
    has_header: bool = True,
) -> pd.DataFrame:
    """Read a CSV file.

    Args:
        path: file to read.
        encoding: character encoding of the file.
        delimiter: field separator.
        keep_all_as_text: read every column as text. Ingest keeps this on so no
            value is silently reinterpreted before the cleaning rules run.
        has_header: whether the first row names the columns. A1 detects this
            and used to only report it - so a file without a header lost its
            first row to the column names, quietly, every time.

    Returns:
        The parsed frame.

    Raises:
        StorageError: the file does not exist or cannot be parsed.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file CSV: {path}")
    try:
        frame = pd.read_csv(
            path,
            encoding=encoding,
            delimiter=delimiter,
            dtype=str if keep_all_as_text else None,
            header=0 if has_header else None,
        )
        if not has_header:
            # pandas numbers them 0, 1, 2. Everything downstream addresses
            # columns by name, so they get names - neutral ones, because
            # inventing meaning here would be guessing at the file's subject.
            frame.columns = [f"cot_{index + 1}" for index in range(len(frame.columns))]
        return frame
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise StorageError(f"Khong doc duoc CSV {path}: {exc}") from exc


def read_parquet(path: Path) -> pd.DataFrame:
    """Read a Parquet file.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file Parquet: {path}")
    try:
        return pd.read_parquet(path)
    except (OSError, ValueError) as exc:
        raise StorageError(f"Khong doc duoc Parquet {path}: {exc}") from exc


def write_parquet(frame: pd.DataFrame, path: Path) -> Path:
    """Write a frame to Parquet atomically, without the index.

    Returns:
        The destination path.
    """

    def _write(target: Path) -> None:
        frame.to_parquet(target, index=False)

    return _atomic_write(path, _write)


def write_text(text: str, path: Path, *, encoding: str = "utf-8") -> Path:
    """Write text atomically with Unix line endings.

    Line endings are pinned so identical content always produces identical bytes
    regardless of platform.

    Returns:
        The destination path.
    """

    def _write(target: Path) -> None:
        target.write_text(text, encoding=encoding, newline="\n")

    return _atomic_write(path, _write)


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 over the bytes of a file, read in chunks.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file de bam hash: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise StorageError(f"Khong doc duoc file {path}: {exc}") from exc
    return digest.hexdigest()


def append_line(line: str, path: Path, *, encoding: str = "utf-8") -> Path:
    """Append one line to a file, creating the file if it does not exist.

    Append-only logs deliberately do not use the atomic rewrite path above:
    rewriting the whole file on every event would be slow and would turn each
    event into a chance to lose the history before it. A single small append
    under O_APPEND is atomic on POSIX, which is exactly what an audit log needs.

    Returns:
        The destination path.

    Raises:
        StorageError: the destination directory does not exist.
    """
    _require_directory(path)
    try:
        with path.open("a", encoding=encoding, newline="\n") as stream:
            stream.write(line.rstrip("\n") + "\n")
    except OSError as exc:
        raise StorageError(f"Khong ghi them duoc vao {path}: {exc}") from exc
    return path


def read_lines(path: Path, *, encoding: str = "utf-8") -> list[str]:
    """Read a text file as a list of lines with the line endings stripped.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file: {path}")
    try:
        return path.read_text(encoding=encoding).splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise StorageError(f"Khong doc duoc file {path}: {exc}") from exc


def read_text(path: Path, *, encoding: str = "utf-8") -> str:
    """Read a whole text file.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file: {path}")
    try:
        return path.read_text(encoding=encoding)
    except (OSError, UnicodeDecodeError) as exc:
        raise StorageError(f"Khong doc duoc file {path}: {exc}") from exc


def read_bytes(path: Path, *, limit: int | None = None) -> bytes:
    """Read raw bytes, optionally only the first *limit* of them.

    Detection has to happen before decoding, so this is the one read that
    returns bytes rather than a frame.

    Raises:
        StorageError: the file does not exist or cannot be read.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file: {path}")
    try:
        with path.open("rb") as stream:
            return stream.read() if limit is None else stream.read(limit)
    except OSError as exc:
        raise StorageError(f"Khong doc duoc file {path}: {exc}") from exc


def read_json(path: Path, *, encoding: str = "utf-8", lines: bool = False) -> pd.DataFrame:
    """Read a JSON or JSON Lines file into a frame.

    Raises:
        StorageError: the file does not exist or cannot be parsed.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file JSON: {path}")
    try:
        # dtype=False stops pandas inventing types of its own; the cast that
        # follows makes JSON arrive as text like every other source, so the
        # cleaning rules see the same thing whatever the file was.
        frame = pd.read_json(path, encoding=encoding, lines=lines, dtype=False)
    except (OSError, ValueError) as exc:
        raise StorageError(f"Khong doc duoc JSON {path}: {exc}") from exc
    return frame.astype("string")


# --- So tinh: NOI DUNG quyet dinh cach doc, khong phai duoi tep ---------------
#
# Duoi .xls khong noi len gi: bao cao tai chinh tai tu web thuong la mot trang
# HTML (co khi la XML SpreadsheetML 2003) mang duoi .xls, va pd.read_excel doan
# theo duoi roi hong. Tep that bi tu choi o day: "Khong doc duoc dinh dang".

_OLE2: Final[bytes] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_SNIFF_BYTES: Final[int] = 4096
_SPREADSHEET_NS: Final[str] = "urn:schemas-microsoft-com:office:spreadsheet"
_TEXT_ENCODINGS: Final[tuple[str, ...]] = ("utf-8-sig", "cp1258", "cp1252")
_MAX_SPAN: Final[int] = 50
# Cot dat them khi xep chong nhieu bang cung cot thanh mot.
SECTION_COLUMN: Final[str] = "Bảng"
ITEM_COLUMN: Final[str] = "Chỉ tiêu"
# Nhung quyet dinh luc doc (gop bang, bo bang) di kem khung trong frame.attrs,
# de nguoi goi bao lai cho nguoi dung thay vi de chung xay ra trong im lang.
READ_NOTES: Final[str] = "read_notes"
OLD_XLS: Final[str] = (
    "Tệp này là Excel 97-2003 thật (dạng nhị phân .xls), hệ thống chưa có thư viện đọc "
    "loại này. Mở tệp bằng Excel hoặc Google Sheets, lưu lại thành .xlsx hoặc .csv rồi "
    "tải lên lại."
)

Table = tuple[str, list[str], list[list[str]]]


def workbook_kind(path: Path) -> str:
    """Tệp mang đuôi Excel thật ra là gì: xlsx, xls (nhị phân 97-2003), html, spreadsheetml.

    Raises:
        StorageError: không mở được tệp.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(_SNIFF_BYTES)
    except OSError as exc:
        raise StorageError(f"Khong doc duoc {path}: {exc}") from exc
    if head.startswith(b"PK"):
        return "xlsx"
    if head.startswith(_OLE2):
        return "xls"
    text = head.decode("utf-8", errors="ignore").lower()
    # SpreadsheetML truoc: no cung co the <Table>, nhung khong bao gio co <html.
    if "<workbook" in text and _SPREADSHEET_NS in text:
        return "spreadsheetml"
    if "<html" in text or "<table" in text:
        return "html"
    return "unknown"


def _decoded(raw: bytes) -> str:
    for encoding in _TEXT_ENCODINGS:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def _tidy(text: str) -> str:
    return " ".join(text.split())


def _span(value: str | None, *, extra: bool = False) -> int:
    """So o mot o gop chiem (colspan), hoac so o them (extra: MergeAcross)."""
    least = 0 if extra else 1
    return max(least, min(int(value), _MAX_SPAN)) if value and value.isdigit() else least


def _grid(rows: list[list[str]]) -> list[list[str]]:
    """Bo dong trong han, don moi dong cho du be ngang."""
    kept = [row for row in rows if any(cell for cell in row)]
    width = max((len(row) for row in kept), default=0)
    return [row + [""] * (width - len(row)) for row in kept]


def _unique(names: list[str]) -> list[str]:
    """Ten cot: o trong thanh "Cột N", ten trung them " (2)"."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, name in enumerate(names):
        base = name or f"Cột {index + 1}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base} ({count})")
    return result


def _frame(header: list[str], body: list[list[str]]) -> pd.DataFrame:
    """Khung chu nguyen van: o trong thanh None, khong o nao bi doi thanh so."""
    width = len(header)
    rows = [[cell or None for cell in (row + [""] * width)[:width]] for row in body]
    return pd.DataFrame(rows, columns=header, dtype=object)


def _html_tables(path: Path) -> list[Table]:
    """Moi <table> thanh (ten bang, ten cot, cac dong), giu nguyen chu trong o.

    Dong <th> cuoi cung o dau bang la ten cot; dong dau (neu khac) la ten bang.
    Khong co <th> thi dong dau la ten cot, nhu cach doc mot sheet Excel.
    """
    try:
        from lxml import etree
        from lxml import html as lxml_html
    except ImportError as exc:  # pragma: no cover - lxml di kem python-docx
        raise StorageError("Chua cai lxml de doc bang HTML.") from exc
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", _decoded(path.read_bytes()))
    try:
        root = lxml_html.fromstring(text)
    except (ValueError, etree.ParserError, etree.XMLSyntaxError) as exc:
        raise StorageError(f"Khong doc duoc bang HTML trong {path.name}: {exc}") from exc
    tables: list[Table] = []
    for number, table in enumerate(root.xpath("//table[not(ancestor::table)]"), start=1):
        rows: list[list[str]] = []
        header_rows = 0
        leading = True
        for row in table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr"):
            cells = row.xpath("./th | ./td")
            values: list[str] = []
            for cell in cells:
                values.append(_tidy(cell.text_content()))
                values.extend([""] * (_span(cell.get("colspan")) - 1))
            if not any(values):
                continue
            if leading and cells and all(cell.tag == "th" for cell in cells):
                header_rows += 1
            else:
                leading = False
            rows.append(values)
        grid = _grid(rows)
        if not grid:
            continue
        cut = max(header_rows, 1)
        title = next((cell for cell in grid[0] if cell), "") or f"Bảng {number}"
        tables.append((title, _unique(grid[cut - 1]), grid[cut:]))
    return tables


def _pick(names: list[str], sheet: str | int, kind: str) -> int:
    if isinstance(sheet, str):
        if sheet not in names:
            raise StorageError(f"Khong co {kind} '{sheet}'. Co: {names}")
        return names.index(sheet)
    if not 0 <= sheet < len(names):
        raise StorageError(f"Khong co {kind} thu {sheet}. Co {len(names)} {kind}: {names}")
    return sheet


def _html_workbook(path: Path, sheet: str | int) -> pd.DataFrame:
    """Bang HTML: cac bang cung cot thi xep chong (cot "Bảng" ghi nguon), khac cot thi bang dau."""
    tables = _html_tables(path)
    if not tables:
        raise StorageError(f"Khong tim thay bang nao trong {path.name}.")
    titles = [title for title, _, _ in tables]
    if sheet != 0 or len(tables) == 1:
        _, header, body = tables[_pick(titles, sheet, "bang")]
        return _frame(header, body)
    tail = tables[0][1][1:]
    if tail and all(header[1:] == tail for _, header, _ in tables):
        rows = [[title, *row] for title, _, body in tables for row in body]
        frame = _frame(_unique([SECTION_COLUMN, ITEM_COLUMN, *tail]), rows)
        frame.attrs[READ_NOTES] = [
            f"Tệp có {len(tables)} bảng cùng cột ({'; '.join(titles)}), đã xếp chồng thành "
            f"một bảng: cột '{SECTION_COLUMN}' ghi mỗi dòng thuộc bảng nào, cột "
            f"'{ITEM_COLUMN}' là cột đầu của mỗi bảng."
        ]
        return frame
    frame = _frame(tables[0][1], tables[0][2])
    frame.attrs[READ_NOTES] = [
        f"Tệp có {len(tables)} bảng khác cột nhau, chỉ đọc bảng '{titles[0]}' và bỏ: "
        f"{'; '.join(titles[1:])}. Muốn đọc bảng khác thì chọn nó theo tên."
    ]
    return frame


def _spreadsheet_ml(path: Path) -> list[tuple[str, list[list[str]]]]:
    """XML SpreadsheetML 2003: moi Worksheet mot luoi chu, hieu ss:Index va MergeAcross."""
    names = {"ss": _SPREADSHEET_NS}
    key = f"{{{_SPREADSHEET_NS}}}"
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        raise StorageError(f"Khong doc duoc SpreadsheetML {path.name}: {exc}") from exc
    sheets: list[tuple[str, list[list[str]]]] = []
    for number, sheet in enumerate(root.findall("ss:Worksheet", names), start=1):
        rows: list[list[str]] = []
        for row in sheet.findall("ss:Table/ss:Row", names):
            values: list[str] = []
            for cell in row.findall("ss:Cell", names):
                index = cell.get(f"{key}Index")
                if index and index.isdigit():
                    values.extend([""] * max(0, int(index) - 1 - len(values)))
                data = cell.find("ss:Data", names)
                values.append(_tidy("".join(data.itertext())) if data is not None else "")
                # MergeAcross dem so o THEM ben phai, khac colspan cua HTML (tong so o).
                values.extend([""] * (_span(cell.get(f"{key}MergeAcross"), extra=True)))
            rows.append(values)
        sheets.append((sheet.get(f"{key}Name") or f"Sheet{number}", _grid(rows)))
    return sheets


def _spreadsheet_ml_workbook(path: Path, sheet: str | int) -> pd.DataFrame:
    sheets = _spreadsheet_ml(path)
    if not sheets:
        raise StorageError(f"Khong tim thay Worksheet nao trong {path.name}.")
    _, grid = sheets[_pick([name for name, _ in sheets], sheet, "sheet")]
    if not grid:
        return pd.DataFrame()
    return _frame(_unique(grid[0]), grid[1:])


def read_excel(path: Path, *, sheet: str | int = 0) -> pd.DataFrame:
    """Read one sheet of a workbook into a frame, every column as text.

    Cách đọc chọn theo NỘI DUNG tệp (`workbook_kind`), không theo đuôi. Quyết
    định lúc đọc (gộp bảng, bỏ bảng) nằm trong `frame.attrs[READ_NOTES]`.

    Raises:
        StorageError: the file does not exist or cannot be read; for a genuine
            Excel 97-2003 file without a reader, the message says what to do.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file Excel: {path}")
    kind = workbook_kind(path)
    if kind == "html":
        return _html_workbook(path, sheet)
    if kind == "spreadsheetml":
        return _spreadsheet_ml_workbook(path, sheet)
    try:
        if kind == "xls":
            return pd.read_excel(path, sheet_name=sheet, dtype=str)
        # Mot .xlsx doi ten thanh .xls: ep openpyxl, khong de pandas doan theo duoi.
        return pd.read_excel(path, sheet_name=sheet, dtype=str, engine="openpyxl")
    except ImportError as exc:
        if kind == "xls":
            raise StorageError(OLD_XLS) from exc
        raise StorageError("Chua cai openpyxl. Cai bang: pip install openpyxl") from exc
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise StorageError(f"Khong doc duoc Excel {path}: {exc}") from exc


def excel_sheets(path: Path) -> list[str]:
    """Names of every sheet in a workbook (for an HTML page: the name of each table).

    Raises:
        StorageError: the workbook cannot be opened.
    """
    if not path.is_file():
        raise StorageError(f"Khong tim thay file Excel: {path}")
    kind = workbook_kind(path)
    if kind == "html":
        return [title for title, _, _ in _html_tables(path)]
    if kind == "spreadsheetml":
        return [name for name, _ in _spreadsheet_ml(path)]
    try:
        with pd.ExcelFile(path, engine=None if kind == "xls" else "openpyxl") as book:
            return [str(name) for name in book.sheet_names]
    except ImportError as exc:
        if kind == "xls":
            raise StorageError(OLD_XLS) from exc
        raise StorageError(f"Khong doc duoc danh sach sheet cua {path}: {exc}") from exc
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise StorageError(f"Khong doc duoc danh sach sheet cua {path}: {exc}") from exc


def write_bytes(payload: bytes, path: Path) -> Path:
    """Write binary content atomically.

    Returns:
        The destination path.
    """

    def _write(target: Path) -> None:
        target.write_bytes(payload)

    return _atomic_write(path, _write)


def ensure_directory(path: Path) -> Path:
    """Create a directory and its parents.

    Used only for a directory inside a layer the caller already has permission
    to write to; the scope check happens before this is ever reached.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path
