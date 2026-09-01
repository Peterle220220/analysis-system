"""Command line entry point: python -m analysis_system.cli

Phase 0 exposes three commands: check the configuration, prepare the data
layers, and run the pipeline. Every error message is in Vietnamese, because the
person reading it is the operator, not the author.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from analysis_system.contracts.agents import Plan
from analysis_system.contracts.base import DataFormat, DataRef
from analysis_system.manager.dag_runner import DagRunner
from analysis_system.manager.gates import GateError, GateStore, decide, render_gate
from analysis_system.manager.planner import PlanError, Planner, validate_plan
from analysis_system.manager.runner import GATE_RULES, Phase1Runner, RunOutcome
from analysis_system.manager.state import StateError, StateStore
from analysis_system.pipeline import run as pipeline
from analysis_system.services import storage
from analysis_system.services.budget import (
    BudgetError,
    BudgetExceeded,
    BudgetTracker,
    load_budget,
    load_pricing,
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
    verify_layers,
)

BPI_SOURCE_NAME = "BPI_Challenge_2019.xes"
BPI_DOWNLOAD_URL = "https://data.4tu.nl/articles/dataset/BPI_Challenge_2019/12715853"
FIXTURE_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "bpi19_slice.csv"
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
        return LlmClient(HandoffProvider(run_dir / "handoff"))
    if choice == "cassette":
        return LlmClient(CassetteProvider(cassette_path(settings)))
    if choice == "gemini":
        return LlmClient(
            GeminiProvider(
                settings.llm.gemini_model,
                thinking=settings.llm.gemini_thinking,
                budget=budget,
            )
        )
    if choice == "anthropic":
        return LlmClient(AnthropicProvider(settings.llm.active_model, budget=budget))
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

    target_uri = f"raw://{run_id}_{source.name}"
    target = resolve(target_uri, settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    ref = DataRef(
        path=target_uri,
        format=_format_of(source),
        content_hash=storage.sha256_file(target),
    )

    run_directory = _run_dir(settings, run_id)
    run_directory.mkdir(parents=True, exist_ok=True)
    storage.write_text(Plan.model_dump_json(plan, indent=2), _plan_path(settings, run_id))
    console.print(f"[dim]Ke hoach {len(plan.tasks)} task -> {target_uri}[/dim]")
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

    table = Table(title="Ke hoach de xuat")
    table.add_column("Task")
    table.add_column("Agent")
    table.add_column("Sau khi")
    table.add_column("Doc tu")
    for task in proposed.tasks:
        table.add_row(
            task.task_id,
            task.agent_id,
            ", ".join(task.depends_on) or "-",
            ", ".join(task.reads_from) or "nguon",
        )
    console.print(table)
    console.print(f"[dim]{proposed.reason}[/dim]")

    if out is not None:
        storage.write_text(Plan.model_dump_json(proposed, indent=2), out.expanduser())
        console.print(f"[green]Da ghi[/green] {out}")


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
