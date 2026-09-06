"""What a model measures about the data you have, never what it guesses about data you don't.

The whole system rests on one rule: every conclusion traces back to rows somebody
can go and look at. A prediction breaks it - "this customer has a 73% chance of
leaving" traces to a model, a training split and a random seed, and nobody can
inspect the thing that makes it true.

So nothing here predicts. Two things are measured instead, and both are
statements about the rows in front of you:

* **Which variables carry the outcome, and how much of it.** That is a property
  of the data, the same kind of thing a correlation is, and it traces the same way.
* **Which rows resemble each other.** A cluster label describes the row it is
  attached to. It says nothing about a row nobody has seen.

**The refusals do most of the work here, more than anywhere else in the system.**
Both techniques produce confident-looking output on data that cannot support
them: a tree will rank variables on thirty rows, and k-means will return five
tidy clusters from a single formless cloud. Neither says so. So:

* An importance ranking is **refit under several seeds** and thrown away if the
  order moves. Tree importances are notoriously unstable, and a ranking that
  changes with the seed is a ranking of nothing - but it reads exactly like a
  finding.
* A clustering is measured for whether the groups are actually separated, and
  refused when they are not. Any number of clusters can be imposed on any cloud
  of points; the question is whether they were already there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score, silhouette_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from analysis_system.contracts.agents import MetricValue

DECIMALS: Final[int] = 4
# Ten rows per variable, the same floor the regression uses. Below it a model is
# fitting the rows rather than what produced them.
MIN_PER_FEATURE: Final[int] = 10
MIN_ROWS: Final[int] = 40
# Seeds the importance ranking is refit under. Fixed, so two runs agree; several,
# so an unstable ranking cannot hide behind one lucky draw.
SEEDS: Final[tuple[int, ...]] = (0, 7, 13, 21, 42)
# How much of the outcome a model must account for on rows it never saw before
# its importances describe anything but noise.
MIN_HOLDOUT_R2: Final[float] = 0.1
# Share of the data held back. Never fitted on, so the score is honest.
HOLDOUT_SHARE: Final[float] = 0.25

# A floor, not the test. Below this nothing is worth reporting whatever the
# comparison says.
MIN_SILHOUETTE: Final[float] = 0.25
# How far the real data must beat structureless data of the same shape before its
# groups are called groups.
#
# A fixed threshold cannot do this job: three hundred points from one Gaussian
# separate at 0.35, past any floor worth setting, because how separated k-means
# can make a cloud look depends on the number of columns and their spread rather
# than on whether groups were there. The comparison asks the question that has an
# answer.
MIN_GAP: Final[float] = 0.08
CLUSTER_RANGE: Final[tuple[int, ...]] = (2, 3, 4, 5, 6)
MIN_CLUSTER_ROWS: Final[int] = 5
TOP_FEATURES: Final[int] = 8


class ModellingError(ValueError):
    """The request itself is malformed, as opposed to the data being too thin."""


def _round(value: float) -> float:
    """One rounding rule, so two runs agree to the last digit."""
    return round(float(value), DECIMALS)


@dataclass
class _Result:
    metrics: dict[str, MetricValue] = field(default_factory=dict)

    def add(self, key: str, value: float, unit: str, source: str) -> None:
        self.metrics[key] = MetricValue(key=key, value=_round(value), unit=unit, source=source)


def _numeric(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """The named columns as numbers, rows with anything missing dropped.

    Raises:
        ModellingError: a column is not there. Guessing which was meant is how a
            model ends up fitted on something nobody asked about.
    """
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise ModellingError(f"khong co cot {missing} trong bang.")
    table = pd.DataFrame({name: pd.to_numeric(frame[name], errors="coerce") for name in columns})
    return table.dropna()


def _slug(text: str) -> str:
    """Make a column name safe to put inside a metric key."""
    return "".join(char if char.isalnum() or char in "_-" else "_" for char in str(text))[:40]


@dataclass(frozen=True)
class Importance:
    """How much of an outcome one variable carries."""

    rank: int
    feature: str
    share_pct: float


@dataclass(frozen=True)
class ImportanceOutcome:
    """What a model found mattered, or why it would not say."""

    outcome: str
    metrics: dict[str, MetricValue] = field(default_factory=dict)
    ranking: tuple[Importance, ...] = ()
    refused: tuple[str, ...] = ()

    def as_context(self) -> list[dict[str, Any]]:
        """The names behind the keys, for a prompt. No figures travel."""
        return [
            {
                "kind": "importance",
                "rank": item.rank,
                "feature": item.feature,
                "share_key": f"{_slug(self.outcome)}.importance.{_slug(item.feature)}",
            }
            for item in self.ranking
        ]


def measure_importance(
    frame: pd.DataFrame, outcome: str, features: Sequence[str]
) -> ImportanceOutcome:
    """Which variables carry an outcome, and how much of it each carries.

    Fitted on part of the data and scored on the part it never saw, because a
    model asked how well it fits what it memorised will always say "perfectly".

    Refit under several seeds and refused when the order moves. A tree's
    importances shift with the random draw, and a ranking that changes with the
    seed is a ranking of nothing - while reading exactly like a finding.

    Args:
        frame: the table. It is never modified.
        outcome: the column being accounted for.
        features: the columns that might account for it.

    Returns:
        The ranking and the metrics behind it, or the reasons there is neither.

    Raises:
        ModellingError: a named column is not in the table.
    """
    wanted = [name for name in features if name != outcome]
    if not wanted:
        raise ModellingError("can it nhat mot bien giai thich khac cot ket qua.")

    table = _numeric(frame, [outcome, *wanted])
    rows = len(table.index)
    refused: list[str] = []

    if rows < max(MIN_ROWS, MIN_PER_FEATURE * len(wanted)):
        return ImportanceOutcome(
            outcome=outcome,
            refused=(
                f"chi co {rows} dong dung duoc cho {len(wanted)} bien - can it nhat "
                f"{max(MIN_ROWS, MIN_PER_FEATURE * len(wanted))}. Duoi muc do mo hinh "
                "khop voi chinh cac dong nay chu khong voi thu sinh ra chung.",
            ),
        )

    target = table[outcome].to_numpy()
    matrix = table[wanted].to_numpy()
    if float(np.std(target)) == 0.0:
        return ImportanceOutcome(
            outcome=outcome,
            refused=(f"cot {outcome!r} khong doi gia tri - khong co gi de giai thich.",),
        )

    rankings: list[list[str]] = []
    scores: list[float] = []
    shares: list[np.ndarray[Any, Any]] = []
    for seed in SEEDS:
        train_x, test_x, train_y, test_y = train_test_split(
            matrix, target, test_size=HOLDOUT_SHARE, random_state=seed
        )
        forest = RandomForestRegressor(n_estimators=200, random_state=seed, n_jobs=1)
        forest.fit(train_x, train_y)
        scores.append(float(r2_score(test_y, forest.predict(test_x))))
        weights = np.asarray(forest.feature_importances_, dtype=float)
        shares.append(weights)
        rankings.append([wanted[index] for index in np.argsort(-weights)])

    mean_score = float(np.mean(scores))
    if mean_score < MIN_HOLDOUT_R2:
        return ImportanceOutcome(
            outcome=outcome,
            refused=(
                f"mo hinh chi giai thich {mean_score:.0%} bien thien tren phan du lieu "
                f"KHONG duoc hoc (duoi nguong {MIN_HOLDOUT_R2:.0%}). Xep hang tam quan "
                "trong tu mot mo hinh khong khop la xep hang cua nhieu.",
            ),
        )

    # The order has to survive the seed changing. It usually does not.
    top = {tuple(order[: min(3, len(wanted))]) for order in rankings}
    if len(top) > 1:
        return ImportanceOutcome(
            outcome=outcome,
            refused=(
                f"thu tu tam quan trong DOI khi doi hat giong ngau nhien "
                f"({len(top)} thu tu khac nhau tren {len(SEEDS)} lan chay). Mot xep hang "
                "thay doi theo hat giong la xep hang cua khong gi ca - nhung no doc y "
                "het mot phat hien.",
            ),
        )

    average = np.mean(np.vstack(shares), axis=0)
    out = _Result()
    out.add(f"{_slug(outcome)}.model.r2_holdout", mean_score, "", "importance")
    out.add(f"{_slug(outcome)}.model.rows", rows, "dòng", "importance")

    order = np.argsort(-average)
    ranking = [
        Importance(
            rank=rank,
            feature=wanted[index],
            share_pct=_round(100.0 * float(average[index])),
        )
        for rank, index in enumerate(order[:TOP_FEATURES], start=1)
    ]
    for item in ranking:
        out.add(
            f"{_slug(outcome)}.importance.{_slug(item.feature)}",
            item.share_pct,
            "%",
            "importance",
        )

    refused.append(
        "tam quan trong do MOI LIEN HE, khong do tac dong. No khong noi rang thay doi "
        "bien nay se lam ket qua thay doi - chi noi rang biet bien nay giup doan ket "
        "qua tot hon."
    )
    return ImportanceOutcome(
        outcome=outcome, metrics=out.metrics, ranking=tuple(ranking), refused=tuple(refused)
    )


@dataclass(frozen=True)
class Cluster:
    """One group of rows that resemble each other."""

    label: int
    size: int
    share_pct: float
    # What sets this group apart, as the columns whose average differs most from
    # the table as a whole.
    distinguishing: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClusterOutcome:
    """Groups found in the data, or why there were none worth reporting."""

    metrics: dict[str, MetricValue] = field(default_factory=dict)
    clusters: tuple[Cluster, ...] = ()
    quality: float = 0.0
    labels: tuple[int, ...] = ()
    refused: tuple[str, ...] = ()

    def as_context(self) -> list[dict[str, Any]]:
        """The names behind the keys, for a prompt. No figures travel."""
        return [
            {
                "kind": "cluster",
                "label": cluster.label,
                "khac_biet_o": list(cluster.distinguishing),
                "share_key": f"cluster.{cluster.label}.share_pct",
                "size_key": f"cluster.{cluster.label}.size",
            }
            for cluster in self.clusters
        ]


def _best_split(
    points: np.ndarray[Any, Any],
) -> tuple[tuple[float, int, np.ndarray[Any, Any]] | None, list[tuple[int, float]]]:
    """The number of groups that separates these points best, and what else was tried."""
    best: tuple[float, int, np.ndarray[Any, Any]] | None = None
    tried: list[tuple[int, float]] = []
    for count in CLUSTER_RANGE:
        if count >= len(points):
            continue
        labels = KMeans(n_clusters=count, random_state=0, n_init=10).fit_predict(points)
        if len(set(labels)) < count:
            continue
        score = float(silhouette_score(points, labels))
        tried.append((count, _round(score)))
        if best is None or score > best[0]:
            best = (score, count, labels)
    return best, tried


def _reference_like(points: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Structureless data with the same shape and spread as the real thing.

    Uniform across each column's own range: the same number of rows, the same
    number of columns, the same extent, and nothing inside it. Whatever
    separation k-means squeezes out of this is separation that means nothing, and
    the real data has to do better than it.

    The seed is fixed, so the comparison a run makes is the comparison it makes
    again.
    """
    generator = np.random.default_rng(0)
    lows = points.min(axis=0)
    highs = points.max(axis=0)
    return np.asarray(generator.uniform(lows, highs, size=points.shape), dtype=float)


