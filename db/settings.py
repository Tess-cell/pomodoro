"""
settings.py - Đọc/ghi cấu hình dạng key-value trong bảng `settings`.

Lưu dạng key-value nên thêm cấu hình mới không cần đổi cấu trúc CSDL.

Các khoá đang dùng:
  - active_omnia: 'house' | 'pet' | 'plant' - Omnia nhận tiến trình khi
    hoàn thành công việc.
"""

from __future__ import annotations

import sqlite3

import config


def get_setting(
    conn: sqlite3.Connection,
    key: str,
    default: str | None = None,
) -> str | None:
    """Đọc một giá trị cấu hình; trả về `default` nếu chưa có."""
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return default if row is None else row["value"]


def set_setting(
    conn: sqlite3.Connection,
    key: str,
    value: str,
    *,
    commit: bool = True,
) -> None:
    """Ghi (hoặc ghi đè) một giá trị cấu hình."""
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Tên cấu hình không được để trống.")
    if not isinstance(value, str):
        raise TypeError(f"Giá trị cấu hình phải là chuỗi, nhận được: {type(value)}")

    conn.execute(
        """
        INSERT INTO settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    if commit:
        conn.commit()


def get_active_omnia(conn: sqlite3.Connection) -> str:
    """Omnia đang nhận tiến trình: 'house', 'pet' hoặc 'plant'."""
    value = get_setting(conn, config.SETTING_ACTIVE_OMNIA, config.DEFAULT_OMNIA_TARGET)
    if value not in config.OMNIA_TARGETS:
        return config.DEFAULT_OMNIA_TARGET
    return value


def set_active_omnia(
    conn: sqlite3.Connection,
    target: str,
    *,
    commit: bool = True,
) -> str:
    """Đổi Omnia nhận tiến trình. Ném ValueError nếu target không hợp lệ."""
    if target not in config.OMNIA_TARGETS:
        raise ValueError(
            f"Omnia '{target}' không hợp lệ (chỉ nhận {config.OMNIA_TARGETS})."
        )
    set_setting(conn, config.SETTING_ACTIVE_OMNIA, target, commit=commit)
    return target


def get_bool_setting(
    conn: sqlite3.Connection,
    key: str,
    default: bool,
) -> bool:
    """Đọc một cấu hình kiểu bật/tắt. Giá trị lạ (hoặc chưa có) -> `default`."""
    value = get_setting(conn, key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def set_bool_setting(
    conn: sqlite3.Connection,
    key: str,
    value: bool,
    *,
    commit: bool = True,
) -> bool:
    """Ghi cấu hình bật/tắt dưới dạng '1'/'0'. Trả lại giá trị đã ghi."""
    set_setting(conn, key, "1" if value else "0", commit=commit)
    return bool(value)


def get_strict_mode(conn: sqlite3.Connection) -> bool:
    """Chế độ Nghiêm ngặt (True) hay Linh hoạt (False).

    Chưa có trong settings thì dùng `config.STRICT_MODE`; giá trị lạ cũng vậy.
    """
    value = get_setting(conn, config.SETTING_STRICT_MODE)
    if value is None:
        return config.STRICT_MODE
    return value.strip().lower() in ("1", "true", "yes", "on")


def set_strict_mode(
    conn: sqlite3.Connection,
    strict: bool,
    *,
    commit: bool = True,
) -> bool:
    """Lưu chế độ Nghiêm ngặt/Linh hoạt dưới dạng '1'/'0'."""
    set_setting(conn, config.SETTING_STRICT_MODE, "1" if strict else "0", commit=commit)
    return bool(strict)


def get_int_setting(
    conn: sqlite3.Connection,
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    """Đọc một cấu hình số nguyên, ép về khoảng [minimum, maximum].

    Chưa lưu hoặc giá trị không phải số -> `default`. Giá trị ngoài khoảng bị
    kẹp lại thay vì ném lỗi (dữ liệu cũ/hỏng không làm app không mở được).
    """
    value = get_setting(conn, key)
    if value is None:
        return default
    try:
        number = int(value.strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def set_int_setting(
    conn: sqlite3.Connection,
    key: str,
    value: int,
    *,
    minimum: int,
    maximum: int,
    commit: bool = True,
) -> int:
    """Ghi cấu hình số nguyên (đã kẹp khoảng). Trả lại giá trị đã ghi."""
    number = max(minimum, min(maximum, int(value)))
    set_setting(conn, key, str(number), commit=commit)
    return number


def get_duration_minutes(
    conn: sqlite3.Connection,
    key: str,
    default_minutes: int,
) -> int:
    """Đọc thời lượng (phút) của một giai đoạn chu kỳ."""
    limits = config.DURATION_LIMITS_MINUTES.get(key)
    if limits is None:
        raise ValueError(f"Không có cấu hình thời lượng cho key '{key}'.")
    return get_int_setting(
        conn, key, default_minutes, minimum=limits[0], maximum=limits[1]
    )


def set_duration_minutes(
    conn: sqlite3.Connection,
    key: str,
    minutes: int,
    *,
    commit: bool = True,
) -> int:
    """Lưu thời lượng (phút) của một giai đoạn chu kỳ."""
    limits = config.DURATION_LIMITS_MINUTES.get(key)
    if limits is None:
        raise ValueError(f"Không có cấu hình thời lượng cho key '{key}'.")
    return set_int_setting(
        conn, key, minutes, minimum=limits[0], maximum=limits[1], commit=commit
    )


def get_pinned_note_autohide(conn: sqlite3.Connection) -> bool:
    """Ghi chú ghim có tự ẩn khi hết giờ nghỉ không (mặc định: có)."""
    return get_bool_setting(
        conn,
        config.SETTING_PINNED_NOTE_AUTOHIDE,
        config.PINNED_NOTE_AUTOHIDE_DEFAULT,
    )


def set_pinned_note_autohide(
    conn: sqlite3.Connection,
    value: bool,
    *,
    commit: bool = True,
) -> bool:
    """Bật/tắt tự ẩn ghi chú ghim khi hết giờ nghỉ."""
    return set_bool_setting(
        conn, config.SETTING_PINNED_NOTE_AUTOHIDE, value, commit=commit
    )
