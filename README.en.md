**English** · [Tiếng Việt](README.md)

<div align="center">

# Analysis System

**An on-premise, multi-agent data analysis platform where every number in an answer traces back to the source rows it came from.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)](src/analysis_system/api)
[![Next.js](https://img.shields.io/badge/Next.js-frontend-000000?logo=nextdotjs&logoColor=white)](frontend)
[![DuckDB](https://img.shields.io/badge/DuckDB-engine-FFF000?logo=duckdb&logoColor=black)](src/analysis_system/domains/execution_engine)

[![Tests](https://img.shields.io/badge/tests-2987%20passing-brightgreen)](tests)
[![Coverage](https://img.shields.io/badge/coverage-90.7%25-brightgreen)](#code-quality)
[![mypy](https://img.shields.io/badge/mypy-strict-blue)](pyproject.toml)
[![Ruff](https://img.shields.io/badge/ruff-clean-261230?logo=ruff&logoColor=white)](pyproject.toml)
[![Architecture](https://img.shields.io/badge/DDD-0%20layer%20violations-7B3FE4)](#architecture)
[![Deployment](https://img.shields.io/badge/deployment-on--premise-334155?logo=docker&logoColor=white)](DEPLOY.md)
[![API cost](https://img.shields.io/badge/handoff%20mode-%240-success)](#running-costs)

</div>

---

Hand it your data, and the system cleans it and gives the clean version back for you to
review. Ask a question, and it assigns the work to specialised AIs, then answers **with
evidence for every number**.

Ask as many follow-up questions as you like.

| | |
|---|---|
| [Overview](#overview) | [Technical highlights](#technical-highlights) |
| [Workflow](#workflow) | [Quick start](#quick-start) |
| [Architecture](#architecture) | [Directory structure](#directory-structure) |
| [Numbers that cannot be made up](#numbers-that-cannot-be-made-up) | [Who does what](#who-does-what) |
| [Security and on-premise operation](#security-and-on-premise-operation) | [Code quality](#code-quality) |
| [Running costs](#running-costs) | [Documentation](#documentation) |

---

## Overview

| | |
|---|---|
| **Problem** | Analysing business data without having to take a model's word for it |
| **Approach** | 14 agents (a Manager and 13 specialists), each running inside a granted scope it cannot exceed; every number is computed by code, the model only interprets |
| **Deployment** | On-premise. Your data stays on your machine; only what the model is asked is sent out, and only when you enable a provider that calls an API |
| **Interfaces** | Web (Next.js) and command line (`asys`) |
| **Storage** | DuckDB and Parquet on local disk, split into data layers |
| **API cost** | $0 in `handoff` mode; all testing against real APIs cost about $7.6 for 220 calls |

---

## Technical highlights

| Area | Figure | Enforced by |
|---|---|---|
| **Test coverage** | **90.7%** (12,999 / 14,326 statements) | `pytest --cov`, re-measured on 18 September 2026 |
| Test suite | **2,987 tests** across 150 files (unit, contract, criteria, golden, regression) | `make test` |
| Static typing | **mypy strict**, 0 errors across 294 files | `mypy src tests` |
| Lint and formatting | **ruff**, 0 warnings | `ruff check` |
| Architecture layer violations | **0**, no exceptions left | `tests/unit/test_architecture.py` |
| Agents touching the disk directly | **0** | a lint rule and an AST test |
| Data sent off the machine | **0 bytes** in `handoff` mode | `provider` in `config/settings.yaml` |
| Secrets leaked into git | **0** | `scripts/secret_scan.py` runs on the diff before every commit |

---

## Workflow

```
You provide a file
   ↓
The system reads it and proposes how to clean it  →  STOPS, waits for your approval
   ↓
You get the clean dataset back
   ↓
You ask a question
   ↓
Manager splits the work → specialised AIs process it → Manager combines the results
   ↓
Answer, with the source of every number           →  STOPS, waits for your approval
   ↓
You ask a follow-up  →  back to the step above
```

The two **STOPS** are deliberate. The system does not change your data on its own and does
not publish conclusions on its own. You have the final say.

---

## Quick start

```bash
# 1. Load a file and clean it
asys clean --input ~/du_lieu/ban_hang.csv --run-id bh

# 2. See what it intends to do, then approve
asys gates bh
asys approve bh --gate gate_t3_clean --select trim_whitespace

# 3. Get the clean version
asys resume-dag bh

# 4. Ask
asys ask bh "Kênh nào có doanh thu cao nhất, và thấp nhất?"

# 5. Keep asking, as many times as you like
asys ask bh "Doanh thu có xu hướng tăng theo thời gian không?"
```

*(The example questions are in Vietnamese: "Which channel has the highest revenue, and the
lowest?" and "Is revenue trending up over time?")*

Not sure what kind of files you have? Ask first:

```bash
asys route ~/du_lieu/
```

It reads the first few bytes of each file and tells you which reader can open it. **The
format is decided by the content, not the file extension.** A PDF named `.csv` is still
recognised correctly.

### Web interface

```bash
asys set-password     # set a password; it is written to .env automatically
asys serve            # open http://localhost:8020
```

Deploying with Docker and systemd: see [DEPLOY.md](DEPLOY.md).

### What it can read

| Type | Formats |
|---|---|
| Tables | CSV · Excel · JSON · Parquet |
| Documents | PDF · **Word** · **Email** · **HTML** |
| Images | PNG · JPEG · TIFF (reads text in images) |
| Audio | WAV · MP3 · M4A · MP4 (listens and transcribes speech) |

### What it can export

```bash
asys export clean://ban_hang.parquet --out bao_cao.xlsx
```

CSV · Excel · Word · Markdown · HTML · JSON. **The output format is your choice and has
nothing to do with the input format.** Read a PDF and export Excel, or read a CSV and
export Word. Excel and CSV open directly in Tableau or Power BI.

---

## Architecture

The system follows Clean Architecture and Domain-Driven Design. The source code is split
into five layers, and **dependency arrows only point downwards**: an upper layer calls a
lower one, never the other way round.

### How a request flows through the layers

```
     ┌──────────────────┐        ┌──────────────────┐
     │     Browser      │        │   asys CLI       │
     └────────┬─────────┘        └────────┬─────────┘
              │ HTTP :3000                │
     ┌────────▼─────────┐                 │
     │ Next.js frontend │  the only port  │
     │   (frontend/)    │  open to the    │
     └────────┬─────────┘  network        │
              │ REST /api/* to 127.0.0.1  │
╔═════════════▼═══════════════════════════▼═══════════════════════════════════╗
║ LAYER 4  api/            Receives requests, checks the session, calls down,  ║
║                          returns JSON. No business rule lives here.          ║
║                          app.py 61 lines · 6 routers · presenters build JSON ║
╠═════════════╪════════════════════════════════════════════════════════════════╣
║             ▼                                                                ║
║ LAYER 3  application/    Orchestrates use cases: clean, ask, approve, delete.║
║                          Knows the order of steps, knows nothing of HTTP.    ║
╠═════════════╪════════════════════════════════════════════════════════════════╣
║             ▼                                                                ║
║ LAYER 2  agents/         Manager plans, assigns work, combines results.      ║
║          manager/        Each agent works inside the boundary it is granted. ║
║          domains/        Business logic, one folder per domain:              ║
║                            data_ingestion    load · read · clean · datasets  ║
║                            execution_engine  SQL and all deterministic maths ║
║                            ai_planner        prompts · model calls · checks  ║
║                            visualization     charts · BI · reports · export  ║
╠═════════════╪════════════════════════════════════════════════════════════════╣
║             ▼                                                                ║
║ LAYER 1  models/         Shared contracts: ScopeToken, DataRef,              ║
║                          the result each agent returns.                      ║
╠═════════════╪════════════════════════════════════════════════════════════════╣
║             ▼                                                                ║
║ LAYER 0  core/           Configuration, layered data storage, boundaries,    ║
║                          audit, budget, Vietnamese text.                     ║
╚═════════════╪════════════════════════════════════════════════════════════════╝
              ▼
     ┌──────────────────────────────────────────────────────────────┐
     │  Local disk:  raw → extracted → staging → clean → mart        │
     │               DuckDB · Parquet · JSONL audit log              │
     └──────────────────────────────────────────────────────────────┘
```

### Dependency rule

```
api  ──▶  application  ──▶  agents · manager · domains  ──▶  models  ──▶  core
```

- `core` does not import domains, agents, manager, application or api.
- `models` imports only `core`.
- Domains do not import `application` or `api`.
- One domain **does not** import another. Bridging them is the job of the layer above.

The rule is enforced by a test ([`tests/unit/test_architecture.py`](tests/unit/test_architecture.py)):
an import that goes against the layers fails the test immediately, and there are currently
**no exceptions**. A new top-level package that has not been assigned a layer also fails
the test, so the structure cannot drift silently.

The frontend is a separate Next.js application in [`frontend/`](frontend) that talks to
the backend only over REST. Not a single line of HTML is generated by Python.

---

## Directory structure

```
analysis-system/
│
├── src/analysis_system/            # Backend
│   ├── api/                        # LAYER 4 · 10 modules + 6 routers
│   │   ├── app.py                  #   61 lines, only wires the routers together
│   │   ├── routers/                #   session · system · datasets · runs · bi · dashboards
│   │   ├── session.py  auth.py     #   login session, password, cookie
│   │   ├── replies.py  inputs.py   #   normalised error replies, input validation
│   │   ├── once.py                 #   stops the same action being submitted twice
│   │   └── view.py  state.py  tree.py    # build JSON for the UI, decide no rules
│   │
│   ├── application/                # LAYER 3 · 1 module
│   │   └── workspace.py            #   orchestrates every use case
│   │
│   ├── agents/                     # LAYER 2 · 13 modules, 14 agents
│   │   ├── a1_ingest.py … a10_text_miner.py
│   │   ├── extractors.py           #   E1-E4: PDF · image · audio · document
│   │   └── base.py  feedback.py
│   │
│   ├── manager/                    # LAYER 2 · 9 modules
│   │   ├── planner.py  dispatcher.py  dag_runner.py  runner.py
│   │   ├── gates.py                #   the two stops that wait for human approval
│   │   └── verifier.py  selection.py  retry.py  state.py
│   │
│   ├── domains/                    # LAYER 2 · 65 modules
│   │   ├── data_ingestion/         #   20 · load, read, cleaning rules, datasets, glossary
│   │   ├── execution_engine/       #   18 · SQL, statistics, forecasting, process mining
│   │   ├── ai_planner/             #   16 · prompts, model calls, reading questions, checks
│   │   └── visualization/          #   11 · charts, self-service analysis, dashboards, export
│   │
│   ├── models/                     # LAYER 1 · 2 modules
│   │   ├── base.py                 #   ScopeToken, DataRef, shared types
│   │   └── agents.py               #   input and output contracts of each agent
│   │
│   ├── core/                       # LAYER 0 · 14 modules
│   │   ├── settings.py             #   reads config; no constants live in code
│   │   ├── storage.py  scoped_storage.py    # data layers, controlled paths
│   │   ├── boundary.py             #   enforces each agent's scope
│   │   ├── audit.py                #   append-only log, never edited
│   │   ├── budget.py  retention.py #   cost caps, data lifecycle
│   │   ├── pii.py  hashing.py      #   detect personal data, anonymising hashes
│   │   └── vietnamese_text.py  punctuation.py  units.py  job_error.py  updater.py
│   │
│   ├── pipeline/                   # runs one full pass end to end
│   └── cli.py                      # entry point of the `asys` command
│
├── frontend/                       # Next.js, TypeScript
│   └── src/  app/  components/  lib/
│
├── tests/                          # 2,987 tests across 150 files
│   ├── unit/                       #   111 files
│   ├── contract/                   #   34 files, input and output contracts of each agent
│   ├── criteria/                   #   4 files, the spec's S1-S4 criteria
│   ├── golden/  regression/        #   reference results, past bugs that must not return
│   └── cassettes/  fixtures/       #   pre-recorded model answers, sample data
│
├── config/                         # settings.yaml · budget.yaml · pricing.yaml · manifests/
├── prompts/                        # each agent's prompts, kept out of the code
├── deploy/                         # asys.service · asys-web.service · restart-services.sh
├── scripts/                        # secret_scan.py · install.sh · operations tools
├── plans/                          # plans for engineering campaigns
│
├── Dockerfile  docker-compose.yml  # on-premise deployment
├── Makefile  tasks.py              # quality gates: lint · type · test · coverage
└── pyproject.toml  requirements.lock.txt
```

---

## Numbers that cannot be made up

This is where the system differs from an ordinary AI.

**The AI is not allowed to type a single number.** It writes sentences with blanks, and
code fills the numbers in:

```
AI writes :  "Nhóm {ten:X.mean.by.kenh.app} xử lý lâu nhất, {X.mean.by.kenh.app}."
You read  :  "Nhóm app xử lý lâu nhất, 24.53 giờ."
```

*(In English: "Group {name} takes longest to process, {value}." → "Group app takes longest
to process, 24.53 hours.")*

Any sentence containing a digit the AI typed itself is **rejected in full**, not repaired.
Repairing it would mean guessing what it meant to say.

The system also blocks, on its own:

- **Naming the wrong top group.** Code re-compares the numbers; saying `sadness` is
  highest when it is actually `joy` gets the whole sentence rejected
- **Claiming a test was run that never ran.** *"A t-test shows a significant difference"*
  with no t-test behind it is rejected
- **Causal inference** from figures that only measure an association
- **Asking for irrelevant data.** Asking about emotions and requesting *"2024 sales"* is
  rejected
- **Answering half the question without saying so.** Asked for the highest *and* the
  lowest but able to answer only one, it states clearly that the other is left open

And whatever **could not** be found is always reported alongside what was found. A
conclusion that stretches over a gap nobody mentions is exactly what this whole system is
built to prevent.

---

## Who does what

**The Manager** computes nothing itself. It reads the question, breaks it into small
tasks, assigns each to the right agent, then combines the results. It runs on the
strongest model because this is the hardest reasoning job.

**The specialised agents** each do one job:

| | What it does | Uses AI? |
|---|---|---|
| A1 Ingest | reads a file into a table | No |
| A2 Profiler | measures what the data has and what is missing | Yes, only to interpret |
| A3 Cleaner | **proposes** cleaning rules | Yes, only to propose |
| A4 Transformer | builds analysis tables in SQL | Yes |
| A5 Validator | scores data against declared criteria | **No** |
| A6 Process Miner | measures how a process actually runs | Yes, only for naming |
| A7 Analyst | draws conclusions from computed numbers | Yes, only to interpret |
| A8 Reporter | writes the report | Yes |
| A10 Text Miner | counts words, measures which words are distinctive | **No** |
| E1-E4 | read PDF, images, audio, documents | **No** |

The **No** entries are deliberate: counting words and scoring data are **arithmetic**. A
model asked *"which words matter"* will answer very confidently, not reproducibly, and
with nothing to check it against, while the numbers come out the same every time they are
recomputed.

---

## Security and on-premise operation

The system is designed to run inside your network, on your machine.

**Where the data lives.** All data sits on local disk, split into the layers
`raw → extracted → staging → clean → mart`, stored as Parquet and read in-process by
DuckDB. There is no external database server and no cloud storage. Each layer's path is
declared independently in `config/settings.yaml`, so pointing a layer at another drive
does not require changing a single line of code.

**Does data leave the machine.** In `provider: handoff` mode, **no**. The system writes
the question to a file for you to paste into your own AI account. The configuration in the
repository enables `openrouter` (paid tier) so the system answers on its own; changing one
line in `config/settings.yaml` switches it back to `handoff`. When a provider that calls a
real API is enabled, every request passes through a token cap, a
cost cap and a time cap; `config/settings.yaml` states which providers use submitted data
for training, with a warning not to use those providers with customer data.

**Agent scope.** Each agent runs with a `ScopeToken` issued from its manifest, and
`core/boundary.py` checks three layers: before the run, during the run, and on the
returned result. *Stating the limit plainly:* agents run in the same process as the
Manager, so the during-run layer is a cooperative sandbox, not an operating-system-level
sandbox. It is backed by a lint rule and an AST test that stop an agent from reaching into
the file system behind its back.

**Model-written SQL.** Nothing runs until `sql_guard` allows it: only `SELECT` and
`CREATE VIEW`; `DROP` `DELETE` `UPDATE` `ATTACH` are forbidden, touching tables outside the
assigned scope is forbidden, and unconditioned cross joins are forbidden. This is the first
of two lines of defence: A4 runs queries against an in-memory database loaded from
Parquet, so even if a statement slipped through there would be nothing durable to damage.

**Audit log.** `core/audit.py` records each event as one line of JSON, append-only, never
editing an old line. A run is considered clean when the log has no unhandled
`BOUNDARY_VIOLATION` left.

**Network surface.** The FastAPI backend listens only on `127.0.0.1:8020`; Next.js is the
only port open to the network. Login uses a single password, and sessions live in the
process memory, so restarting the server ends all sessions.

**Secrets.** API keys and passwords live only in `.env` (gitignored), never in
`.env.example`. `scripts/secret_scan.py` scans the diff before every commit.

**Personal data.** `core/pii.py` detects sensitive fields and `core/hashing.py` hashes them
anonymously when needed. `core/retention.py` manages the data lifecycle: deletion must be
confirmed by hand, and it only touches a run's working files, never your original data.

---

## Code quality

Every commit must pass all the gates below. Failing any gate stops the line.

| Gate | Command | Current result |
|---|---|---|
| Lint and formatting | `ruff check` | clean |
| Static typing | `mypy src tests` (strict) | 0 errors across 294 files |
| Full test suite | `pytest` | 2,985 passed, 2 skipped (need a licensed log file) — measured 18 September 2026 |
| Coverage | `pytest --cov` | **90.7%**, 1,327 / 14,326 statements not covered — measured 18 September 2026 |
| Architecture | `pytest tests/unit/test_architecture.py` | 0 layer violations |
| Deployment | `docker compose build` and curl | `/` 200 · `/api/health` 200 · `/api/data` 401 |
| Secrets | `python scripts/secret_scan.py` | clean |

The tests are organised by role, not by source file:

- **unit** checks each module on its own
- **contract** checks each agent's input and output contract, so changing an agent's
  internals does not break its callers
- **criteria** checks the spec's four criteria S1-S4, where S4 requires every number to
  trace back to source rows
- **golden** keeps reference results on sample data
- **regression** keeps every bug already met, so it does not come back

---

## Running costs

In `provider: handoff` mode: **no API calls, $0**. The system writes the question to a
file; you paste it into your own AI account and paste the result back.

The configuration in the repository uses `openrouter` to answer automatically. All testing
on real data cost **$7.57 for 220 model calls** (summed from the `budget.json` files,
6–16 September 2026). Every run has a token cap, a
cost cap and a time cap. Hitting a cap means **stop**; it never continues on its own.

### Cleaning up

```bash
asys runs                          # see how much space runs are taking
asys forget --giu 10               # LIST what would be deleted
asys forget --giu 10 --xac-nhan    # actually delete
```

Without `--xac-nhan` (confirm) nothing is deleted. Your original data is never touched.

---

## Documentation

| | |
|---|---|
| Installation, deployment | [DEPLOY.md](DEPLOY.md) |
| Progress of each part | [PROGRESS.md](PROGRESS.md) |
| Original specification | [BUILD_SPEC.md](BUILD_SPEC.md) |
| DDD refactoring plan | [plans/refactor-ddd.md](plans/refactor-ddd.md) |
| **81 bugs met and how they were fixed** | [NOTES.md](NOTES.md) |

`NOTES.md` is the one most worth reading if you want to know why the system was built
this way. It records each bug exactly as it was met, not rewritten to look good, including
bugs that every test let through and that only surfaced when running on real data.
(These documents are written in Vietnamese.)
