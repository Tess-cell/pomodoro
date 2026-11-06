"""
creatures.py - Truy vấn bảng creatures (thú ảo và cây trồng của Omnia).

Quy ước dữ liệu:
  - kind: 'pet' (thú ảo) hoặc 'plant' (cây trồng).
  - species: khoá loài, ví dụ 'cat', 'oak' (UI tra sprite trong config.py).
  - stage: 1 = sinh ra, 2 = lớn lên, 3 = trưởng thành.
  - growth: điểm chăm sóc tích luỹ, không bao giờ giảm.
  - is_active: 1 = đang nuôi; mỗi kind tối đa 1 con (partial unique index).
  * Từ schema v3: sinh vật stage = 3 có thể được bật lại (nuôi tiếp trong
    bộ sưu tập) và tiếp tục nhận điểm, không giới hạn giai đoạn.

Về transaction:
  Mọi hàm ghi nhận tham số `commit` (mặc định True). core/reward.py truyền
  commit=False để gộp nhà + thú + cây vào một transaction duy nhất, rồi chỉ
  commit một lần ở cuối apply_task_rewards().

Không import PySide6: tầng này test được bằng pytest.
"""

from __future__ import annotations

import sqlite3

VALID_KINDS = ("pet", "plant")
ADULT_STAGE = 3


def validate_creature_input(kind: str, species: str, name: str) -> tuple[str, str, str]:
    """Kiểm tra kind/species/name. Trả về bộ ba đã strip. Ném ValueError nếu sai."""
    if kind not in VALID_KINDS:
        raise ValueError(f"Loại sinh vật '{kind}' không hợp lệ (chỉ nhận 'pet' hoặc 'plant').")

    if not isinstance(species, str) or not species.strip():
        raise ValueError("Loài sinh vật không được để trống.")

    if not isinstance(name, str) or not name.strip():
        raise ValueError("Tên sinh vật không được để trống.")

    return kind, species.strip(), name.strip()


def create_creature(
    conn: sqlite3.Connection,
    *,
    kind: str,
    species: str,
    name: str,
    activate: bool = True,
    commit: bool = True,
) -> int:
    """Tạo sinh vật mới, trả về id.

    activate=True (mặc định): đưa vào ô nuôi ngay. Nếu ô đang có sinh vật khác
    cùng kind, sinh vật cũ chỉ bị tắt is_active (giữ nguyên growth/stage) để
    người dùng có thể quay lại nuôi tiếp.

    activate=False: thêm vào danh sách đang lớn mà không đổi sinh vật đang nuôi.
    """
    kind, species, name = validate_creature_input(kind, species, name)

    if activate:
        conn.execute(
            "UPDATE creatures SET is_active = 0 WHERE kind = ? AND is_active = 1",
            (kind,),
        )

    cursor = conn.execute(
        """
        INSERT INTO creatures (kind, species, name, is_active)
        VALUES (?, ?, ?, ?)
        """,
        (kind, species, name, 1 if activate else 0),
    )
    if commit:
        conn.commit()
    return int(cursor.lastrowid)


def get_creature(conn: sqlite3.Connection, creature_id: int) -> sqlite3.Row | None:
    """Đọc một sinh vật theo id, None nếu không tồn tại."""
    return conn.execute(
        "SELECT * FROM creatures WHERE id = ?", (creature_id,)
    ).fetchone()


