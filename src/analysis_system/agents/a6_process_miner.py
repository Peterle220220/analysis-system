"""A6 Process Miner: measure how the work actually ran, then let the model name it.

The division is A2's, applied to sequences instead of columns. Code does every
measurement - variants, waiting times, rework, conformance - and the model is
asked for one thing code cannot supply: what to *call* what was measured. A path
taken by four cases in five is "the standard route"; a path that revisits the
same approval three times is "the rework loop". Those are judgements a reader
wants and arithmetic cannot make.

It writes no findings and draws no conclusions. That is A7's work, and A7 already
has the machinery for it - placeholders, evidence refs, the causal guard. A6
hands A7 a metric set; duplicating the rest here would mean two places where a
conclusion can go wrong, which is one more than necessary.

A label carrying a digit the model typed is dropped rather than repaired. The
activity names in the log are stripped out first, because a process really can
have a step called "SRM: 5 Awaiting Approval" and banning those digits would
stop the model naming the step at all - the same mistake that once made a whole
analysis avoid the dimension it was asked about.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, ClassVar, Final

import pandas as pd

from analysis_system.agents.base import BaseAgent, ManifestDir, first_of
from analysis_system.agents.feedback import as_prompt_fields, feedback_from
from analysis_system.contracts.agents import (
    ProcessAttribute,
    ProcessGap,
    ProcessGapStep,
    ProcessHandover,
    ProcessInterpretation,
    ProcessMap,
    ProcessVariant,
)
from analysis_system.contracts.base import (
    ErrorDetail,
    RetryFeedback,
    TaskRequest,
    TaskResult,
)
from analysis_system.services.digging import case_attributes, compare_cohorts
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.process_mining import (
    EventLogSpec,
    MiningOutcome,
    ProcessMiningError,
    mine_process,
    transition_key,
)
from analysis_system.services.prompts import load_prompt
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.settings import Settings

ARTIFACT_PREFIX: Final[str] = "artifacts://"
EVENT_LOG_PARAM: Final[str] = "event_log"
# Which activities a person chose to look at. Written by the selection
# mechanism; absent means the whole log, which is the state before anyone
# has chosen.
KEEP_ACTIVITIES_PARAM: Final[str] = "keep_activities"
# Which two groups of cases to set against each other, and on what.
COMPARE_PARAM: Final[str] = "compare"
MAP_SUFFIX: Final[str] = "_process_map.json"
# A label is a name, not a paragraph. Longer than this and the model is writing
# a conclusion, which is not its job here.
MAX_LABEL_CHARS: Final[int] = 80
# A note is a sentence about what was measured, so it needs room a name does not.
# Holding observations to the label limit threw away three of every four the
# model wrote on a real log - a field for five notes that delivered one.
MAX_NOTE_CHARS: Final[int] = 240

PLAN_PROBLEM_CODES: Final[frozenset[str]] = frozenset({"NO_INPUT", "BAD_EVENT_LOG"})


def strip_names(text: str, vocabulary: Iterable[str]) -> str:
    """Remove the log's own activity names before looking for invented numbers.

    Longest first, so "Step 10" is removed before the "1" inside it could be.
    """
    for name in sorted(vocabulary, key=len, reverse=True):
        if name and any(character.isdigit() for character in name):
            text = text.replace(name, " ")
    return text


def check_labels(
    labels: Mapping[str, str],
    vocabulary: Iterable[str],
    *,
    limit: int = MAX_LABEL_CHARS,
) -> tuple[dict[str, str], list[str]]:
    """Keep the text that describes something; drop what states a figure.

    Dropped rather than corrected, exactly as a finding is: repairing it would
    mean deciding what the model meant to say.

    Args:
        labels: what the model sent back, keyed however it keyed them.
        vocabulary: the log's own activity names, stripped out before the digit
            check so a step really called "SRM: 5 Awaiting" can be named.
        limit: how long the text may be. A name is short or it is not a name; a
            note about what was measured is a sentence and needs more room.

    Returns:
        What survived, and one sentence per entry that did not.
    """
    kept: dict[str, str] = {}
    rejected: list[str] = []
    names = list(vocabulary)
    for key, raw in sorted(labels.items()):
        label = str(raw).strip()
        if not label:
            continue
        if len(label) > limit:
            rejected.append(
                f"{key}: dai qua {limit} ky tu - day la mot ket luan, khong phai mo ta."
            )
            continue
        if any(character.isdigit() for character in strip_names(label, names)):
            rejected.append(f"{key}: nhan co chu so model tu go ({label!r}) - bi loai bo.")
            continue
        kept[key] = label
    return kept, rejected


def build_naming_request(
    outcome: MiningOutcome,
    question: str,
    feedback: RetryFeedback | None = None,
) -> LlmRequest:
    """Ask what to call each path, given the paths and no numbers at all.

    The payload carries activity names and rankings. It carries no figure: a
    number in front of the model is a number it can copy into a label.
    """
    payload: dict[str, Any] = {
        "question": question,
        "paths": outcome.as_context(),
        "declined": list(outcome.refused),
        **as_prompt_fields(feedback),
        "rules": [
            "TUYET DOI khong go bat ky con so nao. Nhan co chu so se bi loai bo.",
            "Nhan la mot TEN ngan, khong phai mot ket luan hay mot cau.",
            "Chi dat ten cho path co trong danh sach 'paths'.",
            "Khong suy dien nguyen nhan. Ban chi dang dat ten cho cai da do duoc.",
        ],
    }
    return LlmRequest(
        purpose="a6_miner_interpret",
        system=load_prompt("a6_miner_interpret"),
        prompt=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        schema=ProcessInterpretation,
    )


class ProcessMinerAgent(BaseAgent):
    """Turns an event log into a map of how the process actually ran."""

    agent_id: ClassVar[str] = "a6_process_miner"

    def __init__(
        self,
        settings: Settings,
        manifest_dir: ManifestDir = None,
        *,
        llm: LlmClient | None = None,
    ) -> None:
        """Bind an optional model client on top of the usual agent setup."""
        super().__init__(settings, manifest_dir)
        self._llm = llm

    def execute(self, request: TaskRequest, files: ScopedStorage) -> TaskResult:
        """Mine the log, ask for names, and write the map."""
        if not request.input_refs:
            return self._failed(request, "NO_INPUT", "A6 can mot bang event log de khai thac.")

        source = first_of(request.input_refs, "parquet")
        if source is None:
            return self._failed(request, "NO_INPUT", "A6 can mot bang event log de khai thac.")
        try:
            spec = EventLogSpec.from_params(request.scope.params.get(EVENT_LOG_PARAM))
        except ProcessMiningError as error:
            return self._failed(request, "BAD_EVENT_LOG", str(error))

        frame = files.load_parquet(source.path)
        frame, filtered = self._keep_chosen(frame, spec, request.scope.params)
        if frame.empty:
            return self._failed(
                request,
                "EMPTY_AFTER_FILTER",
                "Khong con su kien nao sau khi loc theo cac hoat dong da chon.",
            )
        try:
            outcome = mine_process(frame, spec)
        except ProcessMiningError as error:
            # Naming a column that is not there is a wiring mistake, and a
            # different plan is exactly what could fix it.
            return self._failed(request, "BAD_EVENT_LOG", str(error))

        activities = self._activity_names(frame, spec)
        labels, meanings, concerns, rejected = self._naming(outcome, request, activities)

        # What this log could be compared by, reported whether or not a
        # comparison was asked for. The next question is usually "and which part
        # of it is slow", and nobody can ask that without knowing the parts.
        attributes = case_attributes(frame, spec)
        gap, gap_metrics, gap_refused = self._compare(frame, spec, request.scope.params)

        result = ProcessMap(
            source=source.path,
            metrics=tuple(
                {**outcome.metrics, **gap_metrics}[key]
                for key in sorted({**outcome.metrics, **gap_metrics})
            ),
            variants=tuple(
                ProcessVariant(
                    rank=variant.rank,
                    path=variant.preview(),
                    steps=len(variant.trace),
                    cases_key=f"process.variant.{variant.rank}.cases",
                    share_key=f"process.variant.{variant.rank}.share_pct",
                    label=labels.get(str(variant.rank), ""),
                )
                for variant in outcome.variants
            ),
            handovers=tuple(
                ProcessHandover(
                    rank=transition.rank,
                    source_activity=transition.source,
                    target_activity=transition.target,
                    total_hours_key=transition_key(transition, "total_hours"),
                    observations_key=transition_key(transition, "observations"),
                    median_hours_key=(
                        transition_key(transition, "median_hours")
                        if transition.median_hours is not None
                        else ""
                    ),
                )
                for transition in outcome.transitions
            ),
            activity_meanings=meanings,
            concerns=concerns,
            attributes=tuple(
                ProcessAttribute(
                    name=attribute.name, values=attribute.values, detail=attribute.detail
                )
                for attribute in attributes
            ),
            gap=gap,
            refused=(*filtered, *outcome.refused, *gap_refused, *rejected),
        )

        target = f"{ARTIFACT_PREFIX}{request.scope.run_id}{MAP_SUFFIX}"
        written = files.save_text(result.model_dump_json(indent=2), target)

        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            declined=result.refused,
            metrics={
                "variants": float(len(result.variants)),
                "handovers": float(len(result.handovers)),
                "metrics_computed": float(len(result.metrics)),
                "declined": float(len(result.refused)),
            },
            payload=result.model_dump(mode="json"),
        )

    def _keep_chosen(
        self, frame: pd.DataFrame, spec: EventLogSpec, params: dict[str, Any]
    ) -> tuple[pd.DataFrame, tuple[str, ...]]:
        """Keep only the activities a person chose, and record having done it.

        Not a harmless narrowing: every variant, waiting time and rework figure
        afterwards describes a process nobody ran, because two cases differing
        only in a filtered step become the same variant. The note travels with
        the results rather than in a footnote, so a reader cannot see the
        numbers without seeing what they are numbers about.
        """
        wanted = params.get(KEEP_ACTIVITIES_PARAM)
        if not wanted or spec.activity not in frame.columns:
            return frame, ()

        keep = {str(name) for name in wanted}
        kept = frame[frame[spec.activity].astype(str).isin(keep)]
        dropped_events = len(frame.index) - len(kept.index)
        if not dropped_events:
            return frame, ()

        lost_cases = 0
        if spec.case_id in frame.columns:
            lost_cases = frame[spec.case_id].nunique() - kept[spec.case_id].nunique()
        note = (
            f"CHI KHAI THAC {len(keep)} hoat dong da chon: {sorted(keep)}. "
            f"Da bo {dropped_events} su kien"
            + (f" va {lost_cases} case khong con su kien nao" if lost_cases else "")
            + ". Moi con so duoi day mo ta quy trinh DA LOC, khong phai quy trinh day du."
        )
        return kept, (note,)

    def _compare(
        self, frame: pd.DataFrame, spec: EventLogSpec, params: dict[str, Any]
    ) -> tuple[ProcessGap | None, dict[str, Any], tuple[str, ...]]:
        """Set two groups of cases against each other, when the task asked for it.

        Nothing happens unasked. Choosing which groups to compare is a question
        about what somebody wants to know, and picking one on their behalf would
        put an answer in front of them to a question they did not ask.
        """
        raw = params.get(COMPARE_PARAM)
        if not isinstance(raw, dict) or not raw.get("attribute") or not raw.get("focus"):
            return None, {}, ()
        try:
            found = compare_cohorts(
                frame,
                spec,
                str(raw["attribute"]),
                str(raw["focus"]),
                str(raw.get("against") or ""),
            )
        except ProcessMiningError as error:
            return None, {}, (f"khong so sanh duoc: {error}",)

        return (
            ProcessGap(
                attribute=found.attribute,
                focus=found.focus,
                other=found.other,
                focus_cases=found.focus_cases,
                other_cases=found.other_cases,
                total_key="process.gap.total_hours_per_case" if found.steps else "",
                steps=tuple(
                    ProcessGapStep(
                        rank=step.rank,
                        source_activity=step.source,
                        target_activity=step.target,
                        gap_key=f"process.gap.{step.key}.hours_per_case",
                        share_key=f"process.gap.{step.key}.share_pct",
                    )
                    for step in found.steps
                ),
            ),
            found.metrics,
            found.refused,
        )

    def _activity_names(self, frame: pd.DataFrame, spec: EventLogSpec) -> list[str]:
        """Every activity name in the log, for stripping before the digit check."""
        if spec.activity not in frame.columns:
            return []
        return [str(name) for name in frame[spec.activity].dropna().unique()]

    def _naming(
        self,
        outcome: MiningOutcome,
        request: TaskRequest,
        activities: list[str],
    ) -> tuple[dict[str, str], dict[str, str], tuple[str, ...], list[str]]:
        """Ask the model what to call things, and keep only what it may say.

        Without a model this returns nothing and the map is still complete: every
        measurement is already made. Names are the one part that is optional,
        which is what makes it safe to ask for them.
        """
        if self._llm is None or not outcome.variants:
            return {}, {}, (), []

        answer = self._llm.complete(
            build_naming_request(
                outcome,
                str(request.scope.params.get("question") or request.instruction),
                feedback_from(request.scope.params),
            )
        )
        if not isinstance(answer.data, ProcessInterpretation):
            return {}, {}, (), ["model khong tra ve dung ProcessInterpretation - bo qua phan ten."]

        ranks = {str(variant.rank) for variant in outcome.variants}
        labels, rejected = check_labels(answer.data.variant_labels, activities)
        unknown = sorted(set(labels) - ranks)
        for key in unknown:
            # A name for a path that was never measured has nothing behind it.
            rejected.append(f"{key}: dat ten cho path khong co trong ket qua do duoc.")
            labels.pop(key)

        # Meanings and concerns are sentences about the process, not names for
        # it, so they get the room a sentence needs. The digit rule is unchanged:
        # that is the part that stops a figure being invented.
        meanings, meaning_rejects = check_labels(
            answer.data.activity_meanings, activities, limit=MAX_NOTE_CHARS
        )
        concerns, concern_rejects = check_labels(
            {str(index): text for index, text in enumerate(answer.data.concerns)},
            activities,
            limit=MAX_NOTE_CHARS,
        )
        return (
            labels,
            meanings,
            tuple(concerns[key] for key in sorted(concerns, key=int)),
            [*rejected, *meaning_rejects, *concern_rejects],
        )

    def _failed(self, request: TaskRequest, code: str, message: str) -> TaskResult:
        """Report an honest failure, with nothing written."""
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=False,
                replannable=code in PLAN_PROBLEM_CODES,
            ),
        )
