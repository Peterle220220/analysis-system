"""Command line entry point: python -m analysis_system.cli

Phase 0 exposes three commands: check the configuration, prepare the data
layers, and run the pipeline. Every error message is in Vietnamese, because the
person reading it is the operator, not the author.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer
from rich.console import Console
from rich.table import Table

from analysis_system.contracts.agents import Plan, ProcessMap, ProfileReport
from analysis_system.contracts.base import DataFormat, DataRef
from analysis_system.manager.dag_runner import DagRunner
from analysis_system.manager.gates import GateError, GateStore, decide, render_gate
from analysis_system.manager.planner import (
    PlanError,
    Planner,
    cleaning_plan,
    validate_plan,
    with_synthesis,
)
from analysis_system.manager.runner import GATE_RULES, Phase1Runner, RunOutcome
from analysis_system.manager.selection import affected_tasks, apply_selection
from analysis_system.manager.state import StateError, StateStore
from analysis_system.pipeline import run as pipeline
from analysis_system.services import storage
from analysis_system.services.bpmn import BpmnError, to_bpmn
from analysis_system.services.budget import (
    BudgetError,
    BudgetExceeded,
    BudgetTracker,
    load_budget,
    load_pricing,
)
from analysis_system.services.features import (
    FeatureCatalogue,
    FeatureError,
    Selection,
    catalogue_for,
    describe,
)
from analysis_system.services.hashing import canonical_hash
from analysis_system.services.llm import (
    AnthropicProvider,
    CassetteProvider,
    GeminiProvider,
    HandoffProvider,
    LlmClient,
)
from analysis_system.settings import (
    DEFAULT_CONFIG_PATH,
    ConfigError,
    Settings,
    cassette_path,
    load_settings,
    resolve,
    resource_root,
    verify_layers,
)

BPI_SOURCE_NAME = "BPI_Challenge_2019.xes"
BPI_DOWNLOAD_URL = "https://data.4tu.nl/articles/dataset/BPI_Challenge_2019/12715853"
FIXTURE_PATH = resource_root() / "tests" / "fixtures" / "bpi19_slice.csv"
SAMPLE_NAME = "sample.csv"
BUDGET_FILE = "budget.yaml"
PRICING_FILE = "pricing.yaml"

# Lets a test - or an operator with a second environment - point the CLI at a
# different settings file without editing the committed one.
CONFIG_ENV_VAR = "ANALYSIS_SYSTEM_CONFIG"

app = typer.Typer(add_completion=False, help="Pipeline xu ly du lieu nhieu agent")
console = Console()


def _load() -> Settings:
    """Load settings, turning a configuration error into a clean exit."""
    override = os.environ.get(CONFIG_ENV_VAR)
    try:
        settings = load_settings(Path(override) if override else None)
        verify_layers(settings)
    except ConfigError as error:
        console.print(f"[red]Loi cau hinh:[/red]\n{error}")
        raise typer.Exit(code=1) from error
    return settings


@app.command("check-config")
def check_config() -> None:
    """Kiem tra cau hinh va cac tang du lieu."""
    settings = _load()
    table = Table(title="Tang du lieu")
    table.add_column("Tang")
    table.add_column("Duong dan")
    for name in ("raw", "staging", "clean", "artifacts", "runs"):
        table.add_row(name, str(settings.layers.root_of(name)))
    console.print(table)
    console.print("[green]Cau hinh hop le.[/green]")


@app.command("setup")
def setup() -> None:
    """Chuan bi du lieu demo: copy fixture sang raw/sample.csv."""
    settings = _load()
    source = resolve(f"raw://{BPI_SOURCE_NAME}", settings)
    if not source.is_file():
        console.print(
            f"[red]Chua co file du lieu goc:[/red] {source}\n\n"
            f"Tai bo du lieu BPI Challenge 2019 tai:\n  {BPI_DOWNLOAD_URL}\n"
            f"roi dat file {BPI_SOURCE_NAME} vao thu muc tren.\n"
            "Chuong trinh khong tu tai va khong tu sinh du lieu thay the."
        )
        raise typer.Exit(code=1)
    if not FIXTURE_PATH.is_file():
        console.print(
            f"[red]Chua co fixture:[/red] {FIXTURE_PATH}\n"
            "Chay: python3 scripts/make_fixture.py --source <file .xes> "
            "--out tests/fixtures/bpi19_slice.csv"
        )
        raise typer.Exit(code=1)

    target = resolve(f"raw://{SAMPLE_NAME}", settings)
    shutil.copyfile(FIXTURE_PATH, target)
    console.print(f"[green]Da chuan bi[/green] {target}")


@app.command("run")
def run(
    input_path: Annotated[Path, typer.Option("--input", help="File CSV dau vao")],
    run_id: Annotated[str | None, typer.Option("--run-id", help="Dinh danh lan chay")] = None,
) -> None:
    """Chay pipeline: ingest -> clean -> validate -> report."""
    settings = _load()
    source = input_path.expanduser()
    if not source.is_file():
        console.print(f"[red]Khong tim thay file dau vao:[/red] {source}")
        raise typer.Exit(code=1)

    try:
        summary = pipeline.run_pipeline(source, settings, run_id=run_id)
    except (storage.StorageError, ConfigError) as error:
        console.print(f"[red]Pipeline dung lai:[/red]\n{error}")
        raise typer.Exit(code=1) from error

    table = Table(title=f"Ket qua - {summary.run_id}")
    table.add_column("Muc")
    table.add_column("Gia tri")
    table.add_row("So dong vao", str(summary.rows_in))
    table.add_row("So dong ra", str(summary.rows_out))
    table.add_row("Kiem dinh", "PASS" if summary.is_ok else "FAIL")
    table.add_row("hash staging", summary.staging_hash[:16])
    table.add_row("hash clean", summary.clean_hash[:16])
    table.add_row("Bao cao", str(summary.report_path))
    console.print(table)

    if not summary.is_ok:
        for failure in summary.validation.failures:
            console.print(f"[red]FAIL[/red] {failure.test}: {failure.detail}")
        raise typer.Exit(code=1)


def _run_dir(settings: Settings, run_id: str) -> Path:
    """Where one run keeps its state, audit log and gates."""
    return settings.layers.runs / run_id


def _config_dir() -> Path:
    """Where budget.yaml and pricing.yaml live.

    Beside the settings file in use, so pointing the CLI at a second environment
    moves its ceilings with it. Falls back to the committed copies.
    """
    override = os.environ.get(CONFIG_ENV_VAR)
    beside = Path(override).parent if override else DEFAULT_CONFIG_PATH.parent
    return beside if (beside / BUDGET_FILE).is_file() else DEFAULT_CONFIG_PATH.parent


def _build_budget(settings: Settings, now: datetime) -> BudgetTracker | None:
    """The ceiling this run must not cross.

    Built for every provider that calls an endpoint, not only the billed one:
    the token and wall-clock ceilings are worth having whatever the price, and a
    free tier that costs nothing can still run away with an afternoon.

    Returns:
        None for providers that reach no endpoint at all, where there is
        nothing to count.
    """
    if settings.llm.provider in ("none", "cassette", "handoff"):
        return None
    directory = _config_dir()
    try:
        config = load_budget(directory / BUDGET_FILE)
        prices = load_pricing(directory / PRICING_FILE)
    except BudgetError as error:
        console.print(f"[red]Khong doc duoc ngan sach:[/red]\n{error}")
        raise typer.Exit(code=1) from error

    if prices.is_stale(now.date()):
        console.print(
            f"[yellow]Canh bao:[/yellow] bang gia trong {PRICING_FILE} da qua han kiem chung "
            f"(last_verified: {prices.last_verified}). Bao cao chi phi co the sai."
        )
    return BudgetTracker(config, prices, started_at=now)


def _report_spend(budget: BudgetTracker | None) -> None:
    """Say what the run cost, whether or not it cost money."""
    if budget is None:
        return
    for warning in budget.warnings:
        console.print(f"[yellow]Ngan sach:[/yellow] {warning}")
    console.print(f"[dim]Da ghi nhan {budget.tokens_total:,} token · ${budget.cost_usd:.4f}[/dim]")


def _build_llm(
    settings: Settings, run_dir: Path, budget: BudgetTracker | None = None
) -> LlmClient | None:
    """Build the model client the configuration asks for.

    handoff  - writes the prompt out for a person to run on a subscription
    cassette - replays a recorded answer, free and repeatable
    gemini   - calls Gemini; the free tier costs nothing, but trains on what it
               is sent, so it belongs on the fixture and not on client data
    anthropic- calls the Anthropic API, and is billed for it
    none     - no model at all; agents fall back to code-only behaviour
    """
    choice = settings.llm.provider
    if choice == "handoff":
        return LlmClient(HandoffProvider(run_dir / "handoff"), budget=budget)
    if choice == "cassette":
        return LlmClient(CassetteProvider(cassette_path(settings)), budget=budget)
    if choice == "gemini":
        return LlmClient(
            GeminiProvider(settings.llm.gemini_model, thinking=settings.llm.gemini_thinking),
            budget=budget,
        )
    if choice == "anthropic":
        return LlmClient(AnthropicProvider(settings.llm.active_model), budget=budget)
    if choice == "none":
        return None
    console.print(
        f"[red]provider khong ho tro:[/red] {choice}\n"
        "Chon mot trong: handoff, cassette, gemini, anthropic, none"
    )
    raise typer.Exit(code=1)


def _phase1(settings: Settings, ref: DataRef, run_id: str) -> None:
    """Drive the Phase 1 loop and report where it stopped."""
    run_dir = _run_dir(settings, run_id)
    now = datetime.now(UTC)
    budget = _build_budget(settings, now)
    runner = Phase1Runner(
        settings, run_dir, llm=_build_llm(settings, run_dir, budget), budget=budget
    )
    try:
        outcome = runner.run(ref, run_id=run_id, now=now)
    except BudgetExceeded as exceeded:
        console.print(f"[red]DUNG - cham tran ngan sach:[/red] {exceeded}")
        _report_spend(budget)
        raise typer.Exit(code=1) from exceeded
    _report_spend(budget)

    if outcome.pending_handoff:
        console.print(
            "[yellow]Dung lai - can ban chuyen tiep cau hoi cho model[/yellow]\n"
            f"{outcome.pending_handoff}\n"
            f"Xong roi chay: asys resume {run_id}"
        )
        return

    if outcome.is_paused:
        console.print(
            f"[yellow]Da dung tai gate[/yellow] {outcome.paused_gate}\n"
            f"Xem   : asys gates {run_id}\n"
            f"Duyet : asys approve {run_id} --gate {outcome.paused_gate} --select <rule>\n"
            f"Tiep  : asys resume {run_id}"
        )
        return

    table = Table(title=f"Phase 1 - {run_id}")
    table.add_column("Task")
    table.add_column("Ket qua")
    for result in outcome.results:
        table.add_row(result.task_id, result.status)
    console.print(table)

    if outcome.is_complete:
        console.print("[green]Hoan tat.[/green]")
        return

    # A task that failed must say why here. Making the operator go and read the
    # state file to find out is not a report.
    console.print("[red]Dung giua chung.[/red]")
    for result in outcome.results:
        if result.error is not None:
            console.print(f"[red]{result.task_id} - {result.error.code}[/red]")
            console.print(f"  {result.error.message}")
    raise typer.Exit(code=1)


@app.command("run-agents")
def run_agents(
    input_path: Annotated[Path, typer.Option("--input", help="File CSV dau vao")],
    run_id: Annotated[str, typer.Option("--run-id", help="Dinh danh lan chay")] = "r_local",
) -> None:
    """Bat dau Phase 1: nap CSV -> A2 mo ta -> HUMAN GATE 1 -> A3 lam sach."""
    settings = _load()
    source = input_path.expanduser()
    if not source.is_file():
        console.print(f"[red]Khong tim thay file dau vao:[/red] {source}")
        raise typer.Exit(code=1)

    frame = storage.read_csv(source)
    # One staged file per run. Sharing a single name let a second run overwrite
    # the first, and resuming the earlier one would then read the wrong data.
    staged_uri = f"staging://{run_id}_events.parquet"
    storage.write_parquet(frame, resolve(staged_uri, settings))
    ref = DataRef(
        path=staged_uri,
        format="parquet",
        content_hash=canonical_hash(frame),
        row_count=len(frame.index),
    )
    console.print(
        f"[dim]Da nap {len(frame.index):,} dong x {len(frame.columns)} cot -> {staged_uri}[/dim]"
    )
    _phase1(settings, ref, run_id)


# --- Phase 2: run a whole plan ------------------------------------------------

PLAN_FILENAME = "plan.json"

# What A1 is told a file is. Anything it does not recognise is handed over as a
# blob rather than guessed at - A1 detects the real shape itself.
SOURCE_FORMATS: dict[str, DataFormat] = {
    "csv": "csv",
    "tsv": "csv",
    "txt": "csv",
    "parquet": "parquet",
    "json": "json",
    "jsonl": "json",
}


def _format_of(path: Path) -> DataFormat:
    """The declared format of a source file, from its extension."""
    return SOURCE_FORMATS.get(path.suffix.lstrip(".").lower(), "blob")


def _plan_path(settings: Settings, run_id: str) -> Path:
    """Where a run keeps the plan it is executing."""
    return _run_dir(settings, run_id) / PLAN_FILENAME


def _report_declined(outcome: RunOutcome) -> None:
    """Say what the run would not claim, beside what it did.

    A report that lists findings and swallows the refusals invites a conclusion
    drawn on top of a hole nobody mentioned. Grouped by the agent that refused,
    because "the miner had no clock" and "the analyst had too few rows" are
    different problems with different fixes.
    """
    refusals = [(result.agent_id, note) for result in outcome.results for note in result.declined]
    if not refusals:
        return
    console.print("\n[yellow]Khong ket luan duoc nhung phan sau:[/yellow]")
    for agent_id, note in refusals:
        console.print(f"  [dim]{agent_id}[/dim] {note}")


def _report_outcome(outcome: RunOutcome, run_id: str) -> None:
    """Say where the run stopped, and what the operator does next."""
    if outcome.pending_handoff:
        console.print(
            "[yellow]Dung lai - can ban chuyen tiep cau hoi cho model[/yellow]\n"
            f"{outcome.pending_handoff}\n"
            f"Xong roi chay: asys resume-dag {run_id}"
        )
        return

    if outcome.is_paused:
        console.print(
            f"[yellow]Da dung tai gate[/yellow] {outcome.paused_gate}\n"
            f"Xem   : asys gates {run_id}\n"
            f"Duyet : asys approve {run_id} --gate {outcome.paused_gate} --select <muc>\n"
            f"Tiep  : asys resume-dag {run_id}"
        )
        return

    table = Table(title=f"Phase 2 - {run_id}")
    table.add_column("Task")
    table.add_column("Agent")
    table.add_column("Ket qua")
    for result in outcome.results:
        table.add_row(result.task_id, result.agent_id, result.status)
    console.print(table)

    if outcome.is_complete:
        console.print("[green]Hoan tat.[/green]")
        return

    if outcome.halted is not None:
        console.print(
            f"[red]DUNG - du lieu khong dat kiem dinh:[/red] {outcome.halted}\n"
            "Khong agent nao phia sau duoc chay tren bang nay. "
            "Sua du lieu hoac sua tieu chi roi chay lai."
        )
        raise typer.Exit(code=1)

    console.print(f"[red]Dung giua chung:[/red] {outcome.escalation or 'khong ro ly do'}")
    for result in outcome.results:
        if result.error is not None:
            console.print(f"[red]{result.task_id} - {result.error.code}[/red]")
            console.print(f"  {result.error.message}")
    raise typer.Exit(code=1)


def _execute_plan(settings: Settings, plan: Plan, ref: DataRef, run_id: str, question: str) -> None:
    """Drive the Phase 2 loop and report where it stopped."""
    run_dir = _run_dir(settings, run_id)
    now = datetime.now(UTC)
    budget = _build_budget(settings, now)
    llm = _build_llm(settings, run_dir, budget)
    runner = DagRunner(
        settings,
        run_dir,
        llm=llm,
        budget=budget,
        planner=Planner(llm=llm) if llm is not None else None,
    )
    try:
        outcome = runner.run(plan, ref, run_id=run_id, question=question, now=now)
    except BudgetExceeded as exceeded:
        # Never continued past a ceiling automatically, and never quietly. The
        # reason comes first: the counter below shows what was recorded before
        # the refused call, which is zero when the first call is the one that
        # would have crossed.
        console.print(f"[red]DUNG - cham tran ngan sach:[/red] {exceeded}")
        _report_spend(budget)
        raise typer.Exit(code=1) from exceeded
    _report_spend(budget)
    _report_outcome(outcome, run_id)
    _report_declined(outcome)
    if outcome.is_complete:
        _report_clean_table(settings, run_id)


def _plan_table(plan: Plan) -> Table:
    """A plan as a person reads it: what runs, after what, reading what."""
    table = Table(title="Ke hoach")
    table.add_column("Task")
    table.add_column("Agent")
    table.add_column("Sau khi")
    table.add_column("Doc tu")
    for task in plan.tasks:
        table.add_row(
            task.task_id,
            task.agent_id,
            ", ".join(task.depends_on) or "-",
            ", ".join(task.reads_from) or "nguon",
        )
    return table


def _source_ref(settings: Settings, source: Path, run_id: str) -> DataRef:
    """Point the run at its input, copying it in only when it is not already there.

    The raw layer holds the one thing that cannot be regenerated, so nothing
    writes to it if it can avoid doing so - and under Docker it cannot write to
    it at all. A file already inside the layer is used where it lies.

    Raises:
        typer.Exit: the file is outside the layer and the layer cannot be
            written to, which is a situation only the operator can resolve.
    """
    raw_root = settings.layers.raw.resolve()
    resolved = source.resolve()
    if raw_root == resolved.parent or raw_root in resolved.parents:
        relative = resolved.relative_to(raw_root).as_posix()
        return DataRef(
            path=f"raw://{relative}",
            format=_format_of(source),
            content_hash=storage.sha256_file(resolved),
        )

    target_uri = f"raw://{run_id}_{source.name}"
    target = resolve(target_uri, settings)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    except OSError as error:
        console.print(
            f"[red]Khong chep duoc file nguon vao tang raw:[/red] {error}\n"
            f"Tang raw ({raw_root}) chi doc. Hay dat file vao do truoc, "
            "roi tro --input toi chinh no."
        )
        raise typer.Exit(code=1) from error
    return DataRef(
        path=target_uri, format=_format_of(source), content_hash=storage.sha256_file(target)
    )


@app.command("run-dag")
def run_dag(
    input_path: Annotated[Path, typer.Option("--input", help="File du lieu nguon")],
    plan_path: Annotated[Path, typer.Option("--plan", help="File ke hoach JSON")],
    run_id: Annotated[str, typer.Option("--run-id", help="Dinh danh lan chay")] = "r_dag",
    question: Annotated[str, typer.Option("--question", help="Cau hoi nghiep vu")] = "",
) -> None:
    """Chay mot ke hoach nhieu agent, tu file nguon toi bao cao, dung lai o moi gate."""
    settings = _load()
    source = input_path.expanduser()
    if not source.is_file():
        console.print(f"[red]Khong tim thay file dau vao:[/red] {source}")
        raise typer.Exit(code=1)

    try:
        plan = Plan.model_validate_json(plan_path.expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        console.print(f"[red]Khong doc duoc ke hoach:[/red] {plan_path}\n{error}")
        raise typer.Exit(code=1) from error

    # The same check the planner applies to a model's plan. A plan written by
    # hand gets no more trust than one written by a model.
    problems = validate_plan(plan, Planner().agents)
    if problems:
        console.print("[red]Ke hoach khong chay duoc:[/red]")
        for problem in problems:
            console.print(f"  - {problem}")
        raise typer.Exit(code=1)

    ref = _source_ref(settings, source, run_id)

    run_directory = _run_dir(settings, run_id)
    run_directory.mkdir(parents=True, exist_ok=True)
    storage.write_text(Plan.model_dump_json(plan, indent=2), _plan_path(settings, run_id))
    console.print(f"[dim]Ke hoach {len(plan.tasks)} task -> {ref.path}[/dim]")
    _execute_plan(settings, plan, ref, run_id, question)


@app.command("resume-dag")
def resume_dag(
    run_id: Annotated[str, typer.Argument(help="Dinh danh lan chay")],
    question: Annotated[str, typer.Option("--question", help="Cau hoi nghiep vu")] = "",
) -> None:
    """Chay tiep mot ke hoach dang dung. Khong nap lai du lieu, khong hoi lai gate da duyet."""
    settings = _load()
    plan_file = _plan_path(settings, run_id)
    try:
        stored = StateStore(_run_dir(settings, run_id) / "state.json").load()
        plan = Plan.model_validate_json(plan_file.read_text(encoding="utf-8"))
    except (StateError, OSError, ValueError) as error:
        console.print(
            f"[red]Chua co ke hoach hoac state cho {run_id!r}.[/red]\n"
            "Lan dau phai dung: asys run-dag --input <file> --plan <plan.json>"
        )
        raise typer.Exit(code=1) from error

    if stored.source is None:
        console.print("[red]State khong ghi nguon du lieu. Hay bat dau lai bang run-dag.[/red]")
        raise typer.Exit(code=1)

    _execute_plan(settings, plan, stored.source, run_id, question)


@app.command("plan")
def plan_command(
    question: Annotated[str, typer.Argument(help="Cau hoi nghiep vu")],
    source: Annotated[str, typer.Option("--source", help="URI nguon, vi du raw://x.csv")],
    out: Annotated[Path | None, typer.Option("--out", help="Ghi ke hoach ra file")] = None,
) -> None:
    """Sinh ke hoach cho mot cau hoi. Khong chay gi ca - chi de xuat."""
    settings = _load()
    llm = _build_llm(settings, _run_dir(settings, "plan"))
    try:
        proposed = Planner(llm=llm).plan(question, source)
    except PlanError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from error

    console.print(_plan_table(proposed))
    console.print(f"[dim]{proposed.reason}[/dim]")

    if out is not None:
        storage.write_text(Plan.model_dump_json(proposed, indent=2), out.expanduser())
        console.print(f"[green]Da ghi[/green] {out}")


@app.command("bpmn")
def bpmn_command(
    run_id: Annotated[str, typer.Argument(help="Lan chay da khai thac quy trinh")],
    out: Annotated[Path, typer.Option("--out", help="File .bpmn de ghi ra")],
) -> None:
    """Xuat quy trinh da do duoc ra BPMN 2.0, mo duoc trong Signavio.

    Chi cau truc, khong co toa do: Signavio va cac cong cu khac tu sap xep hinh
    khi import, va mot toa do dat tay se sai ngay khi co nguoi keo mot o.
    """
    settings = _load()
    found = _process_map(settings, run_id)
    if found is None:
        console.print(
            f"[red]Lan chay {run_id!r} chua co ban do quy trinh.[/red]\n"
            "Can mot lan chay co agent khai thac quy trinh (a6_process_miner)."
        )
        raise typer.Exit(code=1)

    try:
        xml = to_bpmn(found)
    except BpmnError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from error

    target = out.expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(xml, encoding="utf-8")
    except OSError as error:
        console.print(f"[red]Khong ghi duoc ra {target}:[/red] {error}")
        raise typer.Exit(code=1) from error

    console.print(f"[green]Da ghi[/green] {target}")
    console.print(f"[dim]{_bpmn_note(found)}[/dim]")


def _process_map(settings: Settings, run_id: str) -> ProcessMap | None:
    """The process map a run produced, if it produced one."""
    try:
        state = StateStore(_run_dir(settings, run_id) / "state.json").load()
    except StateError:
        return None
    for task in state.tasks.values():
        for ref in task.output_refs:
            if ref.format != "json" or not ref.path.endswith("_process_map.json"):
                continue
            try:
                return ProcessMap.model_validate_json(
                    resolve(ref.path, settings).read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                return None
    return None


def _bpmn_note(found: ProcessMap) -> str:
    """What the diagram leaves out, said at the terminal as well as in the file."""
    numbers = {metric.key: metric.value for metric in found.metrics}
    total = int(numbers.get("process.variants", len(found.variants)))
    coverage = numbers.get("process.variant_coverage.top5_pct")
    said = f"{len(found.variants)} duong di duoc ve, tren tong {total} duong da do duoc."
    if coverage is not None:
        said += f" Chung chiem {coverage:.1f}% so case."
    return said


@app.command("export")
def export(
    uri: Annotated[str, typer.Argument(help="URI tang, vi du clean://events.parquet")],
    out: Annotated[Path | None, typer.Option("--out", help="File CSV ghi ra")] = None,
    rows: Annotated[int, typer.Option("--rows", help="Chi xem N dong dau, 0 = tat ca")] = 0,
) -> None:
    """Xuat mot bang trong kho du lieu ra CSV, hoac xem nhanh vai dong dau."""
    settings = _load()
    try:
        path = resolve(uri, settings)
    except ConfigError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from error
    if not path.is_file():
        console.print(f"[red]Khong tim thay:[/red] {uri}\n  ({path})")
        raise typer.Exit(code=1)

    try:
        frame = _read_table(path)
    except (storage.StorageError, ValueError) as error:
        console.print(f"[red]Khong doc duoc {uri}:[/red]\n{error}")
        raise typer.Exit(code=1) from error

    if rows > 0:
        frame = frame.head(rows)

    if out is None:
        # No destination: this is a look, not an export.
        console.print(f"[dim]{uri} - {len(frame):,} dong x {len(frame.columns)} cot[/dim]")
        console.print(frame.to_string(max_rows=rows or 20, max_cols=12))
        return

    target = out.expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(target, index=False)
    except OSError as error:
        # A refused write is a normal outcome, not a crash: the raw layer is
        # mounted read-only on purpose, and pointing an export at it is an easy
        # mistake to make.
        console.print(
            f"[red]Khong ghi duoc ra {target}:[/red] {error}\n"
            "Neu day la tang raw thi no CHI DOC theo thiet ke - "
            "chon mot duong dan khac de xuat ra."
        )
        raise typer.Exit(code=1) from error
    console.print(
        f"[green]Da xuat[/green] {len(frame):,} dong x {len(frame.columns)} cot -> {target}"
    )


def _read_table(path: Path) -> pd.DataFrame:
    """Read whichever of the layer formats this file happens to be."""
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return storage.read_parquet(path)
    if suffix in (".json", ".jsonl"):
        return storage.read_json(path, lines=suffix == ".jsonl")
    if suffix in (".xlsx", ".xls"):
        return storage.read_excel(path)
    return storage.read_csv(path)


@app.command("clean")
def clean_command(
    source: Annotated[Path, typer.Option("--input", help="File du lieu dau vao")],
    run_id: Annotated[str, typer.Option("--run-id", help="Dat ten cho lan lam viec nay")] = "",
) -> None:
    """Lam sach du lieu roi DUNG LAI, de ban xem truoc khi dat cau hoi.

    Nap, mo ta, de xuat rule lam sach. Ban duyet rule, chay tiep, va nhan lai
    mot bang sach. Chua phan tich gi ca - phan tich la viec cua `asys ask`.
    """
    settings = _load()
    if not source.is_file():
        console.print(f"[red]Khong tim thay file:[/red] {source}")
        raise typer.Exit(code=1)

    name = run_id or f"d_{datetime.now(UTC):%Y%m%d_%H%M%S}"
    ref = _source_ref(settings, source, name)
    plan = cleaning_plan()
    _plan_path(settings, name).parent.mkdir(parents=True, exist_ok=True)
    _plan_path(settings, name).write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    console.print(f"[bold]Lam sach[/bold] {source.name} -> lan lam viec {name!r}")
    _execute_plan(settings, plan, ref, name, "")


def _report_clean_table(settings: Settings, run_id: str) -> None:
    """Say where the clean table is, and what to do next.

    The point of stopping after cleaning is that a person looks at the data, so
    this has to reach them however the run finished - and a cleaning run always
    finishes through `resume-dag`, because the approval gate interrupts it.

    Silent when the run went on to analyse: at that point the clean table is a
    step along the way, not the thing being handed over.
    """
    if _analysed(settings, run_id):
        return
    table = _clean_table(settings, run_id)
    if table is None:
        return
    frame = storage.read_parquet(resolve(table.path, settings))
    console.print(
        f"\n[green]Du lieu sach:[/green] {table.path}  "
        f"({len(frame.index)} dong, {len(frame.columns)} cot)"
    )
    console.print("Cot: " + ", ".join(str(column) for column in frame.columns))
    console.print(
        "\nXem ra file        : asys export " + table.path + " --out ~/sach.csv\n"
        "Xem chon duoc gi   : asys features " + run_id + "\n"
        "Dat cau hoi        : asys ask " + run_id + ' "cau hoi cua ban"'
    )


def _clean_table(settings: Settings, run_id: str) -> DataRef | None:
    """The clean table a cleaning run produced, if it got that far."""
    try:
        state = StateStore(_run_dir(settings, run_id) / "state.json").load()
    except StateError:
        return None
    for task in state.tasks.values():
        if task.agent_id == "a3_cleaner" and task.is_done and task.output_refs:
            return task.output_refs[0]
    return None


ANALYSIS_AGENTS = frozenset({"a4_transformer", "a6_process_miner", "a7_analyst", "a8_reporter"})


def _analysed(settings: Settings, run_id: str) -> bool:
    """True when this run went past cleaning into analysis."""
    try:
        state = StateStore(_run_dir(settings, run_id) / "state.json").load()
    except StateError:
        return False
    return any(task.agent_id in ANALYSIS_AGENTS for task in state.tasks.values())


def _clean_profile(settings: Settings, run_id: str) -> ProfileReport | None:
    """What A2 found, so the planner does not have to plan blind."""
    try:
        state = StateStore(_run_dir(settings, run_id) / "state.json").load()
    except StateError:
        return None
    for task in state.tasks.values():
        if task.agent_id == "a2_profiler" and task.is_done and task.output_refs:
            try:
                path = resolve(task.output_refs[0].path, settings)
                return ProfileReport.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
    return None


def _next_round(settings: Settings, run_id: str) -> str:
    """A fresh id for this question.

    Each question is its own run, with its own state and its own gates. Two
    questions about one table are two pieces of work, and sharing state would
    mean the second quietly inheriting the first's decisions.
    """
    runs = _run_dir(settings, run_id).parent
    used = {path.name for path in runs.glob(f"{run_id}__q*")} if runs.is_dir() else set()
    index = 1
    while f"{run_id}__q{index}" in used:
        index += 1
    return f"{run_id}__q{index}"


@app.command("ask")
def ask_command(
    run_id: Annotated[str, typer.Argument(help="Lan lam viec da lam sach")],
    question: Annotated[str, typer.Argument(help="Cau hoi nghiep vu")],
) -> None:
    """Dat mot cau hoi len du lieu da lam sach. Hoi lai bao nhieu lan cung duoc.

    Manager nhin ho so du lieu roi moi lap ke hoach, giao viec xuong cac agent,
    va tra ve nhung gi tim duoc. Khong lam sach lai gi ca.
    """
    settings = _load()
    table = _clean_table(settings, run_id)
    if table is None:
        console.print(
            f"[red]Lan lam viec {run_id!r} chua co du lieu sach.[/red]\n"
            "Chay truoc: asys clean --input <file> --run-id " + run_id
        )
        raise typer.Exit(code=1)

    now = datetime.now(UTC)
    budget = _build_budget(settings, now)
    llm = _build_llm(settings, _run_dir(settings, run_id), budget)
    if llm is None:
        console.print(
            "[red]Chua cau hinh model.[/red] Manager can mot model de lap ke hoach "
            "tu cau hoi. Xem llm.provider trong settings.yaml."
        )
        raise typer.Exit(code=1)

    round_id = _next_round(settings, run_id)
    try:
        plan = Planner(llm=llm).plan(question, table.path, _clean_profile(settings, run_id))
        # The Manager answers, always. Whether a question gets an answer is not
        # a planning decision.
        plan = with_synthesis(plan, question, _config_dir() / "manifests")
    except PlanError as error:
        console.print(f"[red]Khong lap duoc ke hoach:[/red] {error}")
        raise typer.Exit(code=1) from error

    _plan_path(settings, round_id).parent.mkdir(parents=True, exist_ok=True)
    _plan_path(settings, round_id).write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    console.print(f"[bold]Cau hoi:[/bold] {question}")
    console.print(f"[dim]{plan.reason}[/dim]")
    console.print(_plan_table(plan))
    _execute_plan(settings, plan, table, round_id, question)
    console.print(f'\n[dim]Lan hoi nay la {round_id}. Hoi tiep: asys ask {run_id} "..."[/dim]')


@app.command("features")
def features_command(
    run_id: Annotated[str, typer.Argument(help="Dinh danh lan chay")],
    kind: Annotated[
        str, typer.Option("--kind", help="Chi hien mot loai: column, activity...")
    ] = "",
) -> None:
    """Liet ke nhung gi co the chon de phan tich trong mot lan chay.

    Cot cua mot bang, hoat dong cua mot event log - deu la 'dac trung'. Dong
    danh dau [x] la dang duoc phan tich.
    """
    settings = _load()
    frame, source, spec = _log_frame(settings, run_id)
    catalogue = catalogue_for(
        frame,
        source,
        activity=spec.get("activity", ""),
        resource=spec.get("resource", ""),
    )
    if kind:
        catalogue = FeatureCatalogue(source=catalogue.source, features=catalogue.of_kind(kind))
    if not catalogue.features:
        console.print(f"[yellow]Khong co dac trung nao{' loai ' + kind if kind else ''}.[/yellow]")
        return

    chosen = _stored_selection(settings, run_id)
    console.print(f"[bold]{len(catalogue.features)} dac trung[/bold] tu {catalogue.source}")
    if chosen.is_empty:
        console.print("[dim]Chua chon gi - dang phan tich tat ca.[/dim]")
    for line in describe(catalogue, chosen):
        # markup off: rich reads [x] as a tag and swallows it, so every chosen
        # feature printed as though it were not chosen. A feature name carrying
        # square brackets would go the same way.
        console.print(line, markup=False)
    console.print(
        "\nChon bang: asys select " + run_id + " --feature column:ten_cot --feature column:ten_khac"
    )


@app.command("select")
def select_command(
    run_id: Annotated[str, typer.Argument(help="Dinh danh lan chay")],
    feature: Annotated[
        list[str] | None, typer.Option("--feature", help="Khoa dac trung, vi du column:gia")
    ] = None,
    clear: Annotated[
        bool, typer.Option("--clear", help="Bo lua chon, quay ve phan tich tat ca")
    ] = False,
) -> None:
    """Chon dac trung nao duoc phan tich, roi chay lai bang resume-dag.

    Khong chay gi ca. No sua ke hoach va cho biet nhung task nao se phai lam
    lai - de xem truoc roi moi quyet dinh.
    """
    settings = _load()
    plan_file = _plan_path(settings, run_id)
    try:
        plan = Plan.model_validate_json(plan_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        console.print(f"[red]Chua co ke hoach cho {run_id!r}. Chay run-dag truoc.[/red]")
        raise typer.Exit(code=1) from error

    if clear:
        base = _base_plan_path(settings, run_id)
        if base.is_file():
            plan_file.write_text(base.read_text(encoding="utf-8"), encoding="utf-8")
        _write_selection(settings, run_id, Selection())
        console.print(
            "[green]Da bo lua chon, ke hoach tro lai nhu truoc khi chon.[/green]\n"
            "Chay lai: asys resume-dag " + run_id
        )
        return

    frame, source, spec = _log_frame(settings, run_id)
    catalogue = catalogue_for(
        frame, source, activity=spec.get("activity", ""), resource=spec.get("resource", "")
    )
    # A later choice replaces an earlier one rather than adding to it, so it is
    # always applied to the plan as it was before any choosing.
    base = _base_plan_path(settings, run_id)
    if base.is_file():
        plan = Plan.model_validate_json(base.read_text(encoding="utf-8"))

    try:
        selection = Selection.from_params(feature or [])
        changed = apply_selection(plan, selection, catalogue, _config_dir() / "manifests")
        touched = affected_tasks(plan, selection, catalogue, _config_dir() / "manifests")
    except FeatureError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from error

    # Keep what the plan looked like before anybody chose, so --clear can put it
    # back exactly. Working out afterwards which parameters came from a
    # selection and which the planner set itself would be a guess, and it would
    # be wrong whenever the planner had opinions about columns.
    base = _base_plan_path(settings, run_id)
    if not base.is_file():
        base.write_text(plan_file.read_text(encoding="utf-8"), encoding="utf-8")

    plan_file.write_text(changed.model_dump_json(indent=2), encoding="utf-8")
    _write_selection(settings, run_id, selection)

    console.print(f"[green]Da chon {len(selection.keys)} dac trung.[/green]")
    console.print("Task se lam lai: " + ", ".join(touched))
    console.print(
        "[dim]Cac task phia sau chung cung se lam lai, vi dau vao se khac.[/dim]\n"
        "Chay: asys resume-dag " + run_id
    )


SELECTION_FILENAME = "selection.json"
BASE_PLAN_FILENAME = "plan.base.json"


def _base_plan_path(settings: Settings, run_id: str) -> Path:
    """The plan as it was before anyone narrowed it."""
    return _run_dir(settings, run_id) / BASE_PLAN_FILENAME


def _selection_path(settings: Settings, run_id: str) -> Path:
    """Where a run's feature selection is kept."""
    return _run_dir(settings, run_id) / SELECTION_FILENAME