def list_creatures(conn: sqlite3.Connection, kind: str | None = None) -> list[sqlite3.Row]:
    """Liệt kê sinh vật (mới nhất lên đầu). Lọc theo kind nếu được truyền."""
    if kind is not None:
        if kind not in VALID_KINDS:
            raise ValueError(f"Loại sinh vật '{kind}' không hợp lệ.")
        rows = conn.execute(
            "SELECT * FROM creatures WHERE kind = ? ORDER BY id DESC", (kind,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM creatures ORDER BY id DESC").fetchall()
    return rows


def get_active_creature(conn: sqlite3.Connection, kind: str) -> sqlite3.Row | None:
    """Sinh vật đang nuôi của một kind (tối đa 1 con), None nếu ô đang trống."""
    if kind not in VALID_KINDS:
        raise ValueError(f"Loại sinh vật '{kind}' không hợp lệ.")
    return conn.execute(
        "SELECT * FROM creatures WHERE kind = ? AND is_active = 1", (kind,)
    ).fetchone()


def list_growing(conn: sqlite3.Connection, kind: str | None = None) -> list[sqlite3.Row]:
    """Các sinh vật chưa trưởng thành (stage 1-2), dùng cho combo đổi sinh vật."""
    if kind is not None:
        rows = conn.execute(
            "SELECT * FROM creatures WHERE kind = ? AND stage < ? ORDER BY id DESC",
            (kind, ADULT_STAGE),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM creatures WHERE stage < ? ORDER BY kind, id DESC",
            (ADULT_STAGE,),
        ).fetchall()
    return rows


def list_collection(conn: sqlite3.Connection, kind: str | None = None) -> list[sqlite3.Row]:
    """Bộ sưu tập: các sinh vật đã trưởng thành (stage = 3)."""
    if kind is not None:
        rows = conn.execute(
            "SELECT * FROM creatures WHERE kind = ? AND stage = ? ORDER BY id DESC",
            (kind, ADULT_STAGE),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM creatures WHERE stage = ? ORDER BY kind, id DESC",
            (ADULT_STAGE,),
        ).fetchall()
    return rows


def activate_creature(
    conn: sqlite3.Connection,
    creature_id: int,
    *,
    commit: bool = True,
) -> None:
    """Đưa một sinh vật vào ô nuôi của kind tương ứng.

    Sinh vật đang nuôi khác (cùng kind) bị tắt is_active nhưng GIỮ NGUYÊN
    growth/stage, nên có thể quay lại nuôi tiếp sau này.
    Sinh vật đã trưởng thành (stage 3) VẪN được bật lại để nuôi tiếp.
    Ném ValueError nếu id không tồn tại.
    """
    row = get_creature(conn, creature_id)
    if row is None:
        raise ValueError(f"Không tìm thấy sinh vật với id {creature_id}.")

    kind = row["kind"]
    conn.execute(
        "UPDATE creatures SET is_active = 0"
        " WHERE kind = ? AND is_active = 1 AND id != ?",
        (kind, creature_id),
    )
    conn.execute(
        "UPDATE creatures SET is_active = 1 WHERE id = ?", (creature_id,)
    )
    if commit:
        conn.commit()


def delete_creature(
    conn: sqlite3.Connection,
    creature_id: int,
    *,
    commit: bool = True,
) -> None:
    """Thả tự do: xóa hẳn sinh vật khỏi CSDL.

    Nếu là con đang nuôi thì chỉ cần xóa — partial unique index tự giải phóng
    ô nuôi (điều kiện `WHERE is_active = 1` không còn dòng nào).
    Ném ValueError nếu id không tồn tại.
    """
    cursor = conn.execute("DELETE FROM creatures WHERE id = ?", (creature_id,))
    if cursor.rowcount == 0:
        raise ValueError(f"Không tìm thấy sinh vật với id {creature_id}.")
    if commit:
        conn.commit()


def update_growth_stage(
    conn: sqlite3.Connection,
    creature_id: int,
    *,
    growth: int,
    stage: int,
    is_active: bool,
    commit: bool = True,
) -> None:
    """Ghi growth + stage + is_active trong ĐÚNG MỘT câu UPDATE.

    Cho phép stage = 3 đi kèm is_active = True (nuôi tiếp sau trưởng thành).
    """
    if isinstance(growth, bool) or not isinstance(growth, int) or growth < 0:
        raise ValueError(f"Điểm chăm sóc phải là số nguyên không âm, nhận được: {growth!r}")
    if isinstance(stage, bool) or stage not in (1, 2, 3):
        raise ValueError(f"Giai đoạn phải là 1, 2 hoặc 3, nhận được: {stage!r}")

    cursor = conn.execute(
        """
        UPDATE creatures
           SET growth = ?, stage = ?, is_active = ?
         WHERE id = ?
        """,
        (growth, stage, 1 if is_active else 0, creature_id),
    )
    if cursor.rowcount == 0:
        raise ValueError(f"Không tìm thấy sinh vật với id {creature_id}.")
    if commit:
        conn.commit()
