"""A4 Transformer: build the mart. The model writes SQL, code decides if it runs.

This is the first agent that executes something a model produced, so the
controls are heavier than anywhere else:

* the statement goes through the SQL guard before anything touches a database;
* it runs against an in-memory instance built for that one query, so there is
  nothing durable to damage;
* the result is refused if it is larger than the task allows, because an
  unconditioned join is how a mart goes from thousands of rows to billions;
* the model must declare, column by column, where each output came from, and
  code checks those source columns actually exist.

That last one is the lineage the spec asks for. Declared by the model, verified
by code: a lineage nobody checks is decoration, and a lineage derived by parsing
SQL would be a second parser to get wrong.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any, ClassVar, Final

import pandas as pd

from analysis_system.agents.base import BaseAgent, ManifestDir, all_of
from analysis_system.agents.feedback import RETRY_RULE, as_prompt_fields, feedback_from
from analysis_system.contracts.agents import SqlProposal, TransformResult
from analysis_system.contracts.base import (
    DataRef,
    ErrorDetail,
    RetryFeedback,
    TaskRequest,
    TaskResult,
)
from analysis_system.services.hashing import canonical_hash
from analysis_system.services.llm import LlmClient, LlmRequest
from analysis_system.services.narrowing import missed_the_filter
from analysis_system.services.prompts import load_prompt
from analysis_system.services.scoped_storage import ScopedStorage
from analysis_system.services.sql_guard import SqlGuardError
from analysis_system.services.sql_runner import (
    DEFAULT_MAX_ROWS,
    SqlRunError,
    describe_tables,
    run_query,
    table_name_for,
)
from analysis_system.settings import Settings

MART_PREFIX: Final[str] = "mart://"
SQL_PARAM: Final[str] = "sql"
TARGET_PARAM: Final[str] = "target"
QUESTION_PARAM: Final[str] = "question"


def load_tables(refs: Sequence[DataRef], files: ScopedStorage) -> dict[str, pd.DataFrame]:
    """Read the tabular inputs and name them for SQL.

    Only the tables. A plan may hand this agent a profile alongside the data it
    is meant to transform - that is a reasonable plan, the profile is context -
    and reading it as Parquet is how a whole run died on magic bytes.
    """
    return {
        table_name_for(ref.path): files.load_parquet(ref.path) for ref in all_of(refs, "parquet")
    }


# Below this a result is a summary rather than a table: nothing downstream can
# correlate, compare or plot it, and every one of those steps will decline
# without being able to say why.
MIN_USEFUL_ROWS: Final[int] = 5


def _collapsed(tables: dict[str, pd.DataFrame], result: pd.DataFrame) -> tuple[str, ...]:
    """Say so when the transform turned a table into a summary.

    Not forbidden - somebody may want exactly that - but everything after it
    degrades silently: no correlation has rows to run on, no group has members
    to compare, no scatter plot has points. A run that quietly produces nothing
    analysable should at least say where the data went.
    """
    largest = max((len(frame.index) for frame in tables.values()), default=0)
    rows = len(result.index)
    if rows >= MIN_USEFUL_ROWS or largest <= rows:
        return ()
    return (
        f"cau SQL da gop bang tu {largest} dong xuong {rows} dong. Moi phan tich theo "
        "dong o buoc sau (tuong quan, so sanh nhom, bieu do phan tan) se khong chay "
        "duoc tren ket qua nay.",
    )


def build_sql_request(
    tables: dict[str, pd.DataFrame],
    question: str,
    max_rows: int,
    instruction: str = "",
    feedback: RetryFeedback | None = None,
) -> LlmRequest:
    """Build the one question A4 asks.

    The model is shown table names, column names and types, the question to
    answer, and what the task actually asked for. It is not shown a single row:
    writing SQL against a shape needs the shape, not the data.

    The instruction used to be dropped here, which made a plan's request for
    particular output columns invisible to the model - and made its perfectly
    reasonable answer look like disobedience.
    """
    payload: dict[str, Any] = {
        "question": question,
        "instruction": instruction,
        "tables": describe_tables(tables),
        "max_output_rows": max_rows,
        "rules": [
            "Chi duoc dung SELECT hoac WITH - cau lenh phai TRA VE cac dong du lieu.",
            "Chi duoc doc cac bang liet ke o tren.",
            "Moi JOIN phai co dieu kien. CROSS JOIN bi cam.",
            "Chi duoc mot cau lenh. Khong dung dau cham phay de noi them lenh.",
            "Voi moi cot dau ra phai khai bao no sinh ra tu cot nao.",
            "Neu 'instruction' yeu cau ten cot cu the thi phai dat DUNG ten do.",
            *([RETRY_RULE] if feedback else []),
        ],
        **as_prompt_fields(feedback),
    }
    return LlmRequest(
        purpose="a4_transformer_sql",
        system=load_prompt("a4_transformer_sql"),
        prompt=json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        schema=SqlProposal,
    )


def verify_lineage(
    proposal: SqlProposal, tables: dict[str, pd.DataFrame], produced: pd.DataFrame
) -> list[str]:
    """Check the declared lineage against the tables and the result.

    Returns:
        Every problem found. An empty list means the declaration holds up.
    """
    problems: list[str] = []
    known: set[str] = set()
    for name, frame in tables.items():
        for column in frame.columns:
            known.add(f"{name}.{column}".lower())
            known.add(str(column).lower())

    produced_columns = {str(column).lower() for column in produced.columns}
    declared = {entry.output.lower() for entry in proposal.lineage}

    # Named once and reused: every complaint below is about a mismatch with
    # this list, and a complaint that does not show the list cannot be acted on.
    # The model wrote the query but never saw it run - these are the only column
    # names it has no way of knowing.
    actual = sorted(produced_columns)

    for entry in proposal.lineage:
        if entry.output.lower() not in produced_columns:
            problems.append(
                f"khai bao lineage cho cot {entry.output!r} nhung ket qua khong co cot do. "
                f"Cac cot THAT SU co trong ket qua: {actual}. "
                f"'output' phai la dung bi danh sau AS trong cau SELECT cua ban."
            )
        unknown = [source for source in entry.sources if source.lower() not in known]
        if unknown:
            problems.append(
                f"cot {entry.output!r} khai la sinh tu {unknown}, khong co trong bang dau vao"
            )

    missing = sorted(produced_columns - declared)
    if missing:
        problems.append(
            f"cot dau ra chua khai bao nguon goc: {missing}. "
            f"Ket qua co {len(actual)} cot: {actual} - lineage phai co du {len(actual)} muc."
        )
    return problems


# Statements that make an object instead of returning rows. Valid SQL, and
# useless to an agent whose whole output is the rows it hands back.
CREATES_SOMETHING: Final[re.Pattern[str]] = re.compile(
    r"^CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP(?:ORARY)?\s+)?(?:VIEW|TABLE)\b",
    re.IGNORECASE,
)

PLAN_PROBLEM_CODES: Final[frozenset[str]] = frozenset({"NO_INPUT"})

# Failures a better answer could repair, and only those. The model wrote a
# statement the guard refused, or one that would not run, or declared lineage
# for columns its own query aggregated away - each of those is fixed by being
# told about it, which is what a retry does. Being handed no table is not.
RETRYABLE_CODES: Final[frozenset[str]] = frozenset(
    # FILTER_MISSED: cau hoi doi thu hep ma SQL giu nguyen ca bang. Sua duoc
    # bang mot cau noi - "dung WHERE, dung them cot co" - nen no thu lai duoc.
    {"SQL_REFUSED", "SQL_FAILED", "LINEAGE_INVALID", "BAD_PROPOSAL", "FILTER_MISSED"}
)


class TransformerAgent(BaseAgent):
    """Turns clean tables into a mart table, under guard."""

    agent_id: ClassVar[str] = "a4_transformer"

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
        """Produce one mart table from the referenced clean tables."""
        if not request.input_refs:
            return self._failed(request, "NO_INPUT", "A4 can it nhat mot bang dau vao.")

        tables = load_tables(request.input_refs, files)
        if not tables:
            return self._failed(request, "NO_INPUT", "A4 can it nhat mot bang de bien doi.")
        max_rows = self._max_rows()

        proposal = self._proposal(request, tables, max_rows)
        if isinstance(proposal, TaskResult):
            return proposal

        # A statement that creates something returns an acknowledgement, not
        # rows: DuckDB answers a CREATE VIEW with a single column called
        # `Count` and no data. A4 exists to produce rows to write into a
        # mart table, so there is nothing here for it to write - and left
        # to run, the lineage check would compare perfectly good
        # declarations against that one column and blame the model for
        # column names that were right.
        if CREATES_SOMETHING.match(proposal.sql.lstrip()):
            return self._failed(
                request,
                "SQL_REFUSED",
                "Cau lenh tao view/bang thi khong tra ve dong nao de ghi ra bang mart. "
                "Hay viet mot cau SELECT (hoac WITH ... SELECT) tra ve dung cac cot can co.",
                # SQL_REFUSED is already in RETRYABLE_CODES, so the next
                # attempt happens and is told exactly what to write instead.
                proposal.model_dump(mode="json"),
            )

        try:
            outcome = run_query(proposal.sql, tables, max_rows=max_rows)
        except SqlGuardError as refused:
            return self._failed(
                request, "SQL_REFUSED", str(refused), proposal.model_dump(mode="json")
            )
        except SqlRunError as error:
            return self._failed(request, "SQL_FAILED", str(error), proposal.model_dump(mode="json"))

        problems = verify_lineage(proposal, tables, outcome.frame)
        if problems:
            return self._failed(
                request, "LINEAGE_INVALID", "; ".join(problems), proposal.model_dump(mode="json")
            )

        collapsed = _collapsed(tables, outcome.frame)

        target = str(request.scope.params.get(TARGET_PARAM) or "") or (
            f"{MART_PREFIX}{request.scope.run_id}_{request.scope.task_id}_{proposal.target_table}.parquet"
        )
        written = files.save_parquet(outcome.frame, target)

        # The statement that built the table, kept beside it. Without this
        # nobody can answer "how was this table built?" once the run is over -
        # and it was the absence of exactly this record that let a dropped
        # instruction go unnoticed through three runs.
        recipe = f"{target.rsplit('.', 1)[0]}.sql"
        files.save_text(
            "\n".join(
                (
                    f"-- run: {request.scope.run_id}   task: {request.scope.task_id}",
                    f"-- nguon: {', '.join(sorted(tables))}",
                    f"-- {outcome.rows_out} dong ra",
                    "",
                    outcome.sql,
                    "",
                )
            ),
            recipe,
            data_format="blob",
        )

        # Cau hoi doi thu hep ma bang khong hep lai thi moi con so sau do la cua
        # ca tep. Da xay ra: mot cau `CASE WHEN ... THEN TRUE` them cot co, 40
        # dong vao va 40 dong ra, va ket qua duoc trinh bay nhu cua nhom duoc
        # hoi. Bat o day de con thu lai duoc, thay vi de no di tiep.
        missed = missed_the_filter(
            request.instruction,
            outcome.sql,
            sum(outcome.rows_in.values()),
            outcome.rows_out,
        )
        if missed:
            # FILTER_MISSED nam trong RETRYABLE_CODES: lan sau model duoc bao
            # dung cho no lam sai, va do la loai sai sua duoc bang mot cau noi.
            return self._failed(request, "FILTER_MISSED", missed, {"sql": outcome.sql})

        result = TransformResult(
            target=target,
            sql=outcome.sql,
            rows_in=outcome.rows_in,
            rows_out=outcome.rows_out,
            lineage=tuple(proposal.lineage),
            content_hash=canonical_hash(outcome.frame),
            warnings=(outcome.note,) if outcome.note else (),
        )
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="OK",
            output_refs=(written,),
            declined=collapsed,
            metrics={
                "rows_out": float(outcome.rows_out),
                "rows_in_total": float(sum(outcome.rows_in.values())),
                "duration_s": outcome.duration_s,
            },
            payload=result.model_dump(mode="json"),
        )

    def _proposal(
        self, request: TaskRequest, tables: dict[str, pd.DataFrame], max_rows: int
    ) -> SqlProposal | TaskResult:
        """Take the SQL from the task, or ask the model for it."""
        supplied = request.scope.params.get(SQL_PARAM)
        if isinstance(supplied, dict):
            return SqlProposal.model_validate(supplied)
        if isinstance(supplied, str) and supplied.strip():
            return SqlProposal(sql=supplied, target_table="mart", lineage=[], reason="da duyet")

        if self._llm is None:
            return self._failed(
                request,
                "NO_SQL",
                f"Khong co tham so {SQL_PARAM!r} va cung khong co model de sinh SQL.",
            )
        question = str(request.scope.params.get(QUESTION_PARAM) or request.instruction)
        answer = self._llm.complete(
            build_sql_request(
                tables,
                question,
                max_rows,
                request.instruction,
                feedback_from(request.scope.params),
            )
        )
        if not isinstance(answer.data, SqlProposal):
            return self._failed(request, "BAD_PROPOSAL", "Model khong tra ve dung SqlProposal.")
        return answer.data

    def _max_rows(self) -> int:
        """Row ceiling from the manifest."""
        declared = self._manifest.limits.get("max_output_rows")
        return int(declared) if isinstance(declared, int | float) else DEFAULT_MAX_ROWS

    def _failed(
        self,
        request: TaskRequest,
        code: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> TaskResult:
        """Report an honest failure, with nothing written to the mart.

        The rejected answer travels in the payload so the next attempt can be
        shown what was wrong with it. Asking the identical question again and
        hoping for a different answer is not a strategy.
        """
        return TaskResult(
            task_id=request.scope.task_id,
            agent_id=self.agent_id,
            status="FAILED",
            payload=payload or {},
            error=ErrorDetail(
                code=code,
                message=message,
                retryable=code in RETRYABLE_CODES,
                # Being handed the wrong input is the one failure a different
                # plan could actually fix.
                replannable=code in PLAN_PROBLEM_CODES,
            ),
        )
