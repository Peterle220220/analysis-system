"""What a person can choose to analyse, and what happens when they change it.

The request behind this module was ordinary: a table has columns A to E, someone
only cares about A and E, and they want to say so and get an analysis of A and E.
Then change their mind and get a different one.

The reason it is not simply "a list of columns" is the sentence that followed it.
Give the system images and the things worth choosing between are *detected
objects*; give it a recording and they are *speakers*; give it an event log and
they are *activities* and *people*. A selection mechanism built around columns
would have to be replaced the first time the input stopped being a table, and
replaced again after that.

So the unit here is a **feature**: something in the data that can be picked or
left out. A column is one kind of feature. An activity is another. The kinds are
open, and nothing outside the extractors knows what a column is.

Two things this module refuses to do:

* **Silently ignore a name it does not recognise.** Someone selecting `exam_scr`
  has made a typo, and quietly analysing the four features they spelled right is
  how they end up reading an answer to a question they did not ask.
* **Decide what a feature means.** It reports what the data shows - this column
  is numeric, this one has six distinct values - and leaves the judgement to the
  person choosing. A "role" here is a measurement, not an opinion.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final

import pandas as pd

# The kinds that exist today. Deliberately a plain string rather than an enum:
# an extractor for a data type nobody has written yet must be able to add its
# own kind without editing this file, which is the whole point of the
# abstraction. The constants below are the ones code currently reads.
KIND_COLUMN: Final[str] = "column"
KIND_ACTIVITY: Final[str] = "activity"
KIND_RESOURCE: Final[str] = "resource"

SEPARATOR: Final[str] = ":"

# What a column looks like, measured rather than judged.
ROLE_NUMERIC: Final[str] = "numeric"
ROLE_CATEGORICAL: Final[str] = "categorical"
ROLE_TEMPORAL: Final[str] = "temporal"
ROLE_IDENTIFIER: Final[str] = "identifier"
ROLE_TEXT: Final[str] = "text"

# Above this share of distinct values a column identifies rows rather than
# grouping them. Breaking an analysis down by it produces one group per row.
IDENTIFIER_SHARE: Final[float] = 0.9
# Below this share of parseable numbers a column is not a number column, whatever
# the few values that did parse suggest.
NUMERIC_SHARE: Final[float] = 0.9
MAX_CATEGORIES: Final[int] = 50


class FeatureError(ValueError):
    """A selection refers to something that is not there.

    Distinct from an empty selection, which is a legitimate way of saying "all
    of it". This means a name was given that the data does not have.
    """


@dataclass(frozen=True)
class Feature:
    """One thing in the data that can be chosen or left out.

    Args:
        kind: what sort of thing it is - a column, an activity, a speaker.
        name: what the data itself calls it.
        role: what it looks like, measured. Empty when the kind has no roles.
        detail: one line for the person doing the choosing.
    """

    kind: str
    name: str
    role: str = ""
    detail: str = ""

    @property
    def key(self) -> str:
        """The stable identifier a selection refers to."""
        return f"{self.kind}{SEPARATOR}{self.name}"


def parse_key(key: str) -> tuple[str, str]:
    """Split a feature key back into its kind and name.

    Split once, from the left, because a name may well contain the separator -
    a real event log has an activity called "SRM: Created". Splitting on every
    colon would turn that into a kind nobody declared.

    Raises:
        FeatureError: the key has no kind at all.
    """
    kind, found, name = key.partition(SEPARATOR)
    if not found or not kind or not name:
        raise FeatureError(f"khoa dac trung {key!r} phai co dang 'loai:ten'.")
    return kind, name


@dataclass(frozen=True)
class FeatureCatalogue:
    """Everything in this data that a person could choose between."""

    source: str
    features: tuple[Feature, ...] = ()

    def keys(self) -> tuple[str, ...]:
        """Every key, in a fixed order so two runs list the same thing."""
        return tuple(feature.key for feature in self.features)

    def of_kind(self, kind: str) -> tuple[Feature, ...]:
        """Every feature of one kind, in catalogue order."""
        return tuple(feature for feature in self.features if feature.kind == kind)

    def get(self, key: str) -> Feature | None:
        """The feature with this key, or None."""
        for feature in self.features:
            if feature.key == key:
                return feature
        return None

    def as_rows(self) -> list[dict[str, str]]:
        """The catalogue in the shape a listing or a prompt can carry."""
        return [
            {
                "key": feature.key,
                "kind": feature.kind,
                "name": feature.name,
                "role": feature.role,
                "detail": feature.detail,
            }
            for feature in self.features
        ]


@dataclass(frozen=True)
class Selection:
    """What a person chose to analyse.

    An empty selection means "everything", which is the state before anyone has
    chosen. It is not the same as choosing nothing, and the difference matters:
    the first is a default, the second would be a request for an empty analysis
    and is refused when it is checked.
    """

    keys: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """True when nothing was chosen and everything therefore applies."""
        return not self.keys

    @classmethod
    def from_params(cls, raw: Any) -> Selection:
        """Read a selection out of scope params or a stored decision.

        Raises:
            FeatureError: the selection is not shaped like one.
        """
        if raw is None:
            return cls()
        if not isinstance(raw, list | tuple):
            raise FeatureError("lua chon dac trung phai la mot danh sach khoa.")
        # Sorted and de-duplicated, because a selection is a *set* and two
        # people picking the same features in a different order are asking the
        # same question. Without this the params fingerprint would differ and
        # the task would re-run for no reason (see L40).
        return cls(keys=tuple(sorted({str(key) for key in raw})))

    def names_of(self, kind: str) -> tuple[str, ...]:
        """The chosen names of one kind, in a fixed order."""
        return tuple(
            name
            for name, feature_kind in (parse_key(key)[::-1] for key in self.keys)
            if feature_kind == kind
        )

    def validate(self, catalogue: FeatureCatalogue) -> None:
        """Refuse a selection naming something the data does not have.

        Raises:
            FeatureError: at least one key is not in the catalogue. Analysing
                the ones that were spelled correctly and saying nothing is how
                somebody reads an answer to a question they did not ask.
        """
        known = set(catalogue.keys())
        missing = sorted(key for key in self.keys if key not in known)
        if not missing:
            return
        raise FeatureError(
            f"khong co dac trung {missing} trong du lieu. "
            "Khong phan tich phan con lai va bo qua - mot lua chon go sai ten "
            "se thanh mot cau tra loi cho cau hoi khac."
        )


def _role_of(series: pd.Series[Any], rows: int) -> tuple[str, str]:
    """What a column looks like, and one line describing it.

    Measured, not judged. The caller decides what to do about it; this only
    reports what is there.
    """
    present = series.dropna()
    if present.empty:
        return ROLE_TEXT, "khong co gia tri nao"

    distinct = int(present.nunique())
    filled = f"{len(present)}/{rows} dong co gia tri"

    if pd.api.types.is_datetime64_any_dtype(series):
        return ROLE_TEMPORAL, f"moc thoi gian, {filled}"

    parsed = pd.to_numeric(present, errors="coerce")
    if float(parsed.notna().sum()) / float(len(present)) >= NUMERIC_SHARE:
        return ROLE_NUMERIC, f"so, {distinct} gia tri khac nhau, {filled}"

    if rows and distinct / rows >= IDENTIFIER_SHARE:
        # One group per row is not a breakdown, it is the table again.
        return ROLE_IDENTIFIER, f"gan nhu moi dong mot gia tri ({distinct}) - dinh danh"
    if distinct <= MAX_CATEGORIES:
        return ROLE_CATEGORICAL, f"{distinct} nhom"
    return ROLE_TEXT, f"{distinct} gia tri khac nhau, qua nhieu de lam nhom"


def columns_of(frame: pd.DataFrame) -> list[Feature]:
    """Every column of a table, as features a person can choose between."""
    rows = len(frame.index)
    return [
        Feature(kind=KIND_COLUMN, name=str(name), role=role, detail=detail)
        for name in frame.columns
        for role, detail in [_role_of(frame[name], rows)]
    ]


def event_features_of(frame: pd.DataFrame, activity: str, resource: str = "") -> list[Feature]:
    """The activities and people in an event log, as features.

    This is the case the abstraction exists for. Nothing above this function
    knows that an activity is not a column, and nothing has to: both are things
    a person can include or leave out of an analysis.
    """
    found: list[Feature] = []
    if activity in frame.columns:
        counts = frame[activity].dropna().astype(str).value_counts()
        found.extend(
            Feature(
                kind=KIND_ACTIVITY,
                name=str(name),
                role="",
                detail=f"{int(counts[name])} su kien",
            )
            for name in sorted(counts.index, key=str)
        )
    if resource and resource in frame.columns:
        counts = frame[resource].dropna().astype(str).value_counts()
        found.extend(
            Feature(
                kind=KIND_RESOURCE,
                name=str(name),
                role="",
                detail=f"{int(counts[name])} su kien",
            )
            for name in sorted(counts.index, key=str)
        )
    return found


def catalogue_for(
    frame: pd.DataFrame,
    source: str,
    *,
    activity: str = "",
    resource: str = "",
) -> FeatureCatalogue:
    """Everything choosable in this data, whatever kind of data it is.

    Args:
        frame: the table. It is never modified.
        source: where it came from, recorded so a selection can be traced back.
        activity: the activity column, when the table is an event log.
        resource: the performer column, when there is one.

    Returns:
        The catalogue, in a fixed order.
    """
    features: list[Feature] = columns_of(frame)
    if activity:
        features.extend(event_features_of(frame, activity, resource))
    return FeatureCatalogue(source=source, features=tuple(features))


def restrict(frame: pd.DataFrame, selection: Selection) -> pd.DataFrame:
    """The table with only the chosen columns, or unchanged when nothing was chosen.

    Column kinds only. Restricting by activity is a *filter on rows* and belongs
    with the miner that understands what a case is - dropping events from the
    middle of a case here would silently rewrite everybody's process.

    Raises:
        FeatureError: the selection names no column that exists.
    """
    wanted = selection.names_of(KIND_COLUMN)
    if not wanted:
        return frame
    present = [name for name in frame.columns if str(name) in set(wanted)]
    if not present:
        raise FeatureError(f"khong con cot nao sau khi loc theo {list(wanted)}.")
    return frame[present]


def describe(catalogue: FeatureCatalogue, selection: Selection) -> list[str]:
    """One line per feature, marking what is in and what is out.

    For a person about to confirm a choice. Reading back what was understood is
    the cheapest way to catch a selection that means something other than what
    was intended.
    """
    chosen = set(selection.keys)
    return [
        f"{'[x]' if (feature.key in chosen or selection.is_empty) else '[ ]'} "
        f"{feature.key} - {feature.role or feature.kind}: {feature.detail}"
        for feature in catalogue.features
    ]


def kinds_in(features: Iterable[Feature]) -> tuple[str, ...]:
    """Every kind present, sorted, so a listing groups the same way twice."""
    return tuple(sorted({feature.kind for feature in features}))


def merge(catalogues: Sequence[FeatureCatalogue], source: str) -> FeatureCatalogue:
    """One catalogue from several, keeping the first description of each key.

    For inputs that arrive in pieces - several tables, or a table plus a
    transcript. First wins rather than last, so adding a source never changes
    what an existing key means.
    """
    seen: dict[str, Feature] = {}
    for catalogue in catalogues:
        for feature in catalogue.features:
            seen.setdefault(feature.key, feature)
    return FeatureCatalogue(source=source, features=tuple(seen.values()))
