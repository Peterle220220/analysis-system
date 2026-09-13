"""Từ cấu hình kéo thả (JSON) ra kết quả, không qua model.

Trình duyệt gửi: trục X, trục Y cùng phép gộp, Legend, bộ lọc. Ở đây code dựng
câu SQL cho DuckDB và đọc thẳng tệp Parquet của bảng sạch:

* tên cột do code đặt trong ngoặc kép, không bao giờ ghép nguyên chuỗi người
  dùng vào câu lệnh, và phải có thật trong bảng;
* giá trị lọc đi bằng tham số `?`;
* phép gộp chỉ lấy trong một danh sách cố định.

Nên dù JSON gửi lên viết gì, không có câu lệnh lạ nào chạy được.

Hai hình dạng kết quả: gộp nhóm (trục X là Dimension: cột, đường, vành khuyên,
thác nước, bảng) và từng điểm (trục X và Y đều là Measure: phân tán).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import duckdb
import pandas as pd
from pydantic import BaseModel, ConfigDict
from pydantic import Field as Default

from analysis_system.services.bi_schema import Field

AGGREGATIONS: Final[dict[str, str]] = {
    "sum": "SUM({})",
    "mean": "AVG({})",
    "median": "MEDIAN({})",
    "min": "MIN({})",
    "max": "MAX({})",
    "count": "COUNT({})",
    "count_distinct": "COUNT(DISTINCT {})",
}
AGGREGATION_LABELS: Final[dict[str, str]] = {
    "sum": "Tổng",
    "mean": "Trung bình",
    "median": "Trung vị",
    "min": "Nhỏ nhất",
    "max": "Lớn nhất",
    "count": "Số giá trị",
    "count_distinct": "Số giá trị khác nhau",
}
# Phép gộp cần con số: cộng hay lấy trung bình một cột chữ thì không có nghĩa.
NUMERIC_ONLY: Final[frozenset[str]] = frozenset({"sum", "mean", "median", "min", "max"})
# Trục X là chữ: chỉ vẽ chừng này nhóm lớn nhất, và nói rõ đã bỏ bao nhiêu.
MAX_CATEGORIES: Final[int] = 60
# Trục X là ngày hay mã số: chừng này điểm, theo thứ tự.
MAX_POINTS: Final[int] = 1000
# Legend: tám màu đã kiểm cho người mù màu; nhóm thứ tám trở đi gộp thành "Khác".
MAX_SERIES: Final[int] = 8
# Phân tán: vẽ tối đa chừng này điểm (một mẫu cố định hạt giống); hệ số tương
# quan vẫn tính trên mọi cặp, không trên mẫu.
MAX_SCATTER: Final[int] = 5000
# Bộ lọc của một Dimension liệt kê chừng này giá trị phổ biến nhất.
MAX_VALUES: Final[int] = 200
OTHER: Final[str] = "Khác"
EMPTY: Final[str] = "(trống)"
SCATTER_NEEDS_Y: Final[str] = (
    "Trục X là Measure thì Trục Y cũng phải là Measure: hai cột số vẽ thành biểu đồ phân tán."
)


class BiQueryError(ValueError):
    """Cấu hình không chạy được. Câu lỗi viết để hiện thẳng cho người dùng."""


class BiFilter(BaseModel):
    """Một bộ lọc: Dimension lọc theo danh sách giá trị, Measure theo khoảng."""

    model_config = ConfigDict(extra="forbid")

    field: str
    values: list[str] | None = None
    min: float | None = None
    max: float | None = None


class BiQuery(BaseModel):
    """Cấu hình kéo thả. Khoá lạ bị từ chối: không có chỗ nào để nhét SQL."""

    model_config = ConfigDict(extra="forbid")

    x: str | None = None
    y: str | None = None
    aggregation: str = "mean"
    color: str | None = None
    filters: list[BiFilter] = Default(default_factory=list)
    # Chỉ giữ chừng này nhóm trên trục X, phần còn lại gộp thành "Khác" (vành khuyên).
    top: int | None = Default(default=None, ge=2, le=50)


def quote(name: str) -> str:
    """Tên cột trong ngoặc kép của SQL; dấu nháy kép bên trong được nhân đôi."""
    return '"' + name.replace('"', '""') + '"'


def _number(name: str) -> str:
    return f"TRY_CAST({quote(name)} AS DOUBLE)"


def _label(name: str) -> str:
    return f"COALESCE(CAST({quote(name)} AS VARCHAR), '{EMPTY}')"


def _placeholders(count: int) -> str:
    return ", ".join("?" for _ in range(count))


def _known(fields: dict[str, Field], name: str) -> Field:
    found = fields.get(name)
    if found is None:
        raise BiQueryError(f"Bảng không có cột '{name}'.")
    return found


def _dimension(fields: dict[str, Field], name: str | None, zone: str) -> Field | None:
    if name is None:
        return None
    field = _known(fields, name)
    if field.role != "dimension":
        raise BiQueryError(f"{zone} chỉ nhận Dimension; '{name}' là Measure.")
    return field


def _where(query: BiQuery, fields: dict[str, Field]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for item in query.filters:
        field = _known(fields, item.field)
        if item.values is not None or field.role == "dimension":
            chosen = [str(value) for value in item.values or []]
            # Chưa chọn giá trị nào thì bộ lọc chưa có hiệu lực, không phải "lọc hết".
            if chosen:
                clauses.append(f"{_label(field.name)} IN ({_placeholders(len(chosen))})")
                params.extend(chosen)
            continue
        if item.min is not None:
            clauses.append(f"{_number(field.name)} >= ?")
            params.append(item.min)
        if item.max is not None:
            clauses.append(f"{_number(field.name)} <= ?")
            params.append(item.max)
    return (" WHERE " + " AND ".join(clauses) if clauses else ""), params


def _aggregate(query: BiQuery, fields: dict[str, Field]) -> str:
    if query.aggregation not in AGGREGATIONS:
        raise BiQueryError(f"Không có phép gộp '{query.aggregation}'.")
    if query.y is None:
        return "COUNT(*)"
    field = _known(fields, query.y)
    if query.aggregation in NUMERIC_ONLY and field.role != "measure":
        raise BiQueryError(f"'{field.name}' không phải cột số, chỉ đếm được.")
    target = _number(field.name) if field.role == "measure" else quote(field.name)
    return AGGREGATIONS[query.aggregation].format(target)


def _connect(source: Path) -> duckdb.DuckDBPyConnection:
    """Một DuckDB trong bộ nhớ cho đúng một lần tính, đọc thẳng tệp Parquet."""
    connection = duckdb.connect()
    # Đường dẫn do máy chủ dựng từ bảng sạch, không phải do người dùng gửi.
    path = str(source).replace("'", "''")
    connection.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet('{path}')")
    return connection


def _missing(value: Any) -> bool:
    return value is None or (not isinstance(value, str) and bool(pd.isna(value)))


def _plain(value: Any) -> Any:
    """Giá trị Python thuần, sẵn cho JSON: số numpy thành số, NaN thành None."""
    if _missing(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _text(value: Any) -> str:
    """Nhãn trên trục: rỗng thành '(trống)', ngày không giờ chỉ ghi ngày, 1.0 thành 1."""
    if _missing(value):
        return EMPTY
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value == value.normalize() else value.isoformat()
    plain = value.item() if hasattr(value, "item") else value
    if isinstance(plain, float) and plain.is_integer():
        return str(int(plain))
    return str(plain)


def _order_key(value: Any) -> tuple[int, Any]:
    return (1, 0) if _missing(value) else (0, value)


def _series(
    connection: duckdb.DuckDBPyConnection, color: Field, where: str, params: list[Any]
) -> tuple[list[str], str, list[Any], bool]:
    """Các nhóm màu của Legend: tám nhóm đông nhất, nhóm thứ tám trở đi thành "Khác".

    Returns:
        (tên các chuỗi, biểu thức SQL của chuỗi, tham số của biểu thức, có gộp "Khác").
    """
    top = connection.execute(
        f"SELECT {_label(color.name)} AS s, COUNT(*) AS n FROM t{where} "
        f"GROUP BY 1 ORDER BY n DESC, s LIMIT {MAX_SERIES + 1}",
        params,
    ).fetchall()
    names = [str(row[0]) for row in top]
    if len(names) <= MAX_SERIES:
        return names, _label(color.name), [], False
    kept = names[: MAX_SERIES - 1]
    sql = (
        f"CASE WHEN {_label(color.name)} IN ({_placeholders(len(kept))}) "
        f"THEN {_label(color.name)} ELSE ? END"
    )
    return [*kept, OTHER], sql, [*kept, OTHER], True


def _shape(
    frame: pd.DataFrame, x: Field | None, names: list[str], folded: bool
) -> tuple[list[str], list[dict[str, Any]], int]:
    """Kết quả SQL thành các nhóm trên trục và mỗi chuỗi một dãy giá trị."""
    if x is None:
        single = {str(row.series): _plain(row.value) for row in frame.itertuples(index=False)}
        return [], [{"name": name, "values": [single.get(name)]} for name in names], 0
    totals = frame.groupby("x", dropna=False, sort=False)["value"].sum(min_count=1)
    if x.kind == "text" or folded:
        order = list(totals.sort_values(ascending=False, na_position="last", kind="stable").index)
        limit = MAX_CATEGORIES
    else:
        order = sorted(totals.index, key=_order_key)
        limit = MAX_POINTS
    if folded and OTHER in order:
        # "Khác" luôn đứng cuối, dù tổng của nó lớn hơn nhóm nào.
        order = [value for value in order if value != OTHER] + [OTHER]
    categories = [_text(value) for value in order[:limit]]
    cells = {
        (_text(row.x), str(row.series)): _plain(row.value) for row in frame.itertuples(index=False)
    }
    series = [
        {"name": name, "values": [cells.get((category, name)) for category in categories]}
        for name in names
    ]
    return categories, series, max(0, len(order) - limit)


def _scatter(
    source: Path, query: BiQuery, known: dict[str, Field], x: Field, color: Field | None
) -> dict[str, Any]:
    """Hai Measure: mỗi dòng một điểm, không gộp; kèm hệ số tương quan trên mọi cặp."""
    if query.y is None:
        raise BiQueryError(SCATTER_NEEDS_Y)
    y = _known(known, query.y)
    if y.role != "measure":
        raise BiQueryError(SCATTER_NEEDS_Y)
    where, params = _where(query, known)
    both = f"{_number(x.name)} IS NOT NULL AND {_number(y.name)} IS NOT NULL"
    scoped = f"{where} AND {both}" if where else f" WHERE {both}"

    names = [y.name]
    other = False
    series_sql = "NULL"
    series_params: list[Any] = []
    connection = _connect(source)
    try:
        counted = connection.execute(f"SELECT COUNT(*) FROM t{where}", params).fetchone()
        stats = connection.execute(
            f"SELECT COUNT(*), corr({_number(x.name)}, {_number(y.name)}) FROM t{scoped}", params
        ).fetchone()
        if color is not None:
            names, series_sql, series_params, other = _series(connection, color, scoped, params)
        inner = (
            f"SELECT {_number(x.name)} AS x, {_number(y.name)} AS y, {series_sql} AS series "
            f"FROM t{scoped}"
        )
        pairs = int(stats[0]) if stats else 0
        sampled = pairs > MAX_SCATTER
        # Mẫu lấy SAU khi lọc (câu con), hạt giống cố định: hỏi lại thì ra đúng các điểm đó.
        sql = (
            f"SELECT * FROM ({inner}) USING SAMPLE reservoir({MAX_SCATTER} ROWS) REPEATABLE (7)"
            if sampled
            else inner
        )
        frame = connection.execute(sql, [*series_params, *params]).fetch_df()
    except duckdb.Error as error:
        raise BiQueryError(f"DuckDB không chạy được cấu hình này: {error}") from error
    finally:
        connection.close()

    if color is None:
        frame["series"] = y.name
    points: dict[str, list[list[Any]]] = {name: [] for name in names}
    for row in frame.itertuples(index=False):
        points.setdefault(str(row.series), []).append([_plain(row.x), _plain(row.y)])
    title = f"{y.name} theo {x.name}" + (f", tách màu theo {color.name}" if color else "")
    return {
        "kind": "scatter",
        "title": title,
        "x_label": x.name,
        "value_label": y.name,
        "categories": [],
        "series": [{"name": name, "values": [], "points": points.get(name, [])} for name in names],
        "rows_used": int(counted[0]) if counted else 0,
        "pairs": pairs,
        "correlation": _plain(stats[1]) if stats else None,
        "sampled": sampled,
        "dropped": 0,
        "other_series": other,
        "folded_x": False,
        "sql": sql,
        "params": [*series_params, *params],
    }


def run_query(source: Path, query: BiQuery, fields: list[Field]) -> dict[str, Any]:
    """Chạy một cấu hình kéo thả trên tệp Parquet, trả về dạng sẵn để vẽ.

    Raises:
        BiQueryError: cấu hình không chạy được, kèm lý do bằng tiếng Việt.
    """
    known = {field.name: field for field in fields}
    color = _dimension(known, query.color, "Phân nhóm (Legend)")
    x = _known(known, query.x) if query.x is not None else None
    if x is not None and x.role == "measure":
        return _scatter(source, query, known, x, color)
    if x is None and color is not None:
        # Chỉ có Legend thì Legend chính là trục: mỗi nhóm một cột.
        x, color = color, None
    if x is None and query.y is None:
        raise BiQueryError("Thả ít nhất một cột vào Trục X hoặc Trục Y.")
    value = _aggregate(query, known)
    where, params = _where(query, known)
    label = f"{AGGREGATION_LABELS[query.aggregation]} {query.y}" if query.y else "Số dòng"

    names = [label]
    other = False
    folded = False
    series_sql = "NULL"
    series_params: list[Any] = []
    x_sql = quote(x.name) if x is not None else "NULL"
    x_params: list[Any] = []
    connection = _connect(source)
    try:
        counted = connection.execute(f"SELECT COUNT(*) FROM t{where}", params).fetchone()
        if color is not None:
            names, series_sql, series_params, other = _series(connection, color, where, params)
        if x is not None and query.top is not None:
            ranked = connection.execute(
                f"SELECT {_label(x.name)} AS k, {value} AS v FROM t{where} "
                f"GROUP BY 1 ORDER BY v DESC NULLS LAST, k LIMIT {query.top + 1}",
                params,
            ).fetchall()
            x_sql = _label(x.name)
            if len(ranked) > query.top:
                kept = [str(row[0]) for row in ranked[: query.top - 1]]
                x_sql = (
                    f"CASE WHEN {_label(x.name)} IN ({_placeholders(len(kept))}) "
                    f"THEN {_label(x.name)} ELSE ? END"
                )
                x_params = [*kept, OTHER]
                folded = True
        sql = (
            f"SELECT {x_sql} AS x, {series_sql} AS series, {value} AS value "
            f"FROM t{where} GROUP BY ALL"
        )
        frame = connection.execute(sql, [*x_params, *series_params, *params]).fetch_df()
    except duckdb.Error as error:
        raise BiQueryError(f"DuckDB không chạy được cấu hình này: {error}") from error
    finally:
        connection.close()

    if color is None:
        frame["series"] = label
    categories, series, dropped = _shape(frame, x, names, folded)
    title = label
    if x is not None:
        title += f" theo {x.name}"
    if color is not None:
        title += f", tách màu theo {color.name}"
    return {
        "kind": "single" if x is None else ("line" if x.kind == "date" else "bar"),
        "title": title,
        "x_label": x.name if x is not None else "",
        "value_label": label,
        "categories": categories,
        "series": series,
        "rows_used": int(counted[0]) if counted else 0,
        "dropped": dropped,
        "other_series": other,
        "folded_x": folded,
        "sql": sql,
        "params": [*x_params, *series_params, *params],
    }


def field_values(source: Path, field: Field, limit: int = MAX_VALUES) -> dict[str, Any]:
    """Các giá trị để chọn trong bộ lọc: Dimension thì giá trị phổ biến, Measure thì min/max.

    Raises:
        BiQueryError: tệp không đọc được.
    """
    connection = _connect(source)
    try:
        if field.role == "measure":
            found = connection.execute(
                f"SELECT MIN({_number(field.name)}), MAX({_number(field.name)}) FROM t"
            ).fetchone()
            low, high = found if found else (None, None)
            return {"field": field.name, "role": "measure", "min": _plain(low), "max": _plain(high)}
        rows = connection.execute(
            f"SELECT {_label(field.name)} AS v, COUNT(*) AS c FROM t "
            "GROUP BY 1 ORDER BY c DESC, v LIMIT ?",
            [limit + 1],
        ).fetchall()
    except duckdb.Error as error:
        raise BiQueryError(f"DuckDB không đọc được cột này: {error}") from error
    finally:
        connection.close()
    return {
        "field": field.name,
        "role": "dimension",
        "values": [{"value": str(value), "count": int(count)} for value, count in rows[:limit]],
        "more": len(rows) > limit,
    }
