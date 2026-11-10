"""
controller.py - Cầu nối giữa Effect của TimerEngine và CSDL.

TimerEngine chỉ báo "vừa mở session" / "vừa đóng session". Lớp này là chỗ duy
nhất dịch những báo cáo đó thành INSERT/UPDATE.

Không import PySide6.
"""

from __future__ import annotations

import sqlite3

from core.effects import Effect, SessionClosed, SessionOpened
from db import sessions as sessions_repo


class SessionController:
    """Theo dõi session đang mở và ghi vào CSDL khi engine báo."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.session_id: int | None = None
        # Id của session vừa đóng gần nhất, để ghi chú nhanh gắn đúng chu kỳ.
        self.last_closed_session_id: int | None = None

    def apply(self, effects: list[Effect]) -> None:
        """Xử lý danh sách effect theo đúng thứ tự engine trả về."""
        for effect in effects:
            if isinstance(effect, SessionOpened):
                self.session_id = sessions_repo.open_session(
                    self.conn,
                    cycle_index=effect.cycle_index,
                    task_id=effect.task_id,
                    mode=effect.mode,
                )
            elif isinstance(effect, SessionClosed):
                if self.session_id is None:
                    # Đóng session chưa mở: bỏ qua, không làm sập app giữa chu kỳ.
                    continue
                sessions_repo.close_session(
                    self.conn,
                    self.session_id,
                    completed=effect.completed,
                )
                self.last_closed_session_id = self.session_id
                self.session_id = None
