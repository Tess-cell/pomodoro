"""
effects.py - Những việc máy trạng thái báo ra ngoài sau mỗi sự kiện.

Engine trả về danh sách Effect; tầng ngoài đọc danh sách đó để ghi CSDL,
hiện cửa sổ... Engine không tự làm tác dụng phụ.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.states import State


@dataclass(frozen=True)
class SessionOpened:
    """Bắt đầu một chu kỳ focus -> cần INSERT vào bảng sessions."""

    cycle_index: int
    task_id: int | None
    mode: str  # 'strict' hoặc 'flexible'


@dataclass(frozen=True)
class SessionClosed:
    """Kết thúc một chu kỳ focus -> cần UPDATE sessions.ended_at.

    completed = True nếu chạy hết giờ (kể cả hết trong GRACE),
    False nếu người dùng bấm Dừng giữa chừng.
    """

    completed: bool


@dataclass(frozen=True)
class CycleFinished:
    """Một giai đoạn kết thúc -> giao diện hiện overlay thông báo."""

    from_state: State
    next_state: State
    pomodoros_done: int


@dataclass(frozen=True)
class NeedNewTask:
    """Việc hiện tại vừa hoàn thành khi đang FOCUS -> nhắc chọn việc mới.

    Đồng hồ KHÔNG dừng: người dùng dùng nốt thời gian còn lại để rà soát.
    """


@dataclass(frozen=True)
class OpenQuickNote:
    """Yêu cầu giao diện mở ô ghi chú nhanh để người dùng ghi bước đang làm dở khi hết focus."""


@dataclass(frozen=True)
class FocusExtended:
    """Đã cộng thêm thời gian focus trong GRACE (chế độ linh hoạt).

    seconds = số giây vừa cộng, total = tổng đã gia hạn trong chu kỳ này.
    """

    seconds: float
    total: float


# Kiểu hợp nhất của mọi effect, dùng cho type hint
Effect = (
    SessionOpened
    | SessionClosed
    | CycleFinished
    | NeedNewTask
    | OpenQuickNote
    | FocusExtended
)