def find_clusters(frame: pd.DataFrame, columns: Sequence[str]) -> ClusterOutcome:
    """Groups of rows that resemble each other, when there are any.

    A cluster label describes the row it is attached to, which is why this
    belongs in a system that insists every claim points at data: it says nothing
    about rows nobody has seen.

    The number of groups is chosen by measuring how separated they are, not
    picked in advance - and the whole thing is refused when the best available
    separation is poor. Any number of clusters can be imposed on any cloud of
    points; the question is whether the divisions were there already.

    Columns are standardised first. Without it the column with the largest
    numbers decides the grouping, and "largest numbers" is a property of the
    units somebody chose rather than of the data.

    Raises:
        ModellingError: a named column is not in the table.
    """
    table = _numeric(frame, columns)
    rows = len(table.index)
    if rows < MIN_ROWS:
        return ClusterOutcome(
            refused=(
                f"chi co {rows} dong - duoi {MIN_ROWS} thi mot 'nhom' chi la vai diem "
                "gan nhau do ngau nhien.",
            ),
        )
    if len(table.columns) < 2:
        return ClusterOutcome(refused=("can it nhat hai cot so de nhom theo.",))

    scaled = StandardScaler().fit_transform(table.to_numpy())
    best, tried = _best_split(scaled)
    if best is None:
        return ClusterOutcome(refused=("khong chia duoc thanh nhom nao.",))

    quality, count, labels = best
    attempts = ", ".join(f"{number} nhom: {score:.2f}" for number, score in tried)

    # The comparison that decides it: structureless data of the same shape, split
    # the same way. Anything can be divided; the question is whether these
    # divisions were there already.
    reference, _ = _best_split(_reference_like(scaled))
    baseline = reference[0] if reference is not None else 0.0
    gap = quality - baseline

    # Two different refusals, and they used to share one sentence. A split that
    # was clear enough on its own but no clearer than structureless data was
    # reported as failing the floor, and one that failed the floor was reported
    # as failing the comparison - so a reader trying to fix it went after the
    # wrong number.
    if quality < MIN_SILHOUETTE:
        why = (
            f"do tach biet tot nhat chi dat {quality:.2f}, duoi san {MIN_SILHOUETTE}. "
            f"Cach chia nao cung mo, khong co ranh gioi nao ro ca"
        )
    elif gap < MIN_GAP:
        why = (
            f"do tach biet dat {quality:.2f}, nhung du lieu KHONG CO cau truc cung hinh "
            f"dang dat {baseline:.2f} - chi hon {gap:.2f}, duoi muc {MIN_GAP}. Chia the "
            f"nao cung ra con so, va con so do khong noi len gi hon mot dam ngau nhien"
        )
    else:
        why = ""
    if why:
        return ClusterOutcome(
            quality=_round(quality),
            refused=(f"{why}. Du lieu nay la MOT dam, khong phai nhieu nhom. Da thu: {attempts}.",),
        )

    out = _Result()
    out.add("cluster.count", count, "nhóm", "cluster")
    out.add("cluster.quality.silhouette", quality, "", "cluster")
    out.add("cluster.rows", rows, "dòng", "cluster")

    overall = table.mean()
    spread = table.std().replace(0.0, np.nan)
    found: list[Cluster] = []
    for label in sorted({int(value) for value in labels}):
        members = table[labels == label]
        out.add(f"cluster.{label}.size", len(members.index), "dòng", "cluster")
        out.add(f"cluster.{label}.share_pct", 100.0 * len(members.index) / rows, "%", "cluster")
        # What sets this group apart: the columns whose average sits furthest
        # from the table's, measured in standard deviations so columns in
        # different units can be compared at all.
        distance = ((members.mean() - overall) / spread).abs().dropna()
        apart = tuple(str(name) for name in distance.sort_values(ascending=False).index[:3])
        for name in apart:
            out.add(
                f"cluster.{label}.mean.{_slug(name)}",
                float(members[name].mean()),
                "",
                "cluster",
            )
        found.append(
            Cluster(
                label=label,
                size=len(members.index),
                share_pct=_round(100.0 * len(members.index) / rows),
                distinguishing=apart,
            )
        )

    refused = [f"da thu cac cach chia: {attempts}."]
    small = [cluster.label for cluster in found if cluster.size < MIN_CLUSTER_ROWS]
    if small:
        refused.append(
            f"nhom {small} co duoi {MIN_CLUSTER_ROWS} dong - dung mo ta chung nhu mot "
            "phan khuc, do co the chi la vai dong le."
        )

    return ClusterOutcome(
        metrics=out.metrics,
        clusters=tuple(found),
        quality=_round(quality),
        labels=tuple(int(value) for value in labels),
        refused=tuple(refused),
    )
