"""Process mining: what the event log says actually happened.

An event log is three columns doing a job no single row can do - a case id, an
activity and a time - and the questions worth asking about it are about
*sequences*, not values. How many distinct paths does the work really take. Where
does it wait. What gets done twice.

Everything here is code. No model is consulted, for the same reason A5 never
consults one: these are measurements, and a measurement that varies with the
weather is not a measurement.

The output is **named metrics**, exactly like `metrics.py` and `statistics.py`.
That is the whole trick and it is worth stating plainly: because a bottleneck
arrives as `process.wait.X__to__Y.median_hours` rather than as prose, the
anti-fabrication machinery needs no changes at all. A model may cite the number;
it may not type one.

**The refusals carry as much weight as the measurements.** A "most common
variant" computed from four cases is arithmetic, not a finding. A median waiting
time from two observations is a coincidence with a decimal point. Every
measurement here states what it needs and declines by name when it does not have
it, and the declines travel back beside the results rather than being dropped -
a number nobody was told about and a number that was never computed look
identical from the outside.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import pandas as pd

from analysis_system.contracts.agents import MetricValue

# Below this, shares are not weak evidence - they are noise with a percent sign.
# Four cases make every variant either 25% or 50% of the process.
MIN_CASES: Final[int] = 5
# A median needs a sample. Three was the number here until a real log put three
# handovers observed three times each at the top of the bottleneck list, ahead of
# one that happens 791 times and costs sixty times more waiting in total.
#
# A *total* has no such requirement - a sum of five waits is exactly the delay
# those five cases suffered - so totals are reported at any count, and only the
# median is withheld.
MIN_MEDIAN_OBSERVATIONS: Final[int] = 10
# How much of the timestamp column has to parse before timings mean anything.
# Below this the ordering itself is guesswork, so nothing timed is reported.
MIN_PARSED_SHARE: Final[float] = 0.9
TOP_VARIANTS: Final[int] = 5
TOP_TRANSITIONS: Final[int] = 5
TOP_ACTIVITIES: Final[int] = 10
DECIMALS: Final[int] = 4
# Long traces are summarised rather than printed whole: a 60-step variant is
# unreadable, and truncating is honest as long as it says that it truncated.
TRACE_PREVIEW: Final[int] = 6

HOUR_SECONDS: Final[float] = 3600.0


class ProcessMiningError(ValueError):
    """The log was described in a way that cannot be mined.

    Distinct from a refusal: this means the columns named do not exist or the
    request is malformed, not that the data was too thin to measure.
    """


@dataclass(frozen=True)
class EventLogSpec:
    """Which columns play which role in the log.

    Declared rather than guessed. A2 proposes candidates and the plan confirms
    them - and the one time a role was assigned by pattern matching alone,
    "case" matched inside "case_company" and every variant number after it was
    quietly wrong.
    """

    case_id: str
    activity: str
    timestamp: str | None = None
    resource: str | None = None

    @classmethod
    def from_params(cls, raw: Any) -> EventLogSpec:
        """Read a spec out of scope params, refusing anything malformed.

        Raises:
            ProcessMiningError: the spec is not shaped like a spec.
        """
        if not isinstance(raw, dict):
            raise ProcessMiningError("tham so 'event_log' phai la mot object.")
        for required in ("case_id", "activity"):
            if not raw.get(required):
                raise ProcessMiningError(f"'event_log' thieu {required!r}.")
        return cls(
            case_id=str(raw["case_id"]),
            activity=str(raw["activity"]),
            timestamp=str(raw["timestamp"]) if raw.get("timestamp") else None,
            resource=str(raw["resource"]) if raw.get("resource") else None,
        )

    def columns(self) -> tuple[str, ...]:
        """Every column this spec refers to, in a fixed order."""
        named = (self.case_id, self.activity, self.timestamp, self.resource)
        return tuple(name for name in named if name)


@dataclass(frozen=True)
class Variant:
    """One distinct path through the process, and how much of the work took it."""

    rank: int
    trace: tuple[str, ...]
    cases: int
    share_pct: float

    def preview(self) -> str:
        """The path as a readable string, shortened when it is long."""
        head = " -> ".join(self.trace[:TRACE_PREVIEW])
        if len(self.trace) <= TRACE_PREVIEW:
            return head
        return f"{head} -> ... (+{len(self.trace) - TRACE_PREVIEW} buoc)"


@dataclass(frozen=True)
class Transition:
    """A handover between two activities, and how long the work waited there.

    Two measurements, because "where is the bottleneck" is two questions. The
    total is what the process loses here; the median is what one case waits.
    A handover that is slow because it happens constantly and one that is slow
    every single time are different problems, and the pair tells them apart.
    """

    rank: int
    source: str
    target: str
    observations: int
    total_hours: float
    # None when there were too few observations to claim a typical wait. Not
    # zero: zero is a measurement, and this is the absence of one.
    median_hours: float | None = None


@dataclass(frozen=True)
class MiningOutcome:
    """What mining found, what it would not claim, and the names behind the keys.

    `metrics` holds every number, keyed so a claim can cite it. `variants` and
    `transitions` carry the *names* those keys are about - an activity name is
    text, not a figure, and a model cannot say which path is the common one
    without being told what the path is.
    """

    metrics: dict[str, MetricValue] = field(default_factory=dict)
    refused: tuple[str, ...] = ()
    variants: tuple[Variant, ...] = ()
    transitions: tuple[Transition, ...] = ()

    def as_context(self) -> list[dict[str, Any]]:
        """The named findings, in the shape a prompt can carry.

        Numbers are deliberately absent: every one of them is in `metrics` under
        a key, and putting a figure here would hand the model a digit to copy.
        """
        rows: list[dict[str, Any]] = [
            {
                "kind": "variant",
                "rank": variant.rank,
                "path": variant.preview(),
                "steps": len(variant.trace),
                "share_key": f"process.variant.{variant.rank}.share_pct",
                "cases_key": f"process.variant.{variant.rank}.cases",
            }
            for variant in self.variants
        ]
        rows.extend(
            {
                "kind": "wait",
                "rank": transition.rank,
                "from": transition.source,
                "to": transition.target,
                "total_hours_key": transition_key(transition, "total_hours"),
                "observations_key": transition_key(transition, "observations"),
                **(
                    {"median_hours_key": transition_key(transition, "median_hours")}
                    if transition.median_hours is not None
                    else {}
                ),
            }
            for transition in self.transitions
        )
        return rows


def _slug(text: str) -> str:
    """Make a name safe to put inside a metric key.

    Same shape as `metrics._clean_key`, and for the same reason: a key is parsed
    on dots, so a name carrying one would split into segments that mean nothing.
    """
    return "".join(char if char.isalnum() or char in "_-" else "_" for char in str(text))[:40]


def slug_map(names: Sequence[str]) -> dict[str, str]:
    """A distinct key fragment for every activity name.

    Two names that flatten to the same slug - "Approve (A)" and "Approve [A]" -
    would otherwise share a metric key, and one of them would overwrite the
    other's number with nothing said. Sorted first, so the disambiguating suffix
    does not depend on what order the rows happened to arrive in.
    """
    mapping: dict[str, str] = {}
    used: dict[str, int] = {}
    for name in sorted(set(names)):
        base = _slug(name)
        seen = used.get(base, 0)
        used[base] = seen + 1
        mapping[name] = base if seen == 0 else f"{base}_{seen + 1}"
    return mapping


def transition_key(transition: Transition, suffix: str) -> str:
    """The metric key for one handover."""
    return f"process.wait.{_slug(transition.source)}__to__{_slug(transition.target)}.{suffix}"


def _round(value: float) -> float:
    """One rounding rule everywhere, so two runs agree to the last digit."""
    return round(float(value), DECIMALS)


@dataclass
class _Result:
    """Collects metrics with their units attached.

    The unit is not decoration. A waiting time rendered as a bare number is a
    number somebody will read as days, and the analyst prompt forbids the model
    from writing units itself - so if code does not attach one, nobody does.
    """

    metrics: dict[str, MetricValue] = field(default_factory=dict)

    def add(self, key: str, value: float, unit: str, source: str) -> None:
        self.metrics[key] = MetricValue(key=key, value=_round(value), unit=unit, source=source)


def order_events(frame: pd.DataFrame, spec: EventLogSpec) -> tuple[pd.DataFrame, list[str]]:
    """The log with usable rows only, sorted into the order things happened.

    Public because the validator needs the same answer. "Goods receipt before
    invoice" is a question about order, and if the referee decided order its own
    way the two halves of the system could disagree about what happened - which
    is the kind of disagreement nobody notices until a report is already out.

    Sorting is stable, and stable on purpose. When two events in a case share a
    timestamp - which happens constantly in real logs, because systems write to
    the second - their original order is kept rather than decided by whatever
    the sort felt like. Without that, two runs over the same data produce two
    different variant sets, and criterion S1 fails for a reason nobody would
    think to look for.
    """
    refused: list[str] = []
    usable = frame.dropna(subset=[spec.case_id, spec.activity])
    dropped = len(frame.index) - len(usable.index)
    if dropped:
        refused.append(
            f"bo {dropped} dong thieu case_id hoac activity - mot su kien khong biet "
            "thuoc case nao thi khong xep vao trinh tu nao duoc."
        )

    usable = usable.copy()
    usable[spec.case_id] = usable[spec.case_id].astype(str)
    usable[spec.activity] = usable[spec.activity].astype(str)

    if spec.timestamp and spec.timestamp in usable.columns and not usable.empty:
        parsed = pd.to_datetime(usable[spec.timestamp], errors="coerce", utc=True, format="mixed")
        share = float(parsed.notna().sum()) / float(len(parsed))
        if share >= MIN_PARSED_SHARE:
            usable = usable.assign(_ts=parsed)
            return usable.sort_values([spec.case_id, "_ts"], kind="mergesort"), refused
        refused.append(
            f"cot thoi gian {spec.timestamp!r} chi doc duoc {share:.0%} - duoi "
            f"{MIN_PARSED_SHARE:.0%} thi ban than thu tu da la phong doan, nen khong "
            "bao cao bat ky so lieu thoi gian nao."
        )

    return usable.sort_values([spec.case_id], kind="mergesort"), refused


def _variants(traces: Mapping[str, tuple[str, ...]]) -> list[Variant]:
    """Distinct paths, most travelled first.

    Ties are broken by the path itself rather than left to chance, so two runs
    rank two equally common variants the same way round.
    """
    counts: dict[tuple[str, ...], int] = {}
    for trace in traces.values():
        counts[trace] = counts.get(trace, 0) + 1
    total = len(traces)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [
        Variant(rank=rank, trace=trace, cases=count, share_pct=_round(100.0 * count / total))
        for rank, (trace, count) in enumerate(ordered[:TOP_VARIANTS], start=1)
    ]


def _rework(traces: Mapping[str, tuple[str, ...]]) -> tuple[dict[str, int], int, int]:
    """Activities done more than once in a case, and how often that happened.

    Two different things, kept apart because they mean different things to
    whoever has to fix the process: a *repeat* anywhere in the case is usually a
    loop back for correction, while an *immediate* repeat is usually the same
    step being retried or logged twice.
    """
    per_activity: dict[str, int] = {}
    repeated_cases = 0
    self_loop_cases = 0
    for trace in traces.values():
        seen: dict[str, int] = {}
        for activity in trace:
            seen[activity] = seen.get(activity, 0) + 1
        repeats = {name for name, count in seen.items() if count > 1}
        if repeats:
            repeated_cases += 1
            for name in repeats:
                per_activity[name] = per_activity.get(name, 0) + 1
        if any(a == b for a, b in zip(trace, trace[1:], strict=False)):
            self_loop_cases += 1
    return per_activity, repeated_cases, self_loop_cases


def _transitions(ordered: pd.DataFrame, spec: EventLogSpec) -> list[Transition]:
    """Where the work waits, most total delay first.

    Ranked by total rather than by typical wait, because that is what somebody
    asking about bottlenecks is nearly always asking: where does this process
    lose its time. Ranking by median put three handovers seen three times each
    above one that happens 791 times and costs sixty times more.

    Median rather than mean for the typical wait: one case abandoned for eight
    months would otherwise name the bottleneck by itself, and the step it points
    at is usually not the one anybody can do something about.
    """
    if "_ts" not in ordered.columns:
        return []

    frame = ordered[[spec.case_id, spec.activity, "_ts"]].copy()
    grouped = frame.groupby(spec.case_id, sort=True)
    frame["_next_activity"] = grouped[spec.activity].shift(-1)
    frame["_next_ts"] = grouped["_ts"].shift(-1)
    steps = frame.dropna(subset=["_next_activity", "_next_ts"])
    if steps.empty:
        return []

    waits = (steps["_next_ts"] - steps["_ts"]).dt.total_seconds() / HOUR_SECONDS
    # A clock running backwards is a data problem, not a negative wait.
    steps = steps.assign(_wait_hours=waits)
    steps = steps[steps["_wait_hours"] >= 0]
    if steps.empty:
        return []

    summary = (
        steps.groupby([spec.activity, "_next_activity"], sort=True)["_wait_hours"]
        .agg(["sum", "median", "count"])
        .reset_index()
    )
    if summary.empty:
        return []

    summary = summary.sort_values(
        ["sum", spec.activity, "_next_activity"],
        ascending=[False, True, True],
        kind="mergesort",
    )
    return [
        Transition(
            rank=rank,
            source=str(row[spec.activity]),
            target=str(row["_next_activity"]),
            observations=int(row["count"]),
            total_hours=_round(float(row["sum"])),
            median_hours=(
                _round(float(row["median"]))
                if int(row["count"]) >= MIN_MEDIAN_OBSERVATIONS
                else None
            ),
        )
        for rank, (_, row) in enumerate(summary.head(TOP_TRANSITIONS).iterrows(), start=1)
    ]


def _durations(ordered: pd.DataFrame, spec: EventLogSpec, out: _Result) -> bool:
    """How long a case takes from its first event to its last.

    The median leads because case durations are almost always skewed: a handful
    of cases that were never closed drag the mean somewhere no real case sits.
    """
    if "_ts" not in ordered.columns:
        return False
    spans = ordered.groupby(spec.case_id, sort=True)["_ts"].agg(["min", "max"])
    hours = (spans["max"] - spans["min"]).dt.total_seconds() / HOUR_SECONDS
    hours = hours[hours >= 0]
    if hours.empty:
        return False
    for name, value in (
        ("median", float(hours.median())),
        ("mean", float(hours.mean())),
        ("p95", float(hours.quantile(0.95))),
        ("max", float(hours.max())),
    ):
        out.add(f"process.duration.{name}_hours", value, "gio", "duration")
    return True


def mine_process(frame: pd.DataFrame, spec: EventLogSpec) -> MiningOutcome:
    """Measure how the process in this log actually ran.

    Args:
        frame: the event log. It is never modified.
        spec: which column plays which role.

    Returns:
        The metrics, whatever had to be declined and why, and the activity names
        the metric keys refer to.

    Raises:
        ProcessMiningError: a column the spec names is not in the frame. That is
            a wiring mistake rather than thin data, and guessing which column was
            meant is how an analysis ends up measuring the wrong thing.
    """
    missing = [name for name in spec.columns() if name not in frame.columns]
    if missing:
        raise ProcessMiningError(f"khong co cot {missing} trong bang de khai thac quy trinh.")

    ordered, refused = order_events(frame, spec)
    if ordered.empty:
        return MiningOutcome(refused=(*refused, "khong con dong nao dung duoc sau khi loc."))

    traces: dict[str, tuple[str, ...]] = {
        str(case): tuple(str(value) for value in group)
        for case, group in ordered.groupby(spec.case_id, sort=True)[spec.activity]
    }
    out = _Result()
    out.add("process.cases", len(traces), "case", "volume")
    out.add("process.events", len(ordered.index), "su kien", "volume")
    out.add("process.events.per_case.mean", len(ordered.index) / len(traces), "su kien", "volume")
    out.add("process.activities.distinct", ordered[spec.activity].nunique(), "hoat dong", "volume")

    if len(traces) < MIN_CASES:
        # The counts above are honest at any size; shares are not. Reporting
        # that one case in three took a path is reporting 33%, and 33% is what
        # gets quoted onwards.
        return MiningOutcome(
            metrics=out.metrics,
            refused=(
                *refused,
                f"chi co {len(traces)} case, duoi nguong {MIN_CASES} - khong bao cao "
                "variant, rework hay diem nghen, vi ty le tren so nay la nhieu chu "
                "khong phai thong tin.",
            ),
        )

    variants = _variants(traces)
    out.add("process.variants", len(set(traces.values())), "variant", "variant")
    for variant in variants:
        out.add(f"process.variant.{variant.rank}.cases", variant.cases, "case", "variant")
        out.add(f"process.variant.{variant.rank}.share_pct", variant.share_pct, "%", "variant")
    covered = sum(variant.cases for variant in variants)
    out.add(
        f"process.variant_coverage.top{TOP_VARIANTS}_pct",
        100.0 * covered / len(traces),
        "%",
        "variant",
    )

    per_activity, repeated_cases, self_loop_cases = _rework(traces)
    out.add("process.rework.cases", repeated_cases, "case", "rework")
    out.add("process.rework.cases_pct", 100.0 * repeated_cases / len(traces), "%", "rework")
    out.add("process.selfloop.cases", self_loop_cases, "case", "rework")
    out.add("process.selfloop.cases_pct", 100.0 * self_loop_cases / len(traces), "%", "rework")

    slugs = slug_map([str(name) for name in ordered[spec.activity].unique()])
    counts = ordered[spec.activity].value_counts()
    for name in sorted(counts.index[:TOP_ACTIVITIES], key=str):
        key = f"process.activity.{slugs[str(name)]}.events"
        out.add(key, float(counts[name]), "su kien", "volume")
    for name, cases in sorted(per_activity.items())[:TOP_ACTIVITIES]:
        out.add(f"process.rework.{slugs[name]}.cases", cases, "case", "rework")
        out.add(
            f"process.rework.{slugs[name]}.cases_pct",
            100.0 * cases / len(traces),
            "%",
            "rework",
        )

    timed = _durations(ordered, spec, out)
    transitions = _transitions(ordered, spec)
    thin: list[str] = []
    for transition in transitions:
        out.add(
            transition_key(transition, "total_hours"),
            transition.total_hours,
            "gio",
            "bottleneck",
        )
        out.add(
            transition_key(transition, "observations"),
            transition.observations,
            "lan",
            "bottleneck",
        )
        if transition.median_hours is None:
            thin.append(f"{transition.source} -> {transition.target}")
            continue
        out.add(
            transition_key(transition, "median_hours"),
            transition.median_hours,
            "gio",
            "bottleneck",
        )

    if thin:
        refused.append(
            f"khong bao thoi gian cho DIEN HINH cho {len(thin)} buoc ban giao vi duoi "
            f"{MIN_MEDIAN_OBSERVATIONS} lan quan sat (tong thoi gian van duoc bao): "
            f"{thin[:3]}."
        )
    if not transitions and timed:
        refused.append("khong buoc ban giao nao do duoc - moi case chi co mot su kien.")
    if spec.timestamp is None:
        refused.append(
            "khong khai cot thoi gian - do duoc trinh tu nhung khong do duoc cho nao cho lau."
        )
    if spec.resource is None:
        refused.append("khong khai cot nguoi thuc hien - khong kiem duoc phan tach trach nhiem.")

    return MiningOutcome(
        metrics=out.metrics,
        refused=tuple(refused),
        variants=tuple(variants),
        transitions=tuple(transitions),
    )
