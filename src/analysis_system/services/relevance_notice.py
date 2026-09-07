"""Lớp lọc "đúng chủ đề" không chạy được — nói ra, và nói phải làm gì.

Câu hỏi gõ không dấu thì `relevance.comparable()` trả False, và mọi kết luận
được **giữ nguyên, chưa qua kiểm**. Đó là lựa chọn đúng — thước đo ngữ nghĩa
không biết "diem thi" và "điểm thi" là một, nên chấm chéo dấu đã ném đi 8 trên
16 câu trả lời đúng khi đo lần đầu.

Nhưng nó **im lặng**, và đó mới là vấn đề. Câu trả lời hiện ra y hệt một câu đã
qua đủ lớp kiểm.

**Đã đo phương án hạ xuống dùng `LexicalScorer`** — thước đo này bỏ dấu trước
khi so nên không ngại lệch dấu. 36 cặp lấy từ ba lượt chạy thật, 12 cặp đúng
chủ đề:

    semantic (đủ dấu)      ngưỡng 0.25    giữ 11/12 đúng, bỏ oan 1
    lexical (hỏi mất dấu)  ngưỡng 0.05    giữ  8/12 đúng, bỏ oan 4
    lexical (hỏi mất dấu)  ngưỡng 0.10    giữ  6/12 đúng, bỏ oan 6

Ném oan một phần ba kết luận đúng để lọc thêm được ít lạc đề là một cuộc đổi
chác tồi: thiếu một kết luận đúng thì không ai biết mà đòi, còn thừa một kết
luận lạc đề thì người đọc nhìn ra. Nên không hạ xuống lexical.

Còn lại đúng một việc đáng làm: **nói ra**. Gộp thành một dòng thay vì mỗi kết
luận một dòng, đưa lên đầu trang, và chỉ luôn cách chữa — gõ câu hỏi có dấu.
"""

from __future__ import annotations

from analysis_system.services.relevance import accented

# `risk_notes.RISK_MARKS` nhận ra cụm này và đẩy dòng lên khối cảnh báo đầu
# trang. Sửa ở đây thì phải sửa ở đó.
MARK: str = "chua kiem duoc do lien quan"


def unchecked_note(question: str, count: int) -> str:
    """Một dòng nói lớp lọc đã không chạy, và vì sao.

    Args:
        question: câu người dùng hỏi.
        count: số kết luận được giữ mà chưa kiểm được.
    """
    head = (
        f"{count} kết luận dưới đây được GIỮ nhưng chưa kiểm được độ liên quan "
        f"với câu hỏi (chua kiem duoc do lien quan)"
    )
    if not accented(question):
        return (
            f"{head}: câu hỏi viết không dấu, mà thước đo không biết "
            '"diem thi" với "điểm thi" là một. Gõ lại câu hỏi có dấu thì lớp '
            "lọc này chạy được."
        )
    return f"{head}: câu hỏi và các kết luận khác nhau về dấu tiếng Việt."
