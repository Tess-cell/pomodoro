"""
states.py - Tập trạng thái và sự kiện của bộ đếm.
"""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    """Các trạng thái của bộ đếm."""

    IDLE = "idle"                    # chưa chạy gì
    FOCUS = "focus"                  # đang tập trung
    GRACE = "grace"                  # gia hạn (chỉ ở chế độ linh hoạt)
    SHORT_BREAK = "short_break"      # nghỉ ngắn
    LONG_BREAK = "long_break"        # nghỉ dài
    PAUSED = "paused"                # tạm dừng, nhớ resume_state


class Event(str, Enum):
    """Sự kiện đưa vào máy trạng thái."""

    START = "start"                          # bắt đầu chu kỳ (chỉ từ IDLE)
    PAUSE = "pause"                          # tạm dừng
    RESUME = "resume"                        # chạy tiếp
    STOP = "stop"                            # dừng hẳn, về IDLE
    CONFIRM = "confirm"                      # người dùng bấm xác nhận overlay
    AUTO_CONFIRM = "auto_confirm"            # tự xác nhận sau N giây (chỉ nghỉ)
    TIME_UP = "time_up"                      # giai đoạn hiện tại hết giờ
    TASK_DONE = "task_done"                  # một công việc vừa được hoàn thành
    END_GRACE_NOW = "end_grace_now"          # bấm "Bắt đầu nghỉ" trong GRACE

    # Gia hạn trong GRACE ở chế độ linh hoạt: cộng thêm `seconds` giây nữa.
    # Chỉ nhận mốc hợp lệ (1/2 phút với nghỉ ngắn, 1..5 phút với nghỉ dài).
    EXTEND_FOCUS = "extend_focus"


# Các trạng thái mà đồng hồ đang đếm ngược về phía "tập trung kết thúc"
RUNNING_STATES = (State.FOCUS, State.GRACE)

# Hai giai đoạn nghỉ (dùng cho auto-confirm và cho ô ghi chú ghim)
BREAK_STATES = (State.SHORT_BREAK, State.LONG_BREAK)