def _stored_selection(settings: Settings, run_id: str) -> Selection:
    """What was chosen last time, or nothing when nobody has chosen."""
    path = _selection_path(settings, run_id)
    if not path.is_file():
        return Selection()
    try:
        return Selection.from_params(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, FeatureError):
        return Selection()


def _write_selection(settings: Settings, run_id: str, selection: Selection) -> None:
    """Record a choice beside the run it belongs to.

    A file rather than a moment, for the same reason gate decisions are: a run
    that a person steered has to replay the same way, or criterion S1 stops
    meaning anything as soon as anybody makes a choice.
    """
    path = _selection_path(settings, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(selection.keys), indent=2), encoding="utf-8")


def _log_frame(settings: Settings, run_id: str) -> tuple[pd.DataFrame, str, dict[str, str]]:
    """The table a run is working on, and its event-log roles if it has any.

    Read from the plan rather than guessed: the plan already says which table
    each task reads and which columns play which role, and re-deriving that here
    would give two answers to one question.
    """
    plan_file = _plan_path(settings, run_id)
    try:
        plan = Plan.model_validate_json(plan_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        console.print(f"[red]Chua co ke hoach cho {run_id!r}. Chay run-dag truoc.[/red]")
        raise typer.Exit(code=1) from error

    spec: dict[str, str] = {}
    for task in plan.tasks:
        raw = task.params.get("event_log")
        if isinstance(raw, dict):
            spec = {str(key): str(value) for key, value in raw.items() if value}
            break

    state = StateStore(_run_dir(settings, run_id) / "state.json").load()
    for task in reversed(plan.tasks):
        stored = state.task(task.task_id)
        if stored is None:
            continue
        for ref in stored.output_refs:
            if ref.format == "parquet":
                return storage.read_parquet(resolve(ref.path, settings)), ref.path, spec

    console.print(
        f"[red]Lan chay {run_id!r} chua tao ra bang nao de chon dac trung.[/red]\n"
        "Chay run-dag it nhat toi buoc lam sach truoc."
    )
    raise typer.Exit(code=1)


@app.command("gates")
def gates(run_id: Annotated[str, typer.Argument(help="Dinh danh lan chay")]) -> None:
    """Liet ke cac gate dang cho duyet."""
    settings = _load()
    run_dir = _run_dir(settings, run_id)
    try:
        state = StateStore(run_dir / "state.json").load()
    except StateError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from error

    pending = GateStore(run_dir).pending(state)
    if not pending:
        console.print("[green]Khong con gate nao cho duyet.[/green]")
        return
    for request in pending:
        console.print(render_gate(request))
        console.print("")


@app.command("approve")
def approve(
    run_id: Annotated[str, typer.Argument(help="Dinh danh lan chay")],
    gate: Annotated[str, typer.Option("--gate", help="Ma gate")] = GATE_RULES,
    select: Annotated[list[str] | None, typer.Option("--select", help="Muc duoc duyet")] = None,
    reject: Annotated[list[str] | None, typer.Option("--reject", help="Muc bi tu choi")] = None,
    note: Annotated[str, typer.Option("--note", help="Ghi chu")] = "",
) -> None:
    """Ghi quyet dinh duyet vao state. Quyet dinh duoc luu nhu du lieu va phat lai khi chay lai."""
    settings = _load()
    run_dir = _run_dir(settings, run_id)
    states = StateStore(run_dir / "state.json")
    try:
        state = states.load()
        request = GateStore(run_dir).read(gate)
        decision = decide(
            request,
            approved=tuple(select or ()),
            rejected=tuple(reject or ()),
            note=note,
            now=datetime.now(UTC),
        )
    except (StateError, GateError) as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(code=1) from error

    states.save(state.with_gate(decision))
    # A run that recorded a plan is resumed by the plan runner, not the Phase 1
    # loop. Printing the wrong command sends the operator into an error.
    command = "resume-dag" if _plan_path(settings, run_id).is_file() else "resume"
    console.print(
        f"[green]Da ghi quyet dinh[/green] gate={gate} "
        f"duyet={list(decision.approved)} tu_choi={list(decision.rejected)}\n"
        f"Chay tiep: asys {command} {run_id}"
    )


@app.command("resume")
def resume(run_id: Annotated[str, typer.Argument(help="Dinh danh lan chay")]) -> None:
    """Chay tiep mot lan chay dang dung.

    Khong can --input va khong nap lai du lieu: lan chay da ghi lai tham chieu
    toi bang staging, va bang do van con nguyen o day.
    """
    settings = _load()
    store = StateStore(_run_dir(settings, run_id) / "state.json")
    try:
        stored = store.load()
    except StateError as error:
        console.print(
            f"[red]Chua co state cho {run_id!r}, khong biet chay tiep tu dau.[/red]\n"
            "Lan dau phai dung: asys run-agents --input <file.csv>"
        )
        raise typer.Exit(code=1) from error

    if stored.source is None:
        console.print(
            "[red]State cua lan chay nay khong ghi nguon du lieu.[/red]\n"
            "Hay bat dau lai bang: asys run-agents --input <file.csv>"
        )
        raise typer.Exit(code=1)

    _phase1(settings, stored.source, run_id)


if __name__ == "__main__":
    app()
