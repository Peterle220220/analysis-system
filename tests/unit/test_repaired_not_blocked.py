"""Sua nhe va loai bo la hai viec khac nhau, nen phai nam hai cho khac nhau.

Chu he thong doc man hinh va viet: "UI phoi bay ro ly do no tram 3 ket luan (do
LLM go thua dau %)". Roi de nghi noi long lop loc dinh dang de "cuu vot cac chi
so dung thay vi giet nham".

Nhung hai trong ba dong do KHONG bi tram. Chung ghi "da bo don vi go tay" - tuc
la he thong DA SUA va GIU LAI ket luan. Lop loc do von da nhe san.

Cai hong la trinh bay: ghi chu sua nhe nam chung danh sach voi cac ket luan bi
loai that, nen nguoi doc dem ca cum. Va tu mot cach doc sai, mot de nghi noi
long mot lop bao ve.

Giao dien HTML cu da bo (plans/refactor-ddd.md); lop JSON cho giao dien Next la noi
tach hai danh sach, nen test kiem o do.
"""

from __future__ import annotations

from analysis_system.domains.ai_planner.findings import was_repaired
from analysis_system.models.agents import ClaimEvidence, ManagerAnswer
from analysis_system.web.view import manager_answer

# Nguyen van hai dong da hien ra tren man hinh cua chu he thong.
DA_SUA = (
    "finding[0]: da bo don vi go tay ngay sau placeholder - he thong tu chen don vi, "
    "viet them se thanh '40.24 % %'."
)
BI_LOAI = (
    "finding[6]: cau nhan dinh khong tro toi chi so nao - khong co gi de kiem chung; "
    "metric_keys khai bao ['campaign.effect_size.by.y'] khong khop voi cac placeholder"
)

TRA_LOI = ManagerAnswer(
    question="Cau hoi",
    claims=(ClaimEvidence(claim="Mot ket luan.", metric_keys=("a.mean",)),),
    rejected=(DA_SUA, DA_SUA, BI_LOAI),
)


def test_a_repair_note_is_told_apart_from_a_rejection() -> None:
    assert was_repaired(DA_SUA)
    assert not was_repaired(BI_LOAI)


def test_a_repaired_claim_is_not_counted_as_blocked() -> None:
    """Day la cho da lam chu he thong doc nham: 2 dong sua nhe bi dem la tram."""
    assert manager_answer(TRA_LOI)["blocked"] == [BI_LOAI]


def test_the_repairs_are_still_carried_somewhere() -> None:
    """Bo trong im lang la dung thu du an nay tranh."""
    assert manager_answer(TRA_LOI)["repaired"] == [DA_SUA, DA_SUA]


def test_an_answer_with_nothing_rejected_carries_neither() -> None:
    payload = manager_answer(ManagerAnswer(question="Cau hoi"))
    assert payload["blocked"] == []
    assert payload["repaired"] == []
