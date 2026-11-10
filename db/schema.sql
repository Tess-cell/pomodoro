-- ===========================================================================
-- schema.sql - Toàn bộ cấu trúc CSDL, chốt phiên bản 1.
--
-- Chạy lại nhiều lần vẫn an toàn (mọi câu lệnh đều IF NOT EXISTS).
--
-- Quy ước thời gian: lưu dạng chuỗi ISO-8601 UTC, ví dụ '2026-10-22T03:15:00Z'.
-- Lý do: so sánh chuỗi = so sánh thời gian, không lệ thuộc timezone máy.
-- Khi thống kê theo NGÀY phải đổi sang giờ địa phương trước khi gom nhóm:
--     GROUP BY date(datetime(started_at, 'localtime'))
-- Nếu không, chu kỳ lúc 6h sáng (giờ VN) sẽ bị tính vào ngày hôm trước (UTC).
--
-- Lưu ý: foreign_keys mặc định TẮT trong SQLite và PRAGMA này không lưu vào
-- file, nên db/database.py phải bật lại ở mỗi kết nối.
-- ===========================================================================

-- 1. Công việc --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    description  TEXT,
    difficulty   INTEGER NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
    status       TEXT    NOT NULL DEFAULT 'todo'
                         CHECK (status IN ('todo', 'doing', 'done')),
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

-- 2. Chu kỳ focus -----------------------------------------------------------
-- 1 dòng = 1 chu kỳ focus. Giai đoạn NGHỈ không tạo dòng nào.
-- ended_at = NULL nghĩa là session đang mở; nếu app crash, lần khởi động sau
-- sẽ đóng lại với completed = 0 (xem db.database.close_orphan_sessions).
CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_index INTEGER NOT NULL CHECK (cycle_index BETWEEN 1 AND 4),
    task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    started_at  TEXT    NOT NULL,
    ended_at    TEXT,
    violations  INTEGER NOT NULL DEFAULT 0,
    completed   INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    mode        TEXT    NOT NULL DEFAULT 'strict'
                        CHECK (mode IN ('strict', 'flexible'))
);

CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at);

-- 3. Ghi chú ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT    NOT NULL,
    task_id    INTEGER REFERENCES tasks(id)    ON DELETE SET NULL,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_notes_session ON notes(session_id);

-- 4. Sinh vật ảo (thú + cây) -------------------------------------------------
-- kind:    'pet' (thú) hoặc 'plant' (cây)
-- species: khoá loài, vd 'cat', 'oak' -> UI tra emoji/sprite trong config
-- stage:   1 = sinh ra, 2 = lớn lên, 3 = trưởng thành
-- growth:  điểm chăm sóc tích luỹ, không bao giờ giảm
-- is_active: 1 = đang nuôi (mỗi kind tối đa 1 con)
--
-- Ràng buộc toàn vẹn (schema v3):
--   - Sinh vật trưởng thành (stage = 3) VẪN có thể is_active = 1 để nuôi tiếp
--     và tăng điểm không giới hạn (trần kỹ thuật ở config.MAX_GROWTH).
--   - stage và growth luôn được ghi trong cùng một câu UPDATE (core/reward.py).
CREATE TABLE IF NOT EXISTS creatures (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT    NOT NULL CHECK (kind IN ('pet', 'plant')),
    species    TEXT    NOT NULL,
    name       TEXT    NOT NULL,
    stage      INTEGER NOT NULL DEFAULT 1 CHECK (stage BETWEEN 1 AND 3),
    growth     INTEGER NOT NULL DEFAULT 0 CHECK (growth >= 0),
    is_active  INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0, 1)),
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Partial index: mỗi loại (thú/cây) chỉ có tối đa 1 sinh vật đang nuôi
CREATE UNIQUE INDEX IF NOT EXISTS idx_creatures_one_active
    ON creatures(kind) WHERE is_active = 1;

-- 5. Ngôi nhà ---------------------------------------------------------------
-- Bảng 1 dòng duy nhất (id luôn = 1).
-- CHECK sẽ báo lỗi nếu UPDATE vượt 9999, nên logic PHẢI clamp trước:
--     floors = min(MAX_FLOORS, floors + difficulty)
CREATE TABLE IF NOT EXISTS house (
    id     INTEGER PRIMARY KEY CHECK (id = 1),
    floors INTEGER NOT NULL DEFAULT 0 CHECK (floors BETWEEN 0 AND 9999)
);

INSERT OR IGNORE INTO house (id, floors) VALUES (1, 0);

-- 6. Cài đặt dạng key-value -------------------------------------------------
-- Key-value để thêm cấu hình mới không phải ALTER TABLE.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Phiên bản schema. V3: cho phép sinh vật trưởng thành tiếp tục được nuôi.
-- DB cũ (user_version 1 hoặc 2) được migrate trong db/database.py TRƯỚC khi chạy file này.
PRAGMA user_version = 3;
