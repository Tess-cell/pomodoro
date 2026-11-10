"""
notes.py - Truy vấn bảng notes (ghi chú nhanh, gắn việc/chu kỳ).

Thời gian tạo do schema.sql tự điền (ISO-8601 UTC).
"""

from __future__ import annotations

import sqlite3


def _validate_content(content: str, *, allow_empty: bool) -> str:
    if not isinstance(content, str):
        raise TypeError(f"Nội dung ghi chú phải là chuỗi, nhận được: {type(content)}")
    if not allow_empty and not content.strip():
        raise ValueError("Nội dung ghi chú không được để trống.")
    return content


def create_note(
    conn: sqlite3.Connection,
    content: str,
    *,
    task_id: int | None = None,
    session_id: int | None = None,
    commit: bool = True,
) -> int:
    """Tạo ghi chú mới, trả về id. Nội dung rỗng bị từ chối."""
    clean = _validate_content(content, allow_empty=False)
    cursor = conn.execute(
        """
        INSERT INTO notes (content, task_id, session_id)
        VALUES (?, ?, ?)
        """,
        (clean, task_id, session_id),
    )
    if commit:
        conn.commit()
    return int(cursor.lastrowid)


def get_note(conn: sqlite3.Connection, note_id: int) -> sqlite3.Row | None:
    """Đọc một ghi chú theo id, None nếu không tồn tại."""
    return conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()


def update_note(
    conn: sqlite3.Connection,
    note_id: int,
    content: str,
    *,
    commit: bool = True,
) -> None:
    """Cập nhật nội dung ghi chú. Cho phép xóa hết nội dung (chuỗi rỗng)."""
    clean = _validate_content(content, allow_empty=True)
    cursor = conn.execute(
        "UPDATE notes SET content = ? WHERE id = ?", (clean, note_id)
    )
    if cursor.rowcount == 0:
        raise ValueError(f"Không tìm thấy ghi chú với id {note_id}.")
    if commit:
        conn.commit()


def list_notes(
    conn: sqlite3.Connection,
    *,
    task_id: int | None = None,
    session_id: int | None = None,
) -> list[sqlite3.Row]:
    """Liệt kê ghi chú mới nhất trước; lọc theo task_id và/hoặc session_id."""
    sql = "SELECT * FROM notes"
    conditions: list[str] = []
    params: list[int] = []

    if task_id is not None:
        conditions.append("task_id = ?")
        params.append(task_id)
    if session_id is not None:
        conditions.append("session_id = ?")
        params.append(session_id)

    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY id DESC"

    return conn.execute(sql, params).fetchall()


def delete_note(conn: sqlite3.Connection, note_id: int, *, commit: bool = True) -> None:
    """Xóa một ghi chú."""
    cursor = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    if cursor.rowcount == 0:
        raise ValueError(f"Không tìm thấy ghi chú với id {note_id}.")
    if commit:
        conn.commit()
