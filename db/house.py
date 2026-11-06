"""
db/house.py - Truy vấn và cập nhật bảng `house` trong SQLite.

Bảng `house` chỉ có đúng 1 dòng (id = 1), lưu trữ số tầng hiện tại của ngôi nhà Omnia.
Quy tắc: số tầng luôn nằm trong khoảng 0 đến config.MAX_FLOORS (9999).
"""

import sqlite3
import config


def get_house_floors(conn: sqlite3.Connection, *, commit: bool = True) -> int:
    """Lấy số tầng hiện tại của ngôi nhà.

    commit chỉ có tác dụng ở trường hy hữu phải tự tạo dòng id = 1.
    core/reward.py truyền commit=False để không cắt ngang transaction thưởng.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT floors FROM house WHERE id = 1")
    row = cursor.fetchone()
    if row is None:
        # Trường hợp hy hữu chưa có dòng id=1 thì khởi tạo mặc định 0
        cursor.execute("INSERT OR IGNORE INTO house (id, floors) VALUES (1, 0)")
        if commit:
            conn.commit()
        return 0
    return int(row[0])


def update_house_floors(
    conn: sqlite3.Connection,
    new_floors: int,
    *,
    commit: bool = True,
) -> int:
    """
    Cập nhật trực tiếp số tầng của ngôi nhà.
    Bảo vệ bằng clamp [0, config.MAX_FLOORS] trước khi ghi vào CSDL.

    commit=False dùng khi apply_task_rewards gộp nhà + thú + cây vào một
    transaction duy nhất (commit một lần ở cuối).
    """
    if not isinstance(new_floors, int):
        raise TypeError(f"Số tầng phải là số nguyên (int), nhận được: {type(new_floors)}")

    if new_floors < 0:
        raise ValueError(f"Số tầng không được âm: {new_floors}")

    clamped_floors = min(config.MAX_FLOORS, new_floors)
    cursor = conn.cursor()
    cursor.execute("UPDATE house SET floors = ? WHERE id = 1", (clamped_floors,))
    if commit:
        conn.commit()
    return clamped_floors


def set_house_floors(conn: sqlite3.Connection, floors: int) -> int:
    """Hàm tiện ích đặt số tầng (dùng cho test hoặc thiết lập lại)."""
    return update_house_floors(conn, floors)
