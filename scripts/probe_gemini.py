#!/usr/bin/env python3
"""Ask Gemini one real question per answer shape, and report what came back.

Everything about the provider is already covered by tests with a faked
transport. The one thing a test cannot settle is whether the vendor actually
honours the schemas this system demands - so that question gets asked once,
here, against the live API.

The six shapes are tried in order of how much they ask for. If the simple ones
pass and the ones carrying a free-form dictionary fail, that is a precise
finding rather than a vague "it did not work".

    export GEMINI_API_KEY=...
    ./.venv/bin/python scripts/probe_gemini.py
"""

from __future__ import annotations

import os
import sys
from typing import Final

from pydantic import BaseModel

from analysis_system.contracts.agents import (
    FindingProposal,
    NarrativeProposal,
    Plan,
    ProfileInterpretation,
    RuleProposal,
    SqlProposal,
)
from analysis_system.services.llm import (
    DEFAULT_GEMINI_MODEL,
    GEMINI_KEY_ENV,
    GeminiProvider,
    LlmError,
    LlmRequest,
)

# Ordered simplest first. The last three carry a dictionary whose keys are not
# known until the data is seen, which is the part most likely to be refused.
CASES: Final[tuple[tuple[type[BaseModel], str, str], ...]] = (
    (
        NarrativeProposal,
        "khong co dict",
        "Viet mot cau tom tat ve gia nha, dung placeholder {price.mean} cho con so.",
    ),
    (
        SqlProposal,
        "khong co dict",
        "Bang 'houses' co cot city (text) va price (text). Viet SQL lay gia trung binh"
        " theo thanh pho, khai bao lineage cho tung cot dau ra.",
    ),
    (
        FindingProposal,
        "khong co dict",
        "Cac chi so co san: price.mean = 550000, city.Seattle.share_pct = 50."
        " Rut hai ket luan, moi con so phai la placeholder dang {ten_chi_so}.",
    ),
    (
        ProfileInterpretation,
        "CO dict tu do",
        "Bang co cac cot: case_id, activity, timestamp, cumulative_net_worth_eur."
        " Giai thich y nghia tung cot.",
    ),
    (
        RuleProposal,
        "CO dict tu do",
        "Cot 'city' co khoang trang thua o dau va cuoi. De xuat rule trim_whitespace cho cot do.",
    ),
    (
        Plan,
        "CO dict tu do",
        "Cac agent co san: a1_ingest (doc raw, ghi staging), a2_profiler (doc staging,"
        " ghi profile). Lap ke hoach nap file roi mo ta du lieu.",
    ),
)

SYSTEM: Final[str] = "Ban tra loi bang JSON dung khuon duoc yeu cau. Khong giai thich gi them."


def main() -> int:
    """Try every shape and print a verdict per shape."""
    if not os.environ.get(GEMINI_KEY_ENV):
        print(
            f"Chua co {GEMINI_KEY_ENV}.\n"
            f"  Lay khoa mien phi: https://aistudio.google.com/apikey\n"
            f"  Roi chay:  export {GEMINI_KEY_ENV}=...",
            file=sys.stderr,
        )
        return 1

    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    provider = GeminiProvider(model)
    print(f"Model: {model}\n")

    failures = 0
    for schema, note, question in CASES:
        label = f"{schema.__name__:22} [{note}]"
        try:
            answer = provider.complete(
                LlmRequest(purpose="probe", system=SYSTEM, prompt=question, schema=schema)
            )
        except LlmError as error:
            failures += 1
            print(f"  HONG   {label}")
            for line in str(error).splitlines()[:12]:
                print(f"         {line}")
            print()
            continue
        tokens = f"{answer.tokens_in}+{answer.tokens_out} token" if answer.tokens_total else ""
        print(f"  OK     {label} {tokens}")
        print(f"         {answer.data.model_dump_json()[:160]}")
        print()

    total = len(CASES)
    print(f"Ket qua: {total - failures}/{total} khuon duoc chap nhan.")
    if failures:
        print(
            "\nKhuon nao hong thi doc thong bao o tren - no in nguyen phan hoi cua"
            "\nGemini, du de biet phai sua cho nao."
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
