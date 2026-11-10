"""
tasks.py - Truy vấn và thao tác trên bảng tasks (CSDL SQLite).

Kiểm tra dữ liệu đầu vào trước khi ghi (độ khó trong khoảng
config.TASK_DIFFICULTY_MIN..MAX). Thời gian lưu theo ISO-8601 UTC.
"""

from __future__ import annotations

import sqlite3

import config
from db.sessions import utc_now_iso

VALID_STATUSES = ("todo", "doing", "done")


def validate_task_input(name: str, difficulty: int) -> tuple[str, int]:
    """Kiểm tra tính hợp lệ của tên và độ khó công việc.

    Trả về (tên_đã_strip, độ_khó_hợp_lệ). Ném ValueError nếu không hợp lệ.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Tên công việc không được để trống.")

    clean_name = name.strip()

    # bool là lớp con của int trong Python (isinstance(True, int) == True), phải loại trừ
    if isinstance(difficulty, bool) or not isinstance(difficulty, int):
        raise ValueError("Độ khó phải là số nguyên từ 1 đến 5.")

    if not (config.TASK_DIFFICULTY_MIN <= difficulty <= config.TASK_DIFFICULTY_MAX):
        raise ValueError(
            f"Độ khó phải nằm trong khoảng từ {config.TASK_DIFFICULTY_MIN} đến {config.TASK_DIFFICULTY_MAX}."
        )

    return clean_name, difficulty


def create_task(
    conn: sqlite3.Connection,
    *,
    name: str,
    description: str = "",
    difficulty: int = 1,
) -> int:
    """Tạo một công việc mới, mặc định trạng thái 'todo'. Trả về task_id."""
    clean_name, clean_diff = validate_task_input(name, difficulty)
    desc = description.strip() if description else None
    created = utc_now_iso()

    cursor = conn.execute(
        """
        INSERT INTO tasks (name, description, difficulty, status, created_at)
        VALUES (?, ?, ?, 'todo', ?)
        """,
        (clean_name, desc, clean_diff, created),
    )
    conn.commit()
    return int(cursor.lastrowid)


def get_task(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row | None:
    """Lấy thông tin một công việc theo id. Trả về None nếu không tìm thấy."""
    cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return cursor.fetchone()


def list_tasks(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    """Liệt kê công việc.

    Nếu có status ('todo', 'doing', 'done'): chỉ lấy việc có status đó.
    Nếu status = None: lấy tất cả, ưu tiên việc chưa làm (doing -> todo -> done),
    mới nhất lên đầu.
    """
    if status is not None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Trạng thái '{status}' không hợp lệ.")
        cursor = conn.execute(
            """
            SELECT * FROM tasks
             WHERE status = ?
             ORDER BY id DESC
            """,
            (status,),
        )
    else:
        cursor = conn.execute(
            """
            SELECT * FROM tasks
             ORDER BY CASE status
                 WHEN 'doing' THEN 1
                 WHEN 'todo'  THEN 2
                 ELSE 3
             END, id DESC
            """
        )
    return cursor.fetchall()


def update_task(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    difficulty: int | None = None,
    status: str | None = None,
) -> None:
    """Cập nhật thông tin công việc. Chỉ cập nhật các trường được truyền."""
    current = get_task(conn, task_id)
    if current is None:
        raise ValueError(f"Không tìm thấy công việc với id {task_id}.")

    new_name = current["name"] if name is None else name
    new_diff = current["difficulty"] if difficulty is None else difficulty
    new_desc = current["description"] if description is None else (description.strip() if description else None)
    new_status = current["status"] if status is None else status

    clean_name, clean_diff = validate_task_input(new_name, new_diff)

    if new_status not in VALID_STATUSES:
        raise ValueError(f"Trạng thái '{new_status}' không hợp lệ.")

    conn.execute(
        """
        UPDATE tasks
           SET name = ?, description = ?, difficulty = ?, status = ?
         WHERE id = ?
        """,
        (clean_name, new_desc, clean_diff, new_status, task_id),
    )
    conn.commit()


def complete_task(
    conn: sqlite3.Connection,
    task_id: int,
    completed_at: str | None = None,
) -> None:
    """Đánh dấu công việc hoàn thành (status = 'done', completed_at = ISO UTC)."""
    current = get_task(conn, task_id)
    if current is None:
        raise ValueError(f"Không tìm thấy công việc với id {task_id}.")

    ended = completed_at or utc_now_iso()
    conn.execute(
        """
        UPDATE tasks
           SET status = 'done', completed_at = ?
         WHERE id = ?
        """,
        (ended, task_id),
    )
    conn.commit()


def delete_task(conn: sqlite3.Connection, task_id: int) -> None:
    """Xóa một công việc.

    Theo schema.sql, khóa ngoại sessions(task_id) có ON DELETE SET NULL,
    nên các session liên quan sẽ tự động chuyển task_id thành NULL mà không bị xóa.
    """
    current = get_task(conn, task_id)
    if current is None:
        raise ValueError(f"Không tìm thấy công việc với id {task_id}.")

    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
