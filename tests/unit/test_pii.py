"""PII tests: nothing identifiable may reach a model, by masking or by omission."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from analysis_system.core.pii import (
    MAX_LLM_SAMPLE_ROWS,
    PiiLeakError,
    PiiMasker,
    assert_no_pii,
    build_llm_sample,
    find_pii,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pii_sample.csv"


def test_an_email_is_replaced_by_a_token() -> None:
    masker = PiiMasker()
    masked = masker.mask_text("Lien he lenamphong2000@gmail.com de biet them")
    assert "lenamphong2000@gmail.com" not in masked
    assert "<EMAIL_1>" in masked


def test_the_same_value_always_gets_the_same_token() -> None:
    masker = PiiMasker()
    first = masker.mask_text("a@x.com goi cho a@x.com")
    assert first.count("<EMAIL_1>") == 2
    assert masker.token_count == 1


def test_different_values_get_different_tokens() -> None:
    masker = PiiMasker()
    masked = masker.mask_text("a@x.com va b@y.com")
    assert "<EMAIL_1>" in masked
    assert "<EMAIL_2>" in masked


def test_vietnamese_phone_numbers_are_masked() -> None:
    masker = PiiMasker()
    for raw in ("0912345678", "+84912345678", "091 234 5678"):
        assert raw not in masker.mask_text(f"So dien thoai: {raw}")


def test_a_bare_digit_run_is_masked_when_the_column_says_what_it_is() -> None:
    masker = PiiMasker()
    masked = masker.mask_text("19001234567", "so_tai_khoan")
    assert "19001234567" not in masked


def test_a_bare_digit_run_is_left_alone_without_that_context() -> None:
    # A house price of 26,590,000 matches the bank-account pattern. Masking it
    # would hide a price list and protect nobody.
    masker = PiiMasker()
    assert masker.mask_text("26590000.0", "price") == "26590000.0"
    assert masker.mask_text("2000000000_00001", "case_id") == "2000000000_00001"


def test_a_tax_id_is_masked_anywhere_because_its_shape_is_distinctive() -> None:
    masker = PiiMasker()
    assert "0101234567-001" not in masker.mask_text("MST 0101234567-001", "ghi_chu")


def test_masking_uses_the_column_name_of_each_cell() -> None:
    masker = PiiMasker()
    (row,) = masker.mask_rows([{"price": "26590000", "bank_account": "19001234567"}])
    assert row["price"] == "26590000"
    assert row["bank_account"] != "19001234567"


def test_ordinary_numbers_are_left_alone() -> None:
    masker = PiiMasker()
    text = "So dong 1000, nam 2019, ty le 26.6%"
    assert masker.mask_text(text) == text


def test_names_are_deliberately_not_masked() -> None:
    # The spec rules out NER for Vietnamese names. Names are protected by never
    # sending the column, which build_llm_sample enforces - not by masking.
    masker = PiiMasker()
    assert masker.mask_text("Le Nam Phong") == "Le Nam Phong"


def test_the_leak_guard_ignores_a_large_number() -> None:
    # The guard checks distinctive shapes only. It cannot judge a bare number
    # without knowing its column, and blocking every large one is useless.
    assert_no_pii("gia cao nhat 26590000.0, dien tich 13540")


def test_the_leak_guard_still_catches_a_tax_id() -> None:
    with pytest.raises(PiiLeakError, match="TAX_ID"):
        assert_no_pii("MST 0101234567-001")


def test_the_leak_guard_catches_an_unmasked_value() -> None:
    with pytest.raises(PiiLeakError):
        assert_no_pii("payload con lot email a@x.com")


def test_the_leak_guard_passes_a_masked_payload() -> None:
    assert_no_pii(PiiMasker().mask_text("email a@x.com, dien thoai 0912345678"))


def test_find_pii_reports_everything_it_recognises() -> None:
    assert len(find_pii("a@x.com va 0912345678")) == 2


# --- what the model is actually allowed to see --------------------------------


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "case_id": [f"c{index}" for index in range(30)],
            "vendor_name": [f"Nguoi Ban {index}" for index in range(30)],
            "vendor_email": [f"ban{index}@vendor.com" for index in range(30)],
            "amount": [100.0 + index for index in range(30)],
        }
    )


def test_pii_columns_contribute_statistics_but_never_values() -> None:
    sample = build_llm_sample(frame(), pii_columns=["vendor_name", "vendor_email"])
    serialised = json.dumps(sample, ensure_ascii=False)
    assert "ban0@vendor.com" not in serialised
    assert "Nguoi Ban 0" not in serialised
    assert sample["statistics"]["vendor_email"]["distinct"] == 30
    assert sample["pii_columns"] == ["vendor_email", "vendor_name"]


def test_the_sample_never_exceeds_twenty_rows() -> None:
    sample = build_llm_sample(frame(), max_rows=1000)
    assert len(sample["sample_rows"]) == MAX_LLM_SAMPLE_ROWS


def test_non_pii_columns_are_still_masked_as_a_second_line_of_defence() -> None:
    # vendor_email is NOT flagged here, so it survives into the sample - and
    # must still come out masked.
    sample = build_llm_sample(frame(), pii_columns=[])
    serialised = json.dumps(sample["sample_rows"], ensure_ascii=False)
    assert "ban0@vendor.com" not in serialised
    assert "<EMAIL_1>" in serialised


def test_the_whole_sample_passes_the_leak_guard() -> None:
    sample = build_llm_sample(frame(), pii_columns=["vendor_name"])
    assert_no_pii(json.dumps(sample["sample_rows"], ensure_ascii=False))


@pytest.mark.skipif(not FIXTURE.is_file(), reason="chua co tests/fixtures/pii_sample.csv")
def test_the_dedicated_pii_fixture_is_fully_masked() -> None:
    # BPI 2019 is anonymised and cannot exercise this path, so a small hand
    # written fixture covers it instead.
    data = pd.read_csv(FIXTURE, dtype=str)
    sample = build_llm_sample(data, pii_columns=["full_name"])
    assert_no_pii(json.dumps(sample["sample_rows"], ensure_ascii=False))
