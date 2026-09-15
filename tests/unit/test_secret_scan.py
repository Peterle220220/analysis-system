"""scripts/secret_scan.py: bắt khoá trong dòng thêm mới, không bắt chữ thường.

Khoá giả trong file này được ghép lúc chạy. Viết liền một chuỗi trông như khoá thì chính
file test sẽ bị bộ quét chặn lúc commit.
"""

from __future__ import annotations

from secret_scan import SHOWN, added_lines, hits, self_check

FAKE_ANTHROPIC = "sk-" + "ant-" + "a" * 30
FAKE_OPENROUTER = "sk-" + "or-v1-" + "b" * 40
FAKE_GOOGLE = "AI" + "za" + "c" * 35


def diff_with(*lines: str) -> str:
    return "\n".join(("diff --git a/x b/x", "--- a/x", "+++ b/x", "@@ -1 +1 @@", *lines))


def test_the_pattern_checks_itself() -> None:
    self_check()


def test_a_key_in_an_added_line_is_caught() -> None:
    for key in (FAKE_ANTHROPIC, FAKE_OPENROUTER, FAKE_GOOGLE):
        assert hits(added_lines(diff_with(f"+API_KEY={key}"))), key


def test_a_removed_line_is_not_scanned() -> None:
    assert hits(added_lines(diff_with(f"-API_KEY={FAKE_ANTHROPIC}"))) == []


def test_the_file_header_is_not_an_added_line() -> None:
    assert added_lines(diff_with("+x = 1")) == ["+x = 1"]


def test_prose_mentioning_a_prefix_is_not_a_key() -> None:
    assert hits(["+Khoa Anthropic bat dau bang sk-ant- roi toi chuoi dai"]) == []


def test_a_hit_shows_only_the_start_of_the_line() -> None:
    (shown,) = hits([f"+{FAKE_ANTHROPIC}"])
    assert shown == f"+{FAKE_ANTHROPIC}"[:SHOWN] + "..."
    assert FAKE_ANTHROPIC not in shown
