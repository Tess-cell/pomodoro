"""
sessions.py - Truy vấn bảng sessions.

Mỗi dòng = một chu kỳ focus. Giai đoạn nghỉ không tạo dòng nào.
Thời gian lưu dạng ISO-8601 UTC, khớp định dạng mặc định trong schema.sql.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Thời điểm hiện tại, dạng '2026-10-22T03:15:00Z'."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_session(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    """Đọc một dòng session theo id (dùng để hiển thị chu kỳ của ghi chú)."""
    return conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()


def open_session(
    conn: sqlite3.Connection,
    *,
    cycle_index: int,
    task_id: int | None = None,
    mode: str = "strict",
    started_at: str | None = None,
) -> int:
    """Tạo một chu kỳ focus mới, trả về id vừa tạo."""
    started = started_at or utc_now_iso()
    cursor = conn.execute(
        """
        INSERT INTO sessions (cycle_index, task_id, started_at, mode)
        VALUES (?, ?, ?, ?)
        """,
        (cycle_index, task_id, started, mode),
    )
    conn.commit()
    return int(cursor.lastrowid)


def close_session(
    conn: sqlite3.Connection,
    session_id: int,
    *,
    completed: bool,
    violations: int = 0,
    ended_at: str | None = None,
) -> None:
    """Ghi kết thúc cho một chu kỳ đang mở."""
    ended = ended_at or utc_now_iso()
    conn.execute(
        """
        UPDATE sessions
           SET ended_at = ?, completed = ?, violations = ?
         WHERE id = ?
        """,
        (ended, 1 if completed else 0, violations, session_id),
    )
    conn.commit()
