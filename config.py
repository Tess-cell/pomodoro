"""
config.py - Mọi hằng số của ứng dụng nằm ở đây.

Quy ước: không file nào khác được hard-code con số cấu hình.
Từ Mốc 8, bảng `settings` trong CSDL sẽ ghi đè phần thời lượng;
config.py luôn là giá trị mặc định.
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Đường dẫn
# ---------------------------------------------------------------------------
# Khi chạy từ mã nguồn: BASE_DIR là thư mục dự án.
# Khi đóng gói PyInstaller onefile: tài nguyên (assets/) được giải nén vào
# sys._MEIPASS, còn dữ liệu người dùng (CSDL) phải nằm cạnh file .exe để lưu
# bền — nên tách RESOURCE_DIR và APP_DIR.
if getattr(sys, "frozen", False):
    RESOURCE_DIR = Path(sys._MEIPASS)              # assets, schema.sql
    APP_DIR = Path(sys.executable).resolve().parent  # cạnh file .exe
else:
    RESOURCE_DIR = Path(__file__).resolve().parent
    APP_DIR = RESOURCE_DIR

BASE_DIR = RESOURCE_DIR
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "omnia.db"
ASSETS_DIR = RESOURCE_DIR / "assets"
STYLE_QSS_PATH = ASSETS_DIR / "style.qss"
APP_ICON_PATH = ASSETS_DIR / "app_icon.png"
ICON_DIR = ASSETS_DIR / "icons"

# ---------------------------------------------------------------------------
# Theme giao diện (dark minimal kiểu Linear/Notion)
# ---------------------------------------------------------------------------
THEME_FONT_FAMILY = "Segoe UI Variable"   # fallback "Segoe UI" do QSS lo
THEME_BG = "#121418"                      # nền cửa sổ
THEME_SURFACE = "#1A1D24"                 # nền thẻ/khối nổi
THEME_BORDER = "#262A33"                  # viền mờ
THEME_ACCENT = "#7C5CFF"                  # màu nhấn duy nhất (tím)
THEME_ACCENT_HOVER = "#9377FF"
THEME_ACCENT_PRESSED = "#6A4AE6"
THEME_TEXT = "#FFFFFF"
THEME_TEXT_MUTED = "#9AA0AD"              # chữ phụ
THEME_TEXT_FAINT = "#6B7280"              # chữ mờ (nhãn chu kỳ)
THEME_RADIUS = 14                         # bo góc chung (px)

# Vòng tròn tiến độ quanh đồng hồ (vẽ bằng QPainter)
CLOCK_RING_WIDTH = 5                      # độ dày vòng
CLOCK_RING_MIN_SIZE = 180                 # đường kính vùng đồng hồ (px)

# ---------------------------------------------------------------------------
# Ảnh Omnia cho overlay (PNG tự cắt nền, quy ước tên file xem
# assets/omnia/README.md). Thiếu ảnh thì overlay tự lùi về emoji sprite.
# ---------------------------------------------------------------------------
OMNIA_ART_DIR = ASSETS_DIR / "omnia"
OMNIA_ART_SIZE = 512              # cạnh ảnh đề xuất (px, vuông, nền trong suốt)
OMNIA_ART_DISPLAY_SIZE = 160      # cạnh hiển thị trong overlay (px)

# ---------------------------------------------------------------------------
# Thông tin ứng dụng
# ---------------------------------------------------------------------------
APP_NAME = "Pomodoro Omnia"
APP_VERSION = "5.10.0"
WINDOW_TITLE = f"{APP_NAME} - v{APP_VERSION}"
# Cửa sổ chính chỉ còn cột đồng hồ + lưới 4 nút mở cửa sổ chức năng.
# Bề ngang THỰC TẾ ~693px do hàng 4 nút timer ("Tua hết giờ >>" + đệm) quyết
# định; WINDOW_WIDTH dưới đây chỉ là gợi ý ban đầu, Qt tự nới theo nội dung.
WINDOW_WIDTH = 380
WINDOW_HEIGHT = 560

# Nhịp QTimer cập nhật đồng hồ và giao diện (mili giây)
TICK_MS = 200

# ---------------------------------------------------------------------------
# Chế độ phát triển & Test nhanh
# DEBUG = False khi nộp bài: tắt nút tua nhanh, nút cộng điểm thử và phím Esc
# FAST_MODE = True: dùng số giây ngắn để test thủ công nhanh; False: chạy phút thật
# ---------------------------------------------------------------------------
DEBUG = False
# DEV_ALLOW_ESCAPE đi kèm Mốc 9 (đã cắt); hiện không được code nào dùng.
DEV_ALLOW_ESCAPE = DEBUG
DEBUG_ADD_POINTS = 25
FAST_MODE = False

# Số giây còn lại khi bấm Tua nhanh (để đếm ngược 1s hoặc 2s trước khi chuyển giai đoạn)
FAST_FORWARD_REMAINING_SECONDS = 1

# ---------------------------------------------------------------------------
# Chu kỳ Pomodoro (Cấu hình chuẩn tính bằng phút)
# ---------------------------------------------------------------------------
FOCUS_MINUTES = 25
SHORT_BREAK_MINUTES = 5
LONG_BREAK_MINUTES = 20
CYCLES_BEFORE_LONG_BREAK = 4

# True = chế độ nghiêm ngặt (hết giờ là nghỉ ngay)
# False = chế độ linh hoạt (được gia hạn GRACE_SECONDS)
STRICT_MODE = True

# Ghi đè từ Cài đặt (bảng settings). Giá trị lạ -> dùng STRICT_MODE.
SETTING_STRICT_MODE = "strict_mode"

# Nhãn hiển thị hai chế độ (dùng chung UI và test)
POMODORO_MODES = {
    "strict": "Nghiêm ngặt (hết giờ là nghỉ ngay)",
    "flexible": "Linh hoạt (gia hạn thêm để làm nốt)",
}

# Ghi đè thời lượng chu kỳ từ Cài đặt (lưu số PHÚT trong bảng settings).
# Chưa lưu -> dùng FOCUS_MINUTES / SHORT_BREAK_MINUTES / LONG_BREAK_MINUTES ở trên.
SETTING_FOCUS_MINUTES = "focus_minutes"
SETTING_SHORT_BREAK_MINUTES = "short_break_minutes"
SETTING_LONG_BREAK_MINUTES = "long_break_minutes"

# Giới hạn hợp lệ khi cho người dùng chỉnh (phút)
DURATION_LIMITS_MINUTES = {
    SETTING_FOCUS_MINUTES: (1, 180),
    SETTING_SHORT_BREAK_MINUTES: (1, 60),
    SETTING_LONG_BREAK_MINUTES: (1, 120),
}

# Mốc gia hạn trong chế độ Linh hoạt (giây). Mốc tối đa = hạn mức tổng mỗi chu kỳ.
#   - Chu kỳ kế tiếp là nghỉ ngắn: chọn 1 hoặc 2 phút.
#   - Chu kỳ kế tiếp là nghỉ dài : chọn 1..5 phút.
SHORT_GRACE_OPTIONS_MINUTES = (1, 2)
LONG_GRACE_OPTIONS_MINUTES = (1, 2, 3, 4, 5)
SHORT_GRACE_OPTIONS_SECONDS = tuple(m * 60 for m in SHORT_GRACE_OPTIONS_MINUTES)
LONG_GRACE_OPTIONS_SECONDS = tuple(m * 60 for m in LONG_GRACE_OPTIONS_MINUTES)

# Thời lượng chuẩn (giây)
STANDARD_FOCUS_SECONDS = FOCUS_MINUTES * 60
STANDARD_SHORT_BREAK_SECONDS = SHORT_BREAK_MINUTES * 60
STANDARD_LONG_BREAK_SECONDS = LONG_BREAK_MINUTES * 60
STANDARD_GRACE_SECONDS = 120
STANDARD_AUTO_CONFIRM_SECONDS = 60

# Thời lượng test nhanh (giây) khi FAST_MODE = True
FAST_FOCUS_SECONDS = 10
FAST_SHORT_BREAK_SECONDS = 3
FAST_LONG_BREAK_SECONDS = 6
FAST_GRACE_SECONDS = 5
FAST_AUTO_CONFIRM_SECONDS = 3

# Giá trị áp dụng thực tế theo cờ FAST_MODE
if FAST_MODE:
    FOCUS_SECONDS = FAST_FOCUS_SECONDS
    SHORT_BREAK_SECONDS = FAST_SHORT_BREAK_SECONDS
    LONG_BREAK_SECONDS = FAST_LONG_BREAK_SECONDS
    GRACE_SECONDS = FAST_GRACE_SECONDS
    AUTO_CONFIRM_BREAK_SECONDS = FAST_AUTO_CONFIRM_SECONDS
else:
    FOCUS_SECONDS = STANDARD_FOCUS_SECONDS
    SHORT_BREAK_SECONDS = STANDARD_SHORT_BREAK_SECONDS
    LONG_BREAK_SECONDS = STANDARD_LONG_BREAK_SECONDS
    GRACE_SECONDS = STANDARD_GRACE_SECONDS
    AUTO_CONFIRM_BREAK_SECONDS = STANDARD_AUTO_CONFIRM_SECONDS

# ---------------------------------------------------------------------------
# Focus mode (Mốc 9 ĐÃ CẮT — xem docs/DECISIONS.md).
# Các hằng số này không được code nào dùng; giữ lại để tham khảo nếu sau này
# làm lại, không xoá theo quyết định cắt.
# ---------------------------------------------------------------------------
FOCUS_POLL_MS = 1500              # chu kỳ quét app cấm (mili giây)
FOCUS_COOLDOWN_SECONDS = 10       # miễn kiểm tra sau khi đuổi Omnia
OMNIA_CLICKS_TO_DISMISS = 10      # số click cần để đuổi
OMNIA_DISMISS_WINDOW_SECONDS = 5  # phải đủ số click trong khoảng này

# ---------------------------------------------------------------------------
# Phần thưởng
# ---------------------------------------------------------------------------
CARE_POINTS_PER_DIFFICULTY = 2    # điểm chăm sóc = hệ số * độ khó
GROWTH_THRESHOLDS = (0, 50, 180)  # điểm tích luỹ cho giai đoạn 1, 2, 3
MAX_FLOORS = 9999                # trần số tầng của ngôi nhà

# Giới hạn kỹ thuật của cột INTEGER trong SQLite (thực tế là vô hạn).
# Điểm chăm sóc vẫn được hiển thị bình thường sau khi trưởng thành.
MAX_GROWTH = 2**63 - 1

TASK_DIFFICULTY_MIN = 1
TASK_DIFFICULTY_MAX = 5

# ---------------------------------------------------------------------------
# Sinh vật Omnia (thú ảo / cây trồng)
# ---------------------------------------------------------------------------
CREATURE_KINDS = ("pet", "plant")

# Mỗi loài có 3 sprite ứng với stage 1 (sinh ra), 2 (lớn lên), 3 (trưởng thành).
# UI tra sprite theo (kind, species, stage); loài lạ sẽ dùng sprite dự phòng.
CREATURE_SPECIES = {
    "pet": {
        "cat": {"label": "Mèo", "sprites": ("🥚", "🐣", "🐱")},
        "dog": {"label": "Chó", "sprites": ("🥚", "🐣", "🐶")},
        "rabbit": {"label": "Thỏ", "sprites": ("🥚", "🐣", "🐰")},
    },
    "plant": {
        "oak": {"label": "Cây sồi", "sprites": ("🌱", "🌿", "🌳")},
        "sunflower": {"label": "Hướng dương", "sprites": ("🌱", "🌿", "🌻")},
        "cactus": {"label": "Xương rồng", "sprites": ("🌱", "🌵", "🌵")},
    },
}

CREATURE_STAGE_LABELS = {
    1: "Sinh ra",
    2: "Lớn lên",
    3: "Trưởng thành",
}

# ---------------------------------------------------------------------------
# Omnia đang nhận tiến trình (chỉ 1 trong 3)
# ---------------------------------------------------------------------------
OMNIA_TARGETS = ("house", "pet", "plant")
DEFAULT_OMNIA_TARGET = "house"
SETTING_ACTIVE_OMNIA = "active_omnia"   # key trong bảng settings (key-value)

# ---------------------------------------------------------------------------
# Ghi chú
# ---------------------------------------------------------------------------
NOTE_AUTOSAVE_MS = 500            # tự lưu sau khi ngừng gõ
PINNED_NOTE_WIDTH = 320           # cửa sổ ghi chú ghim (góc trên trái)
PINNED_NOTE_HEIGHT = 190

# Ghi chú ghim sau khi hết giờ nghỉ có tự ẩn không:
#   True  = tự ẩn khi rời giờ nghỉ (mặc định cũ)
#   False = giữ nguyên trên màn hình cho tới khi người dùng tự tắt
# Người dùng đổi được trong Cài đặt (lưu key `pinned_note_autohide` ở bảng settings).
SETTING_PINNED_NOTE_AUTOHIDE = "pinned_note_autohide"
PINNED_NOTE_AUTOHIDE_DEFAULT = True

# ---------------------------------------------------------------------------
# Overlay thông báo hết chu kỳ (Omnia trượt từ phải)
# ---------------------------------------------------------------------------
# Mỗi chiều chiếm 1/2 vùng khả dụng -> diện tích 1/4, đặt ở góc dưới phải.
OVERLAY_SCREEN_FRACTION = 2
OVERLAY_MIN_WIDTH = 360           # tránh quá nhỏ trên màn hình thấp
OVERLAY_MIN_HEIGHT = 260
OVERLAY_ANIMATION_MS = 320        # thời gian trượt vào / ra
WINDOW_MARGIN = 10                # lề cửa sổ ghim so với mép màn hình
