"""
database.py - Mở kết nối và khởi tạo CSDL.

Không import PySide6: tầng này test được bằng pytest mà không cần giao diện.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Phiên bản schema hiện tại (khớp PRAGMA user_version trong schema.sql).
# V3: cho phép sinh vật trưởng thành (stage = 3) tiếp tục is_active = 1.
SCHEMA_VERSION = 3

# DDL mới nhất của bảng creatures, dùng riêng cho migration v1/v2 -> v3.
# Lưu ý: phải đồng bộ với db/schema.sql. Không thể dùng CREATE TABLE IF NOT EXISTS
# trong schema.sql để sửa bảng đã tồn tại, nên migration tạo bảng mới rồi đổi tên.
_CREATURES_V3_DDL = """
CREATE TABLE creatures_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT    NOT NULL CHECK (kind IN ('pet', 'plant')),
    species    TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    stage      INTEGER NOT NULL DEFAULT 1 CHECK (stage BETWEEN 1 AND 3),
    growth     INTEGER NOT NULL DEFAULT 0 CHECK (growth >= 0),
    is_active  INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
)
"""

# Danh sách bảng, dùng cho test và cho bước kiểm tra toàn vẹn sau này
TABLES = (
    "tasks",
    "sessions",
    "notes",
    "creatures",
    "house",
    "blocked_apps",
    "settings",
)


def connect(db_path: str | Path = config.DB_PATH) -> sqlite3.Connection:
    """Mở kết nối tới CSDL, tạo thư mục cha nếu cần.

    db_path có thể là ':memory:' (dùng trong test) hoặc đường dẫn file.
    """
    path_str = str(db_path)
    is_memory = path_str == ":memory:"

    if not is_memory:
        Path(path_str).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path_str)
    # Cho phép truy cập cột bằng tên: row["floors"] thay vì row[1]
    conn.row_factory = sqlite3.Row
    # Bắt buộc: SQLite mặc định KHÔNG kiểm tra foreign key
    conn.execute("PRAGMA foreign_keys = ON")

    if not is_memory:
        # WAL: đọc/ghi song song tốt hơn, ít bị khoá khi có nhiều cửa sổ
        conn.execute("PRAGMA journal_mode = WAL")

    return conn


def init_db(db_path: str | Path = config.DB_PATH) -> sqlite3.Connection:
    """Tạo CSDL nếu chưa có, migrate nếu cần, đóng session mồ côi.

    Thứ tự cố ý:
      1. migrate_db() chạy TRƯỚC schema.sql, vì file này dùng
         CREATE TABLE IF NOT EXISTS (không sửa được bảng đã tồn tại);
      2. schema.sql tạo các bảng còn thiếu và đặt PRAGMA user_version = 2.
    """
    conn = connect(db_path)
    migrate_db(conn)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    close_orphan_sessions(conn)
    conn.commit()
    return conn


def get_user_version(conn: sqlite3.Connection) -> int:
    """Đọc PRAGMA user_version (0 = CSDL mới tinh, chưa có schema)."""
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def migrate_db(conn: sqlite3.Connection) -> int:
    """Nâng cấp CSDL cũ lên SCHEMA_VERSION. Trả về version đọc được trước khi migrate."""
    version = get_user_version(conn)
    if version in (1, 2):
        _migrate_creatures_to_v3(conn)
    return version


def _migrate_creatures_to_v3(conn: sqlite3.Connection) -> None:
    """Tạo lại bảng creatures v3 (bỏ CHECK cấm stage 3 active), giữ dữ liệu.

    Chỉ đụng bảng creatures; các bảng khác không bị chạm.
    Toàn bộ nằm trong MỘT transaction: lỗi giữa chừng thì rollback, bảng cũ
    và user_version cũ được giữ nguyên để lần khởi động sau thử lại.
    """
    conn.execute("BEGIN")
    try:
        conn.execute(_CREATURES_V3_DDL)
        conn.execute(
            """
            INSERT INTO creatures_new
                (id, kind, species, name, stage, growth, is_active, created_at)
            SELECT id, kind, species, name, stage, growth, is_active, created_at
              FROM creatures
            """
        )
        conn.execute("DROP TABLE creatures")
        conn.execute("ALTER TABLE creatures_new RENAME TO creatures")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_creatures_one_active
                ON creatures(kind) WHERE is_active = 1
            """
        )
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


def close_orphan_sessions(conn: sqlite3.Connection) -> int:
    """Đóng mọi session còn ended_at = NULL (app bị tắt hoặc crash giữa chu kỳ).

    Ghi ended_at = started_at, tức thời lượng 0: ta không biết người dùng đã
    tập trung bao lâu trước khi crash, nên không cộng bừa vào thống kê.

    Trả về số dòng đã đóng.
    """
    cursor = conn.execute(
        """
        UPDATE sessions
           SET ended_at  = started_at,
               completed = 0
         WHERE ended_at IS NULL
        """
    )
    return cursor.rowcount
