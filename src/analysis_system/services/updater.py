"""Lấy code mới từ Git, ngay trên máy chủ, không cần SSH vào.

Hệ thống chạy trên một máy nhỏ đặt ở nhà. Mỗi lần sửa xong lại phải SSH vào,
`git pull`, rồi khởi động lại dịch vụ — ba bước cho một việc, và ba chỗ để gõ
nhầm lúc nửa đêm.

Nên có một nút. Nhưng một nút chạy được code mới trên máy chủ là **một cửa để
chạy code từ xa**, nên nó phải hẹp hơn mọi thứ khác trong dự án này:

* **Không nhận lệnh từ người dùng.** Không có ô nhập nhánh, nhập remote, nhập
  gì cả. Chỉ đúng nhánh đang theo dõi của kho đang chạy.
* **Chỉ tua tới.** `--ff-only`: lịch sử rẽ nhánh thì dừng, không tự trộn. Một
  lần trộn hỏng trên máy chủ là một dịch vụ chết mà không ai đang ngồi trước
  màn hình.
* **Cây phải sạch.** Có sửa tay trên máy chủ thì dừng và nói ra. Ghi đè lên
  thay đổi của người khác là chuyện không lùi được, và ở đây không ai đứng
  cạnh để hỏi.
* **Đọc trước khi ghi.** Xem có gì mới là một việc; áp dụng nó là việc khác,
  và việc thứ hai cần một cú bấm riêng.

Không dùng `git pull`. Nó là `fetch` cộng `merge` gộp làm một, và cái `merge`
kia mới là chỗ mọi thứ hỏng — tách ra thì mỗi bước hỏng ở đâu nói được ở đó.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

# Mạng chậm thì thà báo chậm còn hơn treo trang. Ba mươi giây là quá đủ cho một
# lần fetch của kho này.
NETWORK_TIMEOUT: Final[int] = 30
LOCAL_TIMEOUT: Final[int] = 15


@dataclass(frozen=True)
class Version:
    """Bản đang chạy."""

    sha: str = ""
    subject: str = ""
    when: str = ""
    branch: str = ""
    dirty: bool = False


@dataclass(frozen=True)
class Update:
    """Có gì mới ở kho từ xa."""

    behind: int = 0
    commits: tuple[str, ...] = ()
    # Rỗng khi mọi thứ bình thường. Có chữ nghĩa là không kiểm được, và **không
    # kiểm được** khác hẳn **không có bản mới**.
    problem: str = ""

    @property
    def available(self) -> bool:
        return self.behind > 0 and not self.problem


@dataclass(frozen=True)
class Applied:
    """Kết quả một lần cập nhật."""

    moved: bool = False
    was: str = ""
    now: str = ""
    problem: str = ""
    steps: tuple[str, ...] = field(default_factory=tuple)


def _git(repo: Path, *args: str, timeout: int = LOCAL_TIMEOUT) -> tuple[int, str]:
    """Chạy một lệnh git trong kho này. Không bao giờ nhận lệnh từ bên ngoài."""
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    return done.returncode, (done.stdout + done.stderr).strip()


def current(repo: Path) -> Version:
    """Bản đang chạy trên máy này."""
    code, line = _git(repo, "log", "-1", "--format=%h%x1f%s%x1f%cd", "--date=format:%d/%m %H:%M")
    if code != 0:
        return Version()
    parts = line.split("\x1f")
    _, branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _, changed = _git(repo, "status", "--porcelain")
    return Version(
        sha=parts[0] if parts else "",
        subject=parts[1] if len(parts) > 1 else "",
        when=parts[2] if len(parts) > 2 else "",
        branch=branch,
        dirty=bool(changed.strip()),
    )


def check(repo: Path) -> Update:
    """Kho từ xa có gì mới không.

    Chỉ `fetch` — không đụng gì tới cây làm việc. Gọi bao nhiêu lần cũng an toàn.
    """
    code, said = _git(repo, "fetch", "--quiet", timeout=NETWORK_TIMEOUT)
    if code != 0:
        return Update(problem=f"khong ket noi duoc toi kho: {said[:200]}")

    code, upstream = _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}")
    if code != 0:
        return Update(problem="nhanh nay chua theo doi nhanh nao tren kho tu xa")

    code, listing = _git(repo, "log", "--oneline", f"HEAD..{upstream}")
    if code != 0:
        return Update(problem=f"khong doc duoc lich su: {listing[:200]}")

    lines = tuple(line for line in listing.splitlines() if line.strip())
    return Update(behind=len(lines), commits=lines)


def apply(repo: Path) -> Applied:
    """Lấy code mới về, chỉ khi tua tới được.

    Returns:
        Kết quả, kèm từng bước đã làm. Hỏng thì `problem` có chữ và **không có
        gì bị đổi** — mọi lớp chặn đều đứng trước lệnh ghi đầu tiên.
    """
    before = current(repo)
    if not before.sha:
        return Applied(problem="khong doc duoc kho git o day")
    if before.dirty:
        return Applied(
            was=before.sha,
            problem=(
                "cay lam viec tren may chu dang co thay doi chua luu. "
                "Cap nhat se ghi de len chung, nen dung lai o day."
            ),
        )

    steps: list[str] = []
    code, said = _git(repo, "fetch", "--quiet", timeout=NETWORK_TIMEOUT)
    if code != 0:
        return Applied(was=before.sha, problem=f"khong ket noi duoc toi kho: {said[:200]}")
    steps.append("fetch xong")

    code, upstream = _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}")
    if code != 0:
        return Applied(was=before.sha, problem="nhanh nay chua theo doi nhanh nao tren kho tu xa")

    # `--ff-only`: lich su re nhanh thi dung, khong tu tron. Mot lan tron hong
    # tren may chu la mot dich vu chet ma khong ai dang ngoi truoc man hinh.
    code, said = _git(repo, "merge", "--ff-only", upstream)
    if code != 0:
        return Applied(
            was=before.sha,
            problem=(
                "khong tua toi duoc - lich su tren may chu da re khoi kho tu xa. "
                f"Can vao xem bang tay. Git noi: {said[:200]}"
            ),
            steps=tuple(steps),
        )
    steps.append(said.splitlines()[0] if said else "da tua toi")

    after = current(repo)
    return Applied(
        moved=after.sha != before.sha,
        was=before.sha,
        now=after.sha,
        steps=tuple(steps),
    )


# Lenh khoi dong lai dich vu, doc tu moi truong. De trong thi khong khoi dong
# lai gi ca va nguoi dung duoc bao tu lam - thua hon la doan mot lenh systemd
# co the khong ton tai tren may do.
RESTART_ENV: Final[str] = "ASYS_RESTART_CMD"


def repo_root() -> Path:
    """Thư mục kho git của chính code đang chạy."""
    return Path(__file__).resolve().parents[3]


def _sha_at_start() -> str:
    """Ma commit lúc tiến trình này khởi động.

    Đọc **một lần**, ngay khi module được nạp — tức là lúc tiến trình bắt đầu.
    Sau đó `git pull` có đổi thư mục thế nào thì giá trị này vẫn là bản code
    đang thật sự nằm trong bộ nhớ.
    """
    try:
        code, said = _git(repo_root(), "rev-parse", "--short", "HEAD")
    except OSError:
        return ""
    return said.strip() if code == 0 else ""


# Doc mot lan luc nap module. Day la thu duy nhat noi dung duoc "ban dang chay":
# moi cach khac deu doc thu muc, ma thu muc thi da doi tu luc bam Cap nhat.
LOADED: Final[str] = _sha_at_start()


def stale(repo: Path) -> str:
    """Code trên đĩa đã mới hơn code đang chạy chưa.

    Trang Hệ thống từng ghi *"Bản đang chạy 5e1d518"* và *"Đang chạy bản mới
    nhất"* trong khi tiến trình vẫn nạp code cũ — vì cả hai câu đều đọc từ
    **thư mục**, không phải từ bộ nhớ. `git pull` đổi thư mục ngay lập tức, còn
    tiến trình thì chỉ đổi khi được khởi động lại.

    Chủ hệ thống bấm cập nhật, đọc thấy "đang chạy bản mới nhất", rồi không
    thấy tính năng đâu — và không có gì trên màn hình giải thích được.

    Returns:
        Câu cảnh báo, hoặc rỗng. Rỗng là trường hợp thường gặp.
    """
    code, head = _git(repo, "rev-parse", "--short", "HEAD")
    if code != 0 or not LOADED or not head.strip():
        # Khong doc duoc thi im lang: doan bua o day se keu oan moi lan chay.
        return ""
    if head.strip() == LOADED:
        return ""
    return (
        f"Code trong thư mục đã là {head.strip()}, nhưng tiến trình đang chạy "
        f"vẫn là {LOADED}. Phải khởi động lại thì bản mới mới có hiệu lực."
    )


def restart_after_reply(command: str = "") -> str:
    """Hẹn khởi động lại dịch vụ, **sau** khi trang này đã trả lời xong.

    Khởi động lại giết chính tiến trình đang trả lời, nên nếu gọi thẳng thì
    trình duyệt nhận một kết nối đứt thay vì một trang nói việc đã xong.

    Returns:
        Một câu cho người đọc. Không có lệnh nào được khai thì nói thẳng là
        phải khởi động lại bằng tay — im lặng ở đây sẽ để lại một dịch vụ vẫn
        chạy code cũ trong khi trang báo đã cập nhật.
    """
    import os
    import shlex

    wanted = command or os.environ.get(RESTART_ENV, "")
    if not wanted.strip():
        return (
            "Đã lấy code mới. Dịch vụ VẪN đang chạy bản cũ cho tới khi được "
            "khởi động lại, chạy 'systemctl --user restart asys' trên máy chủ."
        )
    try:
        subprocess.Popen(  # noqa: S603 - lenh den tu cau hinh may chu, khong tu request
            ["sh", "-c", f"sleep 1; {wanted}"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        return f"Đã lấy code mới, nhưng không khởi động lại được: {error}"
    return (
        f"Đã lấy code mới. Đang khởi động lại ({shlex.quote(wanted)}), "
        "đợi vài giây rồi tải lại trang."
    )
