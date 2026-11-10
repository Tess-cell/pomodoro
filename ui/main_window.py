"""
main_window.py - Cửa sổ chính của ứng dụng.

Kiến trúc:
  - Giao diện KHÔNG chứa logic nghiệp vụ cốt lõi (TimerEngine thuần Python
    trong core/, truy vấn dữ liệu trong db/).
  - Hoàn thành công việc chạy ở mọi trạng thái đồng hồ:
      (1) Đánh dấu done trong DB;
      (2) Trao phần thưởng cho Omnia đang chọn;
      (3) Gửi Event.TASK_DONE với task_id cho TimerEngine.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import config
from core.controller import SessionController
from core.effects import CycleFinished, Effect, NeedNewTask, OpenQuickNote
from core import reward
from core.states import BREAK_STATES, RUNNING_STATES, Event, State
from core.timer_engine import TimerEngine, format_duration
from db import creatures as creatures_repo
from db import house as house_repo
from db import notes as notes_repo
from db import sessions as sessions_repo
from db import settings as settings_repo
from db import tasks as tasks_repo
from ui import omnia_art
from ui.cycle_overlay import CycleOverlay
from ui.note_viewer import NoteViewerWindow
from ui.pinned_note import PinnedNoteWindow

# Nhãn hiển thị cho từng trạng thái
STATE_LABELS = {
    State.IDLE: "Sẵn sàng",
    State.FOCUS: "Đang tập trung",
    State.GRACE: "Gia hạn (đang làm nốt)",
    State.SHORT_BREAK: "Nghỉ ngắn",
    State.LONG_BREAK: "Nghỉ dài",
    State.PAUSED: "Tạm dừng",
}

class ClockRing(QWidget):
    """Khung vẽ vòng tròn tiến độ bao quanh nhãn đồng hồ.

    Chỉ vẽ, không chứa logic thời gian: MainWindow gọi `set_progress(ratio)`
    với tỉ lệ 0..1 (phần thời gian ĐÃ trôi của giai đoạn hiện tại).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress = 0.0
        size = config.CLOCK_RING_MIN_SIZE
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def set_progress(self, ratio: float) -> None:
        ratio = max(0.0, min(1.0, float(ratio)))
        if ratio != self._progress:
            self._progress = ratio
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = config.CLOCK_RING_WIDTH
        margin = width / 2 + 1
        # Vòng luôn vuông: lấy cạnh nhỏ hơn để không bị méo.
        side = min(self.width(), self.height()) - 2 * margin
        rect = QRectF(
            (self.width() - side) / 2, (self.height() - side) / 2, side, side
        )

        # Vòng nền xám đầy đủ.
        base_pen = QPen(QColor(config.THEME_BORDER), width)
        base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(base_pen)
        painter.drawArc(rect, 0, 360 * 16)

        # Vòng tiến độ màu nhấn, bắt đầu 12 giờ, chạy theo chiều kim đồng hồ.
        if self._progress > 0:
            accent_pen = QPen(QColor(config.THEME_ACCENT), width)
            accent_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(accent_pen)
            span = int(-self._progress * 360 * 16)
            painter.drawArc(rect, 90 * 16, span)


class MainWindow(QMainWindow):
    """Cửa sổ chính của ứng dụng."""

    def __init__(self, conn: sqlite3.Connection, engine: TimerEngine | None = None) -> None:
        super().__init__()
        self.conn = conn

        # Cho phép tiêm engine từ ngoài (dùng khi cần test với đồng hồ giả).
        # Cài đặt đã lưu chỉ áp dụng cho engine do chính MainWindow tạo; engine
        # tiêm từ ngoài giữ nguyên cấu hình mà người gọi đã đặt.
        engine_injected = engine is not None
        self.engine = engine if engine is not None else TimerEngine()
        self.controller = SessionController(conn)

        # Trạng thái công việc trên giao diện
        self.selected_task_id: int | None = None
        self.editing_task_id: int | None = None
        # Chữ đầy đủ của từng dòng tab Ghi chú (để cắt "…" khi cửa sổ hẹp).
        self._note_texts: dict[int, str] = {}

        self._build_ui()
        self._load_tasks()

        # Áp dụng Cài đặt đã lưu. Lúc khởi động engine ở IDLE nên
        # mọi thay đổi đều áp dụng được ngay.
        #   - Chế độ Nghiêm ngặt/Linh hoạt: luôn theo Cài đặt (là tùy chọn của
        #     người dùng, không phải tham số kỹ thuật của engine).
        #   - Thời lượng: chỉ khi MainWindow tự tạo engine. Engine được tiêm
        #     từ ngoài (test, script) giữ đúng thời lượng người gọi đã đặt.
        self.engine.set_strict_mode(
            settings_repo.get_strict_mode(conn), force=True
        )
        if not engine_injected:
            # Cài đặt trong CSDL ghi bằng PHÚT; chưa có thì giữ nguyên thời
            # lượng engine đã khởi tạo theo config (*_SECONDS, đã áp FAST_MODE).
            if settings_repo.get_setting(conn, config.SETTING_FOCUS_MINUTES) is not None:
                self.engine.set_durations(
                    focus_seconds=settings_repo.get_duration_minutes(
                        conn, config.SETTING_FOCUS_MINUTES, config.FOCUS_MINUTES
                    ) * 60,
                    short_break_seconds=settings_repo.get_duration_minutes(
                        conn, config.SETTING_SHORT_BREAK_MINUTES,
                        config.SHORT_BREAK_MINUTES,
                    ) * 60,
                    long_break_seconds=settings_repo.get_duration_minutes(
                        conn, config.SETTING_LONG_BREAK_MINUTES,
                        config.LONG_BREAK_MINUTES,
                    ) * 60,
                    force=True,
                )

        # Cửa sổ nổi: overlay thông báo hết chu kỳ (phải) và ghi chú ghim (trái).
        # Ẩn tường minh ngay sau khi tạo: widget frameless chưa show() có thể bị
        # driver vẽ lộ một khung ở góc (0,0) khi chưa có lần show() nào.
        self.overlay = CycleOverlay(self)
        self.overlay.hide()
        self.overlay.confirmed.connect(self._on_confirm_clicked)
        self.overlay.extend_requested.connect(self._on_extend_requested)
        self.pinned_note = PinnedNoteWindow(self)
        self.pinned_note.hide()
        self.pinned_note.save_requested.connect(self._on_pinned_note_save_requested)
        self.pinned_note.close_button.clicked.connect(self._on_pinned_note_closed)
        # True = người dùng đã chủ động tắt ghi chú ghim trong chu kỳ này
        self._pinned_note_dismissed = False
        self.note_viewer: NoteViewerWindow | None = None

        # QTimer định kỳ gọi engine.update()
        self.tick_timer = QTimer(self)
        self.tick_timer.setInterval(config.TICK_MS)
        self.tick_timer.timeout.connect(self._on_tick)
        self.tick_timer.start()

        self._refresh_ui()
        self._refresh_omnia_display()
        self._refresh_notes_display()

    # ------------------------------------------------------------------
    # Dựng giao diện
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle(config.WINDOW_TITLE)
        self.resize(config.WINDOW_WIDTH, config.WINDOW_HEIGHT)

        central = QWidget(self)
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 24, 24, 24)
        main_layout.setSpacing(18)

        # ==============================================================
        # CỘT DUY NHẤT: Bộ đếm Pomodoro (cửa sổ hẹp, dọc)
        # ==============================================================
        timer_widget = QWidget(central)
        timer_layout = QVBoxLayout(timer_widget)
        timer_layout.setContentsMargins(0, 0, 0, 0)
        timer_layout.setSpacing(18)

        self.cycle_label = QLabel(self)
        self.cycle_label.setObjectName("cycleLabel")
        self.cycle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_layout.addWidget(self.cycle_label)

        self.state_label = QLabel(self)
        self.state_label.setObjectName("stateLabel")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        timer_layout.addWidget(self.state_label)

        # Nhãn đồng hồ nằm trong một widget tự vẽ vòng tròn tiến độ bao quanh.
        self.clock_label = QLabel(self._format_time(self.engine.phase_seconds), self)
        self.clock_label.setObjectName("clockLabel")
        self.clock_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock_ring = ClockRing(self)
        self.clock_ring.setObjectName("clockRing")
        ring_layout = QVBoxLayout(self.clock_ring)
        ring_layout.setContentsMargins(0, 0, 0, 0)
        ring_layout.addWidget(self.clock_label)
        timer_layout.addWidget(
            self.clock_ring, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        # Nhãn công việc hiện tại
        self.current_task_label = QLabel("Việc hiện tại: (Chưa chọn việc)", self)
        self.current_task_label.setObjectName("currentTaskLabel")
        self.current_task_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Cho xuống dòng để tên việc dài không ép cửa sổ hẹp phình ra.
        self.current_task_label.setWordWrap(True)
        timer_layout.addWidget(self.current_task_label)

        # Nhãn hiển thị Omnia đang nhận tiến trình, dạng thẻ nổi.
        summary_widget = QWidget(timer_widget)
        summary_layout = QHBoxLayout(summary_widget)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(10)
        self.house_icon = QLabel(summary_widget)
        self.house_icon.setFixedSize(40, 40)
        self.house_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary_layout.addWidget(self.house_icon)
        self.house_label = QLabel(summary_widget)
        self.house_label.setObjectName("houseLabel")
        self.house_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.house_label.setWordWrap(True)
        summary_layout.addWidget(self.house_label, stretch=1)
        timer_layout.addWidget(summary_widget)

        # Hàng nút điều khiển đồng hồ: "Bắt đầu" là nút chính (màu nhấn),
        # ba nút còn lại là nút phụ (nền tối, viền mờ).
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.start_button = QPushButton("Bắt đầu", self)
        self.start_button.setObjectName("primaryButton")
        self.pause_button = QPushButton("Tạm dừng", self)
        self.stop_button = QPushButton("Dừng", self)
        self.skip_button = QPushButton("Tua hết giờ >>", self)
        for button in (self.pause_button, self.stop_button, self.skip_button):
            button.setObjectName("secondaryButton")
        self.skip_button.setToolTip("Tua nhanh tới 1-2 giây cuối của giai đoạn (Phím tắt: F12)")

        for button in (
            self.start_button,
            self.pause_button,
            self.stop_button,
            self.skip_button,
        ):
            button.setMinimumHeight(38)
            button_row.addWidget(button)
        timer_layout.addLayout(button_row)

        # Nối signal nút đồng hồ
        self.start_button.clicked.connect(self._on_start_clicked)
        self.pause_button.clicked.connect(self._on_pause_clicked)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        # Không có nút "Xác nhận"/"Nghỉ ngay" ở đây: overlay hết chu kỳ (góc
        # dưới phải màn hình) lo cả hai việc (chọn mốc gia hạn / bắt đầu nghỉ).
        self.skip_button.clicked.connect(self._on_skip_clicked)

        # Phím tắt F12 tua nhanh khi DEBUG = True
        self.skip_shortcut = QShortcut(QKeySequence("F12"), self)
        self.skip_shortcut.activated.connect(self._on_skip_clicked)

        main_layout.addWidget(timer_widget, stretch=1)

        # ==============================================================
        # Lưới 2x2 nút mở cửa sổ chức năng (thay cho QTabWidget cột phải)
        # ==============================================================
        self.open_buttons: dict[str, QPushButton] = {}
        self.tab_titles: dict[str, str] = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        for position, (key, label) in enumerate(
            (
                ("tasks", "Công việc"),
                ("omnia", "Omnia"),
                ("collection", "Bộ sưu tập"),
                ("notes", "Ghi chú"),
            )
        ):
            self.tab_titles[key] = label
            button = QPushButton(label, central)
            icon_key = "pet" if key == "omnia" else key
            button.setIcon(QIcon(str(config.ICON_DIR / f"{icon_key}.svg")))
            button.setIconSize(QSize(20, 20))
            button.setObjectName("navButton")
            button.setMinimumHeight(46)
            button.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            button.clicked.connect(
                lambda _checked=False, k=key: self._open_tab_window(k)
            )
            grid.addWidget(button, position // 2, position % 2)
            self.open_buttons[key] = button
        for column in (0, 1):
            grid.setColumnStretch(column, 1)
        main_layout.addLayout(grid)

        # ==============================================================
        # NỘI DUNG 4 CHỨC NĂNG: mỗi cái là một QWidget, mở trong cửa sổ riêng
        # ==============================================================
        # Các widget chức năng được gắn vào QDialog khi mở; để chúng không là
        # con của central widget khi đang chờ, tránh bị vẽ lộ ở góc (0, 0).
        tasks_widget = QWidget()
        tasks_layout = QVBoxLayout(tasks_widget)
        tasks_layout.setContentsMargins(10, 10, 10, 10)
        tasks_layout.setSpacing(10)

        tasks_title = QLabel("Danh sách công việc (To-do List)", tasks_widget)
        tasks_title_font = tasks_title.font()
        tasks_title_font.setPointSize(13)
        tasks_title_font.setBold(True)
        tasks_title.setFont(tasks_title_font)
        tasks_layout.addWidget(tasks_title)

        # Bảng danh sách công việc
        self.tasks_table = QTableWidget(tasks_widget)
        self.tasks_table.setColumnCount(5)
        self.tasks_table.setHorizontalHeaderLabels(
            ["STT", "Tên công việc", "Mô tả", "Độ khó", "Trạng thái"]
        )
        self.tasks_table.verticalHeader().setVisible(False)
        header = self.tasks_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)   # Mô tả
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        # Tên/mô tả dài không được kéo dãn cửa sổ: cho xuống dòng và giới hạn.
        self.tasks_table.setWordWrap(True)
        self.tasks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tasks_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tasks_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tasks_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        # Nhấp đúp vào ô Tên/Mô tả -> mở cửa sổ xem toàn bộ nội dung.
        self.tasks_table.cellDoubleClicked.connect(self._on_task_cell_double_clicked)
        tasks_layout.addWidget(self.tasks_table)

        # Hàng nút thao tác trên công việc
        task_btn_row = QHBoxLayout()
        task_btn_row.setSpacing(8)
        self.btn_select_task = QPushButton("Chọn làm việc này", tasks_widget)
        self.btn_deselect_task = QPushButton("Bỏ chọn", tasks_widget)
        self.btn_complete_task = QPushButton("Hoàn thành", tasks_widget)
        self.btn_edit_task = QPushButton("Sửa", tasks_widget)
        self.btn_delete_task = QPushButton("Xóa", tasks_widget)

        for btn in (
            self.btn_select_task,
            self.btn_deselect_task,
            self.btn_complete_task,
            self.btn_edit_task,
            self.btn_delete_task,
        ):
            btn.setMinimumHeight(32)
            task_btn_row.addWidget(btn)
        tasks_layout.addLayout(task_btn_row)

        self.btn_select_task.clicked.connect(self._on_select_task_clicked)
        self.btn_deselect_task.clicked.connect(self._on_deselect_task_clicked)
        self.btn_complete_task.clicked.connect(self._on_complete_task_clicked)
        self.btn_edit_task.clicked.connect(self._on_edit_task_clicked)
        self.btn_delete_task.clicked.connect(self._on_delete_task_clicked)

        # Form thêm / sửa công việc
        self.form_group = QGroupBox("Thêm công việc mới", tasks_widget)
        form_layout = QVBoxLayout(self.form_group)
        form_layout.setSpacing(8)

        row1 = QHBoxLayout()
        self.name_input = QLineEdit(self.form_group)
        self.name_input.setPlaceholderText("Tên công việc (bắt buộc)...")
        self.diff_spin = QSpinBox(self.form_group)
        self.diff_spin.setRange(config.TASK_DIFFICULTY_MIN, config.TASK_DIFFICULTY_MAX)
        self.diff_spin.setValue(1)
        self.diff_spin.setPrefix("Độ khó: ")
        row1.addWidget(self.name_input, stretch=3)
        row1.addWidget(self.diff_spin, stretch=1)
        form_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.desc_input = QLineEdit(self.form_group)
        self.desc_input.setPlaceholderText("Mô tả chi tiết (tùy chọn)...")
        self.btn_save_task = QPushButton("Thêm việc", self.form_group)
        self.btn_cancel_edit = QPushButton("Hủy", self.form_group)
        self.btn_cancel_edit.setVisible(False)
        row2.addWidget(self.desc_input, stretch=3)
        row2.addWidget(self.btn_save_task, stretch=1)
        row2.addWidget(self.btn_cancel_edit, stretch=1)
        form_layout.addLayout(row2)

        self.btn_save_task.clicked.connect(self._on_save_task_clicked)
        self.btn_cancel_edit.clicked.connect(self._on_cancel_edit_clicked)
        self.name_input.returnPressed.connect(self._on_save_task_clicked)
        self.desc_input.returnPressed.connect(self._on_save_task_clicked)

        tasks_layout.addWidget(self.form_group)

        # Bốn widget chức năng, KHÔNG nằm trong cửa sổ chính. Mỗi cái được mở
        # trong một QDialog riêng (xem _open_tab_window). Widget giữ nguyên
        # mọi hành vi cũ; chỉ đổi nơi chứa.
        self.tab_widgets: dict[str, QWidget] = {
            "tasks": tasks_widget,
            "omnia": self._build_omnia_tab(None),
            "collection": self._build_collection_tab(None),
            "notes": self._build_notes_tab(None),
        }
        self.tab_windows: dict[str, QDialog] = {}

        # Nút Cài đặt ở thanh trạng thái (bắt đầu từ mục ghi chú ghim).
        self.btn_settings = QPushButton("Cài đặt", self)
        self.btn_settings.setIcon(QIcon(str(config.ICON_DIR / "settings.svg")))
        self.btn_settings.setIconSize(QSize(16, 16))
        self.btn_settings.setFlat(True)
        self.btn_settings.clicked.connect(self._open_settings_dialog)
        self.statusBar().addPermanentWidget(self.btn_settings)

        self.statusBar().showMessage("Sẵn sàng")

    # ------------------------------------------------------------------
    # Cửa sổ chức năng (thay cho QTabWidget cột phải)
    # ------------------------------------------------------------------
    def _open_tab_window(self, key: str) -> None:
        """Mở nội dung `key` trong một cửa sổ riêng; đã mở thì đưa lên trước.

        Cửa sổ tạo lazy một lần rồi giữ lại: đóng chỉ ẩn đi nên widget và dữ
        liệu bên trong không bị hủy. Cửa sổ là con của MainWindow (không modal)
        nên tự đóng theo cửa sổ chính.
        """
        window = self.tab_windows.get(key)
        if window is None:
            widget = self.tab_widgets[key]
            window = QDialog(self)
            window.setWindowTitle(self.tab_titles[key])
            window.resize(640, 520)
            layout = QVBoxLayout(window)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.addWidget(widget)
            self.tab_windows[key] = window

        if key == "notes":
            self._refresh_notes_display()

        window.show()
        window.raise_()
        window.activateWindow()

    # ------------------------------------------------------------------
    # Xử lý CSDL và bảng công việc
    # ------------------------------------------------------------------
    def _load_tasks(self) -> None:
        """Đọc danh sách công việc từ CSDL và nạp vào bảng."""
        tasks = tasks_repo.list_tasks(self.conn)
        self.tasks_table.setRowCount(len(tasks))

        for row, task in enumerate(tasks):
            stt_item = QTableWidgetItem(str(row + 1))
            stt_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Cột tên lưu task_id vào UserRole để quản lý lựa chọn.
            name_item = QTableWidgetItem(task["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, task["id"])
            if task["status"] == "done":
                font = name_item.font()
                font.setStrikeOut(True)
                name_item.setFont(font)

            # Cột 2: Mô tả (hiện ngay trong bảng, không cần bấm Sửa).
            desc_text = task["description"] or ""
            desc_item = QTableWidgetItem(desc_text)
            desc_item.setToolTip(desc_text)

            # Cột 3: Độ khó
            diff_item = QTableWidgetItem(f"{task['difficulty']}/{config.TASK_DIFFICULTY_MAX}")
            diff_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Cột 4: Trạng thái
            status_map = {
                "todo": "Chưa làm",
                "doing": "Đang làm",
                "done": "Đã xong",
            }
            status_text = status_map.get(task["status"], task["status"])
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.tasks_table.setItem(row, 0, stt_item)
            self.tasks_table.setItem(row, 1, name_item)
            self.tasks_table.setItem(row, 2, desc_item)
            self.tasks_table.setItem(row, 3, diff_item)
            self.tasks_table.setItem(row, 4, status_item)

        self._on_table_selection_changed()

    def _get_selected_task_id(self) -> int | None:
        row = self.tasks_table.currentRow()
        if row < 0:
            return None
        item = self.tasks_table.item(row, 1)
        if item is None:
            return None
        task_id = item.data(Qt.ItemDataRole.UserRole)
        return int(task_id) if task_id is not None else None

    def _on_table_selection_changed(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            self.btn_select_task.setEnabled(False)
            self.btn_complete_task.setEnabled(False)
            self.btn_edit_task.setEnabled(False)
            self.btn_delete_task.setEnabled(False)
            return

        task = tasks_repo.get_task(self.conn, task_id)
        if task is None:
            return

        is_done = task["status"] == "done"
        self.btn_select_task.setEnabled(not is_done)
        self.btn_complete_task.setEnabled(not is_done)
        self.btn_edit_task.setEnabled(not is_done)
        self.btn_delete_task.setEnabled(True)

    def _on_select_task_clicked(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return

        task = tasks_repo.get_task(self.conn, task_id)
        if task is None:
            return

        if task["status"] == "done":
            QMessageBox.warning(self, "Không hợp lệ", "Công việc này đã hoàn thành, vui lòng chọn việc chưa hoàn thành.")
            return

        self.selected_task_id = task_id
        if self.engine.state in (State.FOCUS, State.GRACE):
            self.engine.current_task_id = task_id

        self._refresh_current_task_label()
        self.statusBar().showMessage(f"Đã chọn công việc: '{task['name']}' làm việc hiện tại.")

    def _on_deselect_task_clicked(self) -> None:
        self.selected_task_id = None
        self.engine.current_task_id = None
        self._refresh_current_task_label()
        self.statusBar().showMessage("Đã bỏ chọn công việc.")

    def _on_complete_task_clicked(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return

        task = tasks_repo.get_task(self.conn, task_id)
        if task is None:
            return

        reply = QMessageBox.question(
            self,
            "Xác nhận hoàn thành",
            f"Đánh dấu hoàn thành công việc:\n'{task['name']}' (Độ khó {task['difficulty']})?\n\n(Hành động này là một chiều và không thể hoàn tác)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # (1) Đánh dấu done trong CSDL
        tasks_repo.complete_task(self.conn, task_id)

        # (2) Trao tiến trình cho Omnia đang chọn (nhà / thú / cây)
        target, award = self._resolve_reward_target(task["difficulty"])
        reward_result = reward.apply_task_rewards(
            self.conn,
            difficulty=task["difficulty"],
            target=target,
            award=award,
        )

        # (3) Gửi Event.TASK_DONE với đúng task_id
        effects = self.engine.handle(Event.TASK_DONE, task_id=task_id)
        self._apply_effects(effects)

        if self.selected_task_id == task_id:
            self.selected_task_id = None

        self._load_tasks()
        self._refresh_current_task_label()
        self._refresh_house_display()
        self._refresh_omnia_display()
        self._refresh_ui()

        # Hiển thị thông báo thưởng theo đúng Omnia đã nhận tiến trình
        if not award:
            reward_msg = "Không cộng tiến trình lần này (ô nuôi trống, giữ lựa chọn cũ)."
        elif reward_result.target == "house":
            if reward_result.added_floors > 0:
                reward_msg = f"+{reward_result.added_floors} tầng nhà! (Hiện tại: Tầng {reward_result.total_floors:,})"
            else:
                reward_msg = f"Ngôi nhà đã chạm tầng mây cao nhất (Tầng {config.MAX_FLOORS:,})!"
        else:
            creature_reward = reward_result.pet or reward_result.plant
            if creature_reward is None:
                reward_msg = "Ô nuôi đang trống nên không cộng điểm."
            else:
                emoji = "🐾" if creature_reward.kind == "pet" else "🌱"
                reward_msg = (
                    f"{emoji} {creature_reward.name} +{creature_reward.added_points} điểm"
                    f" (tổng {creature_reward.new_growth:,})"
                )

        creature_rewards = [
            r for r in (reward_result.pet, reward_result.plant) if r is not None
        ]
        care_parts = [
            f"🎉 {r.name} đã trưởng thành!" for r in creature_rewards if r.became_adult
        ]
        care_msg = (" | " + " · ".join(care_parts)) if care_parts else ""
        self._notify_matured(creature_rewards)

        if any(isinstance(e, NeedNewTask) for e in effects):
            self.statusBar().showMessage(
                f"Đã hoàn thành '{task['name']}'! {reward_msg}{care_msg}"
                " | Đồng hồ vẫn đang tập trung - hãy chọn việc mới hoặc nghỉ ngơi."
            )
        else:
            self.statusBar().showMessage(
                f"Đã hoàn thành '{task['name']}'! {reward_msg}{care_msg}"
            )

    def _on_delete_task_clicked(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return

        task = tasks_repo.get_task(self.conn, task_id)
        if task is None:
            return

        reply = QMessageBox.question(
            self,
            "Xác nhận xóa",
            f"Bạn có chắc muốn xóa công việc: '{task['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Xóa việc đang là current_task_id thì bỏ gắn khỏi engine, không lỗi
        if self.engine.current_task_id == task_id:
            self.engine.current_task_id = None
        if self.selected_task_id == task_id:
            self.selected_task_id = None

        if self.editing_task_id == task_id:
            self._on_cancel_edit_clicked()

        tasks_repo.delete_task(self.conn, task_id)
        self._load_tasks()
        self._refresh_current_task_label()
        self.statusBar().showMessage("Đã xóa công việc.")

    def _on_task_cell_double_clicked(self, row: int, column: int) -> None:
        """Nhấp đúp cột Tên (1) hoặc Mô tả (2): mở cửa sổ xem toàn bộ."""
        if column not in (1, 2):
            return
        item = self.tasks_table.item(row, column)
        if item is None:
            return
        heading = "Tên công việc" if column == 1 else "Mô tả công việc"
        text = item.text() or "(trống)"
        self._show_text_window(f"{heading}", text)

    def _show_text_window(self, title: str, text: str) -> None:
        """Cửa sổ chỉ-đọc hiện toàn bộ nội dung, cho copy và đóng."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(520, 420)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        view = QPlainTextEdit(dialog)
        view.setReadOnly(True)
        view.setPlainText(text)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(view, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        copy_button = QPushButton("Sao chép", dialog)
        copy_button.clicked.connect(
            lambda: QApplication.clipboard().setText(view.toPlainText())
        )
        row.addWidget(copy_button)
        close_button = QPushButton("Đóng", dialog)
        close_button.clicked.connect(dialog.close)
        row.addWidget(close_button)
        layout.addLayout(row)

        # Không modal: người dùng vẫn thao tác bảng chính; cửa sổ tự quản lý.
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _on_edit_task_clicked(self) -> None:
        task_id = self._get_selected_task_id()
        if task_id is None:
            return

        task = tasks_repo.get_task(self.conn, task_id)
        if task is None:
            return

        self.editing_task_id = task_id
        self.name_input.setText(task["name"])
        self.desc_input.setText(task["description"] or "")
        self.diff_spin.setValue(task["difficulty"])

        self.btn_save_task.setText("Lưu sửa")
        self.btn_cancel_edit.setVisible(True)
        # Tiêu đề QGroupBox không tự xuống dòng; tên dài sẽ kéo dãn cả tab,
        # nên cắt ngắn chỉ để nhận diện (tên đầy đủ đã nằm trong ô nhập).
        title_name = task["name"]
        if len(title_name) > 30:
            title_name = title_name[:30] + "…"
        self.form_group.setTitle(f"Sửa công việc: '{title_name}'")
        self.name_input.setFocus()

    def _on_cancel_edit_clicked(self) -> None:
        self.editing_task_id = None
        self.name_input.clear()
        self.desc_input.clear()
        self.diff_spin.setValue(1)
        self.btn_save_task.setText("Thêm việc")
        self.btn_cancel_edit.setVisible(False)
        self.form_group.setTitle("Thêm công việc mới")

    def _on_save_task_clicked(self) -> None:
        name = self.name_input.text().strip()
        diff = self.diff_spin.value()
        desc = self.desc_input.text().strip()

        try:
            if self.editing_task_id is None:
                new_id = tasks_repo.create_task(self.conn, name=name, description=desc, difficulty=diff)
                self.statusBar().showMessage(f"Đã thêm công việc: '{name}'.")
            else:
                tasks_repo.update_task(self.conn, self.editing_task_id, name=name, description=desc, difficulty=diff)
                self.statusBar().showMessage(f"Đã cập nhật công việc: '{name}'.")
                self._on_cancel_edit_clicked()
        except ValueError as exc:
            QMessageBox.warning(self, "Lỗi nhập liệu", str(exc))
            return

        self.name_input.clear()
        self.desc_input.clear()
        self.diff_spin.setValue(1)
        self._load_tasks()
        self._refresh_current_task_label()

    def _refresh_current_task_label(self) -> None:
        active_id = self.engine.current_task_id or self.selected_task_id
        if active_id is not None:
            task = tasks_repo.get_task(self.conn, active_id)
            if task:
                prefix = "Đang làm" if self.engine.state in (State.FOCUS, State.GRACE) else "Việc đã chọn"
                self.current_task_label.setText(
                    f"{prefix}: {task['name']} (Độ khó {task['difficulty']}/{config.TASK_DIFFICULTY_MAX})"
                )
                self.btn_deselect_task.setEnabled(True)
                return

        self.current_task_label.setText("Việc hiện tại: (Chưa chọn việc)")
        self.btn_deselect_task.setEnabled(False)

    @staticmethod
    def _house_text(floors: int) -> str:
        """Chuỗi hiển thị ngôi nhà; chỉ chạm trần 9999 mới báo "Đã đạt tối đa"."""
        if floors >= config.MAX_FLOORS:
            return f"Ngôi nhà Omnia: Tầng {floors} (Đã đạt tối đa)"
        return f"Ngôi nhà Omnia: Tầng {floors:,}"

    def _set_main_omnia_icon(
        self, kind: str, species: str | None = None, stage: int | None = None
    ) -> None:
        """Hiện sprite PNG của Omnia đang chọn, fallback sang icon SVG cùng bộ."""
        self.house_icon.setPixmap(
            self._creature_icon(
                kind, species, stage, self.house_icon.width()
            ).pixmap(self.house_icon.size())
        )

    @staticmethod
    def _creature_icon(
        kind: str,
        species: str | None = None,
        stage: int | None = None,
        size: int = 24,
    ) -> QIcon:
        """Tạo icon từ sprite PNG, dùng SVG đồng bộ nếu thiếu sprite."""
        pixmap = omnia_art.load_omnia_pixmap(
            kind, species, stage, display_size=size
        )
        if pixmap is not None:
            return QIcon(pixmap)
        return QIcon(str(config.ICON_DIR / f"{kind}.svg"))

    def _icon_heading(self, parent: QWidget, key: str, text: str) -> QWidget:
        """Dựng tiêu đề thẻ bằng icon SVG và chữ, không dùng emoji hệ thống."""
        heading = QWidget(parent)
        row = QHBoxLayout(heading)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        icon = QLabel(heading)
        icon.setFixedSize(20, 20)
        icon.setPixmap(
            QIcon(str(config.ICON_DIR / f"{key}.svg")).pixmap(icon.size())
        )
        row.addWidget(icon)
        label = QLabel(text, heading)
        label.setStyleSheet("font-weight: 700; font-size: 13px;")
        row.addWidget(label)
        row.addStretch(1)
        return heading

    def _refresh_house_display(self) -> None:
        """Cập nhật thẻ Nhà trong tab Omnia.
       
        Nếu Nhà đang là Omnia nhận tiến trình thì nhãn chính trên cột trái
        cũng hiển thị số tầng mới ngay (không phải chờ nhịp tick kế tiếp).
        """
        floors = house_repo.get_house_floors(self.conn)
        text = self._house_text(floors)
        tooltip = "Hoàn thành công việc để xây thêm các tầng mới vươn cao vô tận!"
        self.omnia_house_label.setText(text)
        self.omnia_house_label.setToolTip(tooltip)

        if settings_repo.get_active_omnia(self.conn) == "house":
            self.house_label.setText(text)
            self.house_label.setToolTip(tooltip)
            self._set_main_omnia_icon("house")

    def _refresh_main_omnia_display(self) -> None:
        """Màn hình chính hiển thị Omnia ĐANG nhận tiến trình (nhà/thú/cây)."""
        selected = settings_repo.get_active_omnia(self.conn)

        if selected == "house":
            text = self._house_text(house_repo.get_house_floors(self.conn))
            tooltip = "Hoàn thành công việc để xây thêm các tầng mới vươn cao vô tận!"
            self._set_main_omnia_icon("house")
        else:
            label = "Thú ảo" if selected == "pet" else "Cây trồng"
            active = creatures_repo.get_active_creature(self.conn, selected)
            if active is None:
                text = f"{label}: ô nuôi trống"
                tooltip = "Ô nuôi đang trống - hãy tạo hoặc chọn một con để nuôi."
                self._set_main_omnia_icon(selected)
            else:
                stage = int(active["stage"])
                growth = int(active["growth"])
                self._set_main_omnia_icon(selected, active["species"], stage)
                if stage >= 3:
                    text = (
                        f"{active['name']} — Trưởng thành"
                        f" · {growth:,} điểm"
                    )
                else:
                    threshold = config.GROWTH_THRESHOLDS[stage]
                    text = (
                        f"{active['name']} — {config.CREATURE_STAGE_LABELS[stage]}"
                        f" · {growth}/{threshold} điểm"
                    )
                tooltip = f"{label} đang nhận tiến trình: {active['name']}"

        self.house_label.setText(text)
        self.house_label.setToolTip(tooltip)

    # ------------------------------------------------------------------
    # Tab Omnia: nhà, thú ảo, cây trồng, bộ sưu tập
    # ------------------------------------------------------------------
    def _build_omnia_tab(self, parent: QWidget | None) -> QWidget:
        tab = QWidget(parent)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Nhà có ô riêng (thấp hơn), thú và cây chia đều phần còn lại.
        house_group = QGroupBox(tab)
        house_layout = QVBoxLayout(house_group)
        house_layout.addWidget(self._icon_heading(house_group, "house", "Ngôi nhà"))
        house_row = QHBoxLayout()
        self.omnia_house_label = QLabel("Ngôi nhà Omnia: Tầng 0", house_group)
        omnia_house_font = self.omnia_house_label.font()
        omnia_house_font.setPointSize(12)
        omnia_house_font.setBold(True)
        self.omnia_house_label.setFont(omnia_house_font)
        house_row.addWidget(self.omnia_house_label, stretch=1)

        self.btn_target_house = QPushButton("Nuôi nhà", house_group)
        self.btn_target_house.clicked.connect(
            lambda: self._on_choose_target_clicked("house")
        )
        house_row.addWidget(self.btn_target_house)
        house_layout.addLayout(house_row)
        house_group.setMaximumHeight(110)
        layout.addWidget(house_group)

        self.creature_widgets: dict[str, dict[str, QWidget]] = {
            "pet": self._build_creature_section(tab, layout, "pet", "Thú ảo"),
            "plant": self._build_creature_section(tab, layout, "plant", "Cây trồng"),
        }

        self.debug_points_button = QPushButton(
            f"Cộng điểm thử (+{config.DEBUG_ADD_POINTS})", tab
        )
        self.debug_points_button.setToolTip(
            "Chỉ hiện khi DEBUG = True. Gọi đúng core.reward.add_care_points() "
            "cho Omnia thú/cây đang chọn."
        )
        self.debug_points_button.clicked.connect(self._on_debug_add_points_clicked)
        self.debug_points_button.setVisible(config.DEBUG)
        layout.addWidget(self.debug_points_button)

        return tab

    def _build_collection_tab(self, parent: QWidget | None) -> QWidget:
        tab = QWidget(parent)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = self._icon_heading(
            tab, "collection", "Bộ sưu tập (sinh vật đã trưởng thành)"
        )
        layout.addWidget(title)

        self.collection_list = QListWidget(tab)
        self.collection_list.setIconSize(QSize(28, 28))
        self.collection_list.itemSelectionChanged.connect(
            self._on_collection_selection_changed
        )
        layout.addWidget(self.collection_list)

        self.btn_continue_collection = QPushButton("Nuôi tiếp con đã chọn", tab)
        self.btn_continue_collection.clicked.connect(
            self._on_continue_collection_clicked
        )
        layout.addWidget(self.btn_continue_collection)

        # Thả tự do: xóa hẳn con đã chọn (có hỏi xác nhận trước khi xóa).
        self.btn_release_collection = QPushButton("Thả tự do", tab)
        self.btn_release_collection.clicked.connect(
            self._on_release_collection_clicked
        )
        layout.addWidget(self.btn_release_collection)
        return tab

    def _build_notes_tab(self, parent: QWidget | None) -> QWidget:
        """Tab xem lại các ghi chú đã lưu trong lúc nghỉ."""
        tab = QWidget(parent)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        layout.addWidget(self._icon_heading(tab, "notes", "Ghi chú đã lưu trong lúc nghỉ"))

        # QSplitter: người dùng kéo được thanh chia giữa danh sách và nội dung.
        self.notes_splitter = QSplitter(Qt.Orientation.Horizontal, tab)

        # Trái: danh sách ghi chú gọn (thời gian + dòng đầu)
        left_panel = QWidget(self.notes_splitter)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_title = QLabel("Danh sách", left_panel)
        left_title.setStyleSheet("color: #888; font-size: 11px;")
        left_layout.addWidget(left_title)
        self.notes_list = QListWidget(left_panel)
        self.notes_list.itemSelectionChanged.connect(
            self._on_note_selection_changed
        )
        left_layout.addWidget(self.notes_list)
        self.notes_splitter.addWidget(left_panel)

        # Phải: đọc đầy đủ nội dung, có thanh cuộn
        right_panel = QWidget(self.notes_splitter)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.note_meta_label = QLabel("Chưa có ghi chú nào.", right_panel)
        self.note_meta_label.setWordWrap(True)
        self.note_meta_label.setStyleSheet("color: #777; font-size: 11px;")
        right_layout.addWidget(self.note_meta_label)

        self.notes_view = QPlainTextEdit(right_panel)
        self.notes_view.setReadOnly(True)
        self.notes_view.setPlaceholderText(
            "Chọn một ghi chú ở bên trái để xem đầy đủ."
        )
        right_layout.addWidget(self.notes_view, stretch=1)

        notes_buttons = QHBoxLayout()
        notes_buttons.setContentsMargins(0, 0, 0, 0)
        notes_buttons.setSpacing(8)

        self.btn_new_note = QPushButton("Tạo ghi chú", right_panel)
        self.btn_new_note.clicked.connect(self._on_new_note_clicked)
        notes_buttons.addWidget(self.btn_new_note)

        self.btn_open_note_window = QPushButton("Mở cửa sổ", right_panel)
        self.btn_open_note_window.setEnabled(False)
        self.btn_open_note_window.clicked.connect(
            self._open_selected_note_window
        )
        notes_buttons.addWidget(self.btn_open_note_window)
        right_layout.addLayout(notes_buttons)
        self.notes_splitter.addWidget(right_panel)

        # Tỉ lệ ban đầu 2:3 giống bố cục cũ; kéo được và không cho panel nào
        # co về 0 để luôn còn chỗ đọc.
        self.notes_splitter.setStretchFactor(0, 2)
        self.notes_splitter.setStretchFactor(1, 3)
        self.notes_splitter.setChildrenCollapsible(False)
        self.notes_splitter.splitterMoved.connect(self._on_notes_splitter_moved)

        layout.addWidget(self.notes_splitter, stretch=1)
        return tab

    def _build_creature_section(
        self, parent: QWidget, layout: QVBoxLayout, kind: str, title: str
    ) -> dict[str, QWidget]:
        group = QGroupBox(parent)
        box = QVBoxLayout(group)
        box.setSpacing(6)
        box.addWidget(self._icon_heading(group, kind, title))

        header = QHBoxLayout()
        sprite = QLabel(group)
        sprite.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sprite.setFixedWidth(70)
        sprite.setPixmap(
            QIcon(str(config.ICON_DIR / "add.svg")).pixmap(QSize(36, 36))
        )
        header.addWidget(sprite)

        info = QLabel("Chưa nuôi sinh vật nào.", group)
        info.setWordWrap(True)
        header.addWidget(info, stretch=1)

        target_button = QPushButton("Nuôi thú" if kind == "pet" else "Nuôi cây", group)
        target_button.clicked.connect(lambda: self._on_choose_target_clicked(kind))
        header.addWidget(target_button)
        box.addLayout(header)

        switch_row = QHBoxLayout()
        owned = QComboBox(group)
        owned.setToolTip("Chọn một sinh vật đang lớn (stage 1-2) để nuôi tiếp.")
        activate = QPushButton("Nuôi / Đổi sang con này", group)
        switch_row.addWidget(owned, stretch=2)
        switch_row.addWidget(activate, stretch=1)
        box.addLayout(switch_row)

        create_row = QHBoxLayout()
        species = QComboBox(group)
        for key, meta in config.CREATURE_SPECIES[kind].items():
            species.addItem(
                self._creature_icon(kind, key, 3), meta["label"], key
            )
        name_input = QLineEdit(group)
        name_input.setPlaceholderText("Tên sinh vật mới...")
        create = QPushButton("Nuôi sinh vật mới", group)
        create_row.addWidget(species, stretch=1)
        create_row.addWidget(name_input, stretch=2)
        create_row.addWidget(create, stretch=1)
        box.addLayout(create_row)

        layout.addWidget(group, 1)   # thú và cây chia đều chiều cao còn lại

        activate.clicked.connect(lambda: self._on_activate_creature_clicked(kind))
        create.clicked.connect(lambda: self._on_create_creature_clicked(kind))

        return {
            "group": group,
            "sprite": sprite,
            "info": info,
            "owned": owned,
            "activate": activate,
            "species": species,
            "name_input": name_input,
            "create": create,
            "target": target_button,
        }

    @staticmethod
    def _sprite_for(kind: str, species: str, stage: int) -> str:
        """Tra emoji sprite; giữ tên cũ, dùng chung với overlay Omnia."""
        return omnia_art.sprite_for(kind, species, stage)

    @staticmethod
    def _species_label(kind: str, species: str) -> str:
        meta = config.CREATURE_SPECIES.get(kind, {}).get(species)
        return meta["label"] if meta else species

    def _refresh_omnia_display(self) -> None:
        """Vẽ lại tab Omnia + màn hình chính từ CSDL."""
        selected = settings_repo.get_active_omnia(self.conn)
        self._refresh_house_display()
        self._refresh_main_omnia_display()
        for kind in config.CREATURE_KINDS:
            self._refresh_creature_section(kind)
        self._refresh_target_buttons(selected)
        self._refresh_collection()

    def _refresh_target_buttons(self, selected: str) -> None:
        """Hiển thị Omnia đang nhận tiến trình trên nút tương ứng."""
        house_active = selected == "house"
        self.btn_target_house.setText("Đang nuôi" if house_active else "Nuôi nhà")
        self.btn_target_house.setEnabled(not house_active)

        for kind, title in (("pet", "Nuôi thú"), ("plant", "Nuôi cây")):
            button = self.creature_widgets[kind]["target"]
            active = selected == kind
            button.setText("Đang nuôi" if active else title)
            button.setEnabled(not active)

    def _on_choose_target_clicked(self, kind: str) -> None:
        """Chọn 1 trong 3 Omnia để nhận tiến trình khi hoàn thành việc."""
        settings_repo.set_active_omnia(self.conn, kind)
        self._refresh_omnia_display()
        self._refresh_ui()
        label = {"house": "Ngôi nhà", "pet": "Thú ảo", "plant": "Cây trồng"}[kind]
        self.statusBar().showMessage(
            f"Từ giờ mọi việc hoàn thành sẽ cộng tiến trình cho {label}."
        )

    def _resolve_reward_target(self, difficulty: int) -> tuple[str, bool]:
        """Xác định Omnia nhận tiến trình; nhắc chọn nếu ô nuôi đang trống.

        Trả về (target, award). award=False nghĩa là người dùng chọn
        "giữ lựa chọn" và lần hoàn thành này không cộng tiến trình.
        """
        selected = settings_repo.get_active_omnia(self.conn)
        if selected == "house":
            return "house", True
        if creatures_repo.get_active_creature(self.conn, selected) is not None:
            return selected, True

        target, award = self._ask_empty_pen_choice(selected, difficulty)
        if award:
            # Mọi lựa chọn có trao thưởng đều trở thành Omnia đang nuôi.
            settings_repo.set_active_omnia(self.conn, target)
        return target, award

    def _ask_empty_pen_choice(self, kind: str, difficulty: int) -> tuple[str, bool]:
        """Hỏi nơi nhận tiến trình khi ô nuôi của thú/cây đang trống.

        Trả về (target, award). Các lựa chọn:
          - cộng số tầng vào Nhà
          - chọn một con đang lớn khác (nếu có)
          - tạo con nuôi mới
          - giữ lựa chọn hiện tại (không cộng lần này)
        """
        kind_label = "thú ảo" if kind == "pet" else "cây trồng"

        dialog = QDialog(self)
        dialog.setWindowTitle("Ô nuôi đang trống")
        layout = QVBoxLayout(dialog)
        layout.addWidget(
            QLabel(
                f"Ô nuôi {kind_label} đang trống.\n"
                "Chọn nơi nhận tiến trình của việc vừa hoàn thành:",
                dialog,
            )
        )

        group = QButtonGroup(dialog)

        radio_house = QRadioButton(f"Cộng {difficulty} tầng vào Nhà", dialog)
        group.addButton(radio_house)
        layout.addWidget(radio_house)

        existing = creatures_repo.list_creatures(self.conn, kind)
        radio_existing = QRadioButton("Chọn con đã có:", dialog)
        combo_existing = QComboBox(dialog)
        combo_existing.setIconSize(QSize(24, 24))
        for row in existing:
            stage = int(row["stage"])
            label = config.CREATURE_STAGE_LABELS[stage]
            if stage >= 3:
                label = "Trưởng thành"
            combo_existing.addItem(
                self._creature_icon(kind, row["species"], stage),
                f"{row['name']} ({label})",
                row["id"],
            )
        radio_existing.setEnabled(bool(existing))
        combo_existing.setEnabled(bool(existing))
        group.addButton(radio_existing)
        existing_row = QHBoxLayout()
        existing_row.addWidget(radio_existing)
        existing_row.addWidget(combo_existing, stretch=1)
        layout.addLayout(existing_row)

        radio_new = QRadioButton("Tạo con nuôi mới:", dialog)
        group.addButton(radio_new)
        layout.addWidget(radio_new)
        new_row = QHBoxLayout()
        species_combo = QComboBox(dialog)
        species_combo.setIconSize(QSize(24, 24))
        for key, meta in config.CREATURE_SPECIES[kind].items():
            species_combo.addItem(
                self._creature_icon(kind, key, 3), meta["label"], key
            )
        name_input = QLineEdit(dialog)
        name_input.setPlaceholderText("Tên sinh vật mới...")
        new_row.addWidget(species_combo, stretch=1)
        new_row.addWidget(name_input, stretch=2)
        layout.addLayout(new_row)

        radio_keep = QRadioButton(
            "Giữ lựa chọn hiện tại (không cộng tiến trình lần này)", dialog
        )
        group.addButton(radio_keep)
        layout.addWidget(radio_keep)

        radio_house.setChecked(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        while True:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return kind, False

            if radio_house.isChecked():
                return "house", True

            if radio_existing.isChecked():
                creature_id = combo_existing.currentData()
                if creature_id is None:
                    QMessageBox.warning(dialog, "Chưa chọn", "Chưa có con nào để chọn.")
                    continue
                try:
                    creatures_repo.activate_creature(self.conn, int(creature_id))
                except ValueError as exc:
                    QMessageBox.warning(dialog, "Không thể chọn", str(exc))
                    continue
                return kind, True

            if radio_new.isChecked():
                try:
                    creatures_repo.create_creature(
                        self.conn,
                        kind=kind,
                        species=species_combo.currentData(),
                        name=name_input.text(),
                    )
                except ValueError as exc:
                    QMessageBox.warning(dialog, "Lỗi nhập liệu", str(exc))
                    continue
                return kind, True

            return kind, False   # giữ lựa chọn, không cộng lần này

    def _refresh_creature_section(self, kind: str) -> None:
        widgets = self.creature_widgets[kind]
        active = creatures_repo.get_active_creature(self.conn, kind)

        if active is None:
            widgets["sprite"].setPixmap(
                QIcon(str(config.ICON_DIR / "add.svg")).pixmap(QSize(36, 36))
            )
            widgets["info"].setText(
                "Chưa nuôi sinh vật nào. Chọn loài, đặt tên rồi bấm 'Nuôi sinh vật mới'."
            )
        else:
            stage = int(active["stage"])
            growth = int(active["growth"])
            widgets["sprite"].setPixmap(
                self._creature_icon(kind, active["species"], stage, 64)
                .pixmap(QSize(64, 64))
            )
            stage_label = config.CREATURE_STAGE_LABELS.get(stage, "?")
            head = (
                f"{self._species_label(kind, active['species'])} '{active['name']}'"
            )
            if stage >= 3:
                widgets["info"].setText(
                    f"{head} — Trưởng thành\nChăm sóc: {growth:,} điểm"
                )
            else:
                threshold = config.GROWTH_THRESHOLDS[stage]
                widgets["info"].setText(
                    f"{head} — {stage_label}\nChăm sóc: {growth}/{threshold} điểm"
                )

        owned: QComboBox = widgets["owned"]
        owned.setIconSize(QSize(24, 24))
        previous_id = owned.currentData()
        owned.blockSignals(True)
        owned.clear()
        for row in creatures_repo.list_growing(self.conn, kind):
            suffix = " • đang nuôi" if row["is_active"] else ""
            owned.addItem(
                self._creature_icon(kind, row["species"], int(row["stage"])),
                f"{row['name']} ({config.CREATURE_STAGE_LABELS[int(row['stage'])]}){suffix}",
                row["id"],
            )
        owned.blockSignals(False)

        if previous_id is not None:
            index = owned.findData(previous_id)
            if index >= 0:
                owned.setCurrentIndex(index)

        widgets["activate"].setEnabled(owned.count() > 0)

    def _refresh_collection(self) -> None:
        """Đổ tab Bộ sưu tập: sinh vật trưởng thành (kể cả con đang nuôi tiếp)."""
        active_target = settings_repo.get_active_omnia(self.conn)
        self.collection_list.clear()
        for row in creatures_repo.list_collection(self.conn):
            kind_label = "Thú" if row["kind"] == "pet" else "Cây"
            # Chỉ hiển thị "đang nuôi" khi sinh vật vừa active vừa thuộc Omnia đang nhận tiến trình
            is_active = bool(row["is_active"]) and active_target == row["kind"]
            suffix = " • đang nuôi" if is_active else ""
            item = QListWidgetItem(
                f"{row['name']} — {self._species_label(row['kind'], row['species'])}"
                f" ({kind_label}, {int(row['growth']):,} điểm){suffix}"
            )
            item.setIcon(self._creature_icon(row["kind"], row["species"], 3))
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self.collection_list.addItem(item)
        has_items = self.collection_list.count() > 0
        self.btn_continue_collection.setEnabled(has_items)
        self.btn_release_collection.setEnabled(has_items)

    def _on_collection_selection_changed(self) -> None:
        has_selection = self.collection_list.currentItem() is not None
        self.btn_continue_collection.setEnabled(has_selection)
        self.btn_release_collection.setEnabled(has_selection)

    def _refresh_notes_display(self) -> None:
        """Đổ danh sách ghi chú, giữ dòng đang chọn nếu còn."""
        notes = [
            note
            for note in notes_repo.list_notes(self.conn)
            if note["content"].strip()
        ]

        current_item = self.notes_list.currentItem()
        current_id = (
            current_item.data(Qt.ItemDataRole.UserRole)
            if current_item is not None
            else None
        )

        self._note_texts = {}
        self.notes_list.blockSignals(True)
        self.notes_list.clear()
        for note in notes:
            note_id = int(note["id"])
            self._note_texts[note_id] = self._note_preview_text(note)
            item = QListWidgetItem(self._note_texts[note_id])
            item.setData(Qt.ItemDataRole.UserRole, note_id)
            item.setToolTip(note["content"].strip())
            self.notes_list.addItem(item)
        self.notes_list.blockSignals(False)
        self._fit_note_items()

        if notes:
            target_row = 0
            if current_id is not None:
                for row in range(self.notes_list.count()):
                    if (
                        self.notes_list.item(row).data(
                            Qt.ItemDataRole.UserRole
                        )
                        == current_id
                    ):
                        target_row = row
                        break
            self.notes_list.setCurrentRow(target_row)

        self._on_note_selection_changed()

    def _note_preview_text(self, note: sqlite3.Row) -> str:
        """Một dòng cho danh sách: thời gian · dòng đầu tiên của ghi chú."""
        content = note["content"].strip()
        first_line = content.splitlines()[0] if content else ""
        return f"{self._format_note_time(note['created_at'])} · {first_line}"

    def _fit_note_items(self) -> None:
        """Cắt chữ cho vừa bề ngang danh sách, kết thúc bằng "…" nếu bị che.

        QListWidget không tự elide khi cửa sổ hẹp: chữ tràn ra ngoài bị cắt
        cứng giữa ký tự. Ở đây đo bề rộng thực tế rồi nhờ Qt rút gọn bằng
        `fontMetrics().elidedText()`.
        """
        if not getattr(self, "_note_texts", None):
            return

        viewport_width = self.notes_list.viewport().width()
        # Cửa sổ chưa hiện/chưa bố cục xong thì bề ngang gần 0; cắt lúc này sẽ
        # mất chữ vĩnh viễn, nên chờ lần vẽ lại kế tiếp.
        if viewport_width <= 0:
            return

        metrics = self.notes_list.fontMetrics()
        available = max(60, viewport_width - 24)
        for row in range(self.notes_list.count()):
            item = self.notes_list.item(row)
            # Luôn elide từ chữ GỐC, không elide lại trên chữ đã cắt.
            full_text = self._note_texts.get(
                item.data(Qt.ItemDataRole.UserRole), item.text()
            )
            elided = metrics.elidedText(
                full_text, Qt.TextElideMode.ElideRight, available
            )
            if item.text() != elided:
                item.setText(elided)

    def _on_notes_splitter_moved(self, _pos: int, _index: int) -> None:
        self._fit_note_items()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Bố cục chưa cập nhật xong ngay trong resizeEvent: chờ một vòng sự
        # kiện để viewport có bề ngang thật rồi mới cắt chữ.
        QTimer.singleShot(0, self._fit_note_items)

    def _on_note_selection_changed(self) -> None:
        note = self._current_note()
        if note is None:
            self.notes_view.clear()
            self.note_meta_label.setText("Chưa có ghi chú nào.")
            self.btn_open_note_window.setEnabled(False)
            # Không còn ghi chú nào: đóng luôn cửa sổ nổi đang mở.
            if self.note_viewer is not None and self.note_viewer.isVisible():
                self.note_viewer.close()
            return

        self.notes_view.setPlainText(note["content"])
        self.note_meta_label.setText(self._note_meta_text(note))
        self.btn_open_note_window.setEnabled(True)

        # Cửa sổ nổi đang mở thì theo luôn ghi chú đang chọn (không mở thêm
        # cửa sổ mới). Nếu cửa sổ đang hiện ghi chú khác thì nạp lại, và tắt
        # chế độ sửa để không lưu nhầm nội dung sang ghi chú khác.
        viewer = self.note_viewer
        if viewer is not None and viewer.isVisible():
            if viewer.note_id != int(note["id"]):
                self._show_note_in_viewer(note)

    def _current_note(self) -> sqlite3.Row | None:
        item = self.notes_list.currentItem()
        if item is None:
            return None
        return notes_repo.get_note(
            self.conn, int(item.data(Qt.ItemDataRole.UserRole))
        )

    def _note_meta_text(self, note: sqlite3.Row) -> str:
        parts = [self._format_note_time(note["created_at"])]

        if note["task_id"] is not None:
            task = tasks_repo.get_task(self.conn, note["task_id"])
            parts.append(f"Việc: {task['name']}" if task else "Việc đã xóa")

        if note["session_id"] is not None:
            session = sessions_repo.get_session(self.conn, note["session_id"])
            if session is not None:
                parts.append(
                    f"Chu kỳ {session['cycle_index']}/{config.CYCLES_BEFORE_LONG_BREAK}"
                )
            else:
                parts.append(f"Phiên #{note['session_id']}")

        return " · ".join(parts)

    def _on_new_note_clicked(self) -> None:
        """Tạo ghi chú mới: mở hộp nhập, lưu rồi chọn dòng vừa tạo."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Ghi chú mới")
        dialog.resize(480, 360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        editor = QPlainTextEdit(dialog)
        editor.setPlaceholderText("Nhập nội dung ghi chú...")
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(editor, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        content = editor.toPlainText().strip()
        if not content:
            self.statusBar().showMessage("Ghi chú trống, chưa tạo.")
            return

        note_id = notes_repo.create_note(self.conn, content)
        self._refresh_notes_display()
        # Chọn đúng dòng vừa tạo để người dùng thấy ngay.
        for row in range(self.notes_list.count()):
            if (
                self.notes_list.item(row).data(Qt.ItemDataRole.UserRole)
                == note_id
            ):
                self.notes_list.setCurrentRow(row)
                break
        self.statusBar().showMessage("Đã tạo ghi chú mới.")

    def _open_selected_note_window(self) -> None:
        note = self._current_note()
        if note is None:
            return

        self._show_note_in_viewer(note)

    def _show_note_in_viewer(
        self, note: sqlite3.Row, *, editable: bool = False
    ) -> None:
        """Mở (hoặc nạp lại) cửa sổ nổi DUY NHẤT cho một ghi chú."""
        if self.note_viewer is None:
            self.note_viewer = NoteViewerWindow(self)
            self.note_viewer.edit_requested.connect(self._on_note_viewer_edit)
            self.note_viewer.save_requested.connect(self._on_note_viewer_save)
            self.note_viewer.delete_requested.connect(
                self._on_note_viewer_delete
            )

        self.note_viewer.show_note(
            note_id=int(note["id"]),
            title=f"Ghi chú — {self._format_note_time(note['created_at'])}",
            meta=self._note_meta_text(note),
            content=note["content"],
            editable=editable,
        )

    def _close_note_viewer(self) -> None:
        """Đóng cửa sổ nổi (không tự nạp sang ghi chú khác)."""
        if self.note_viewer is not None and self.note_viewer.isVisible():
            self.note_viewer.close()

    def _on_note_viewer_edit(self, note_id: int | None) -> None:
        """Cửa sổ nổi bấm Sửa: nạp lại nội dung mới nhất rồi bật chế độ sửa."""
        if note_id is None:
            return
        note = notes_repo.get_note(self.conn, int(note_id))
        if note is None:
            # Ghi chú đã bị xóa ở nơi khác: không hỏi xóa lại, chỉ làm mới tab
            # (tự đóng cửa sổ nổi nếu danh sách trống).
            self._refresh_notes_display()
            self.statusBar().showMessage("Ghi chú này không còn tồn tại.")
            return
        self._show_note_in_viewer(note, editable=True)

    def _on_note_viewer_save(self, note_id: int | None, content: str) -> None:
        """Cửa sổ nổi bấm Lưu: ghi nội dung mới (cho phép rỗng) rồi làm mới tab."""
        if note_id is None:
            return
        notes_repo.update_note(self.conn, int(note_id), content)

        note = notes_repo.get_note(self.conn, int(note_id))
        if note is not None:
            self.note_viewer.show_note(
                note_id=int(note["id"]),
                title=f"Ghi chú — {self._format_note_time(note['created_at'])}",
                meta=self._note_meta_text(note),
                content=note["content"],
            )
        self._refresh_notes_display()
        self.statusBar().showMessage("Đã lưu ghi chú.")

    def _on_note_viewer_delete(self, note_id: int | None) -> None:
        """Cửa sổ nổi bấm Xóa: xác nhận rồi xóa ghi chú khỏi CSDL."""
        if note_id is None:
            return
        note = notes_repo.get_note(self.conn, int(note_id))
        if note is None:
            self._refresh_notes_display()
            return

        reply = QMessageBox.question(
            self,
            "Xác nhận xóa ghi chú",
            "Bạn có chắc muốn xóa ghi chú này?\n\n(Hành động này không thể hoàn tác)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        notes_repo.delete_note(self.conn, int(note_id))
        # Đóng cửa sổ đang xem trước để tab không tự nạp ghi chú kế tiếp vào
        # một cửa sổ mà người dùng vừa xóa nội dung.
        self._close_note_viewer()
        self._refresh_notes_display()
        self.statusBar().showMessage("Đã xóa ghi chú.")

    @staticmethod
    def _format_note_time(created_at: str) -> str:
        """Đổi ISO-8601 UTC sang giờ địa phương để hiển thị."""
        moment = datetime.strptime(
            created_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        return moment.astimezone().strftime("%d/%m/%Y %H:%M")

    def _on_continue_collection_clicked(self) -> None:
        """Đưa sinh vật trưởng thành đã chọn trở lại ô nuôi để tăng điểm tiếp."""
        item = self.collection_list.currentItem()
        if item is None:
            self.statusBar().showMessage("Hãy chọn một sinh vật trong bộ sưu tập.")
            return

        creature_id = item.data(Qt.ItemDataRole.UserRole)
        row = creatures_repo.get_creature(self.conn, int(creature_id))
        if row is None:
            return

        creatures_repo.activate_creature(self.conn, int(creature_id))
        settings_repo.set_active_omnia(self.conn, row["kind"])
        self._open_tab_window("omnia")   # mở cửa sổ Omnia
        self._refresh_omnia_display()
        self._refresh_ui()
        self.statusBar().showMessage(f"Đang nuôi tiếp '{row['name']}'.")

    def _on_release_collection_clicked(self) -> None:
        """Thả tự do sinh vật đã chọn: xác nhận rồi xóa hẳn khỏi CSDL."""
        item = self.collection_list.currentItem()
        if item is None:
            self.statusBar().showMessage("Hãy chọn một sinh vật trong bộ sưu tập.")
            return

        creature_id = int(item.data(Qt.ItemDataRole.UserRole))
        row = creatures_repo.get_creature(self.conn, creature_id)
        if row is None:
            self._refresh_collection()
            return

        was_active = bool(row["is_active"])
        reply = QMessageBox.question(
            self,
            "Xác nhận thả tự do",
            f"Thả tự do '{row['name']}'?\n\n"
            "Sinh vật sẽ rời bộ sưu tập và không thể hoàn tác.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        creatures_repo.delete_creature(self.conn, creature_id)
        # Nếu vừa thả con đang nuôi: ô nuôi của loại đó trở về trống. Omnia
        # đang nhận tiến trình KHÔNG đổi (giữ nguyên nhà/thú/cây như cũ).
        self._refresh_omnia_display()
        self._refresh_collection()
        self.statusBar().showMessage(
            f"Đã thả tự do '{row['name']}'."
            + (" Ô nuôi đang trống." if was_active else "")
        )

    def _on_create_creature_clicked(self, kind: str) -> None:
        widgets = self.creature_widgets[kind]
        species = widgets["species"].currentData()
        name = widgets["name_input"].text()
        try:
            creatures_repo.create_creature(
                self.conn, kind=kind, species=species, name=name
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Lỗi nhập liệu", str(exc))
            return

        # Tạo con mới cũng là chọn Omnia đó nhận tiến trình.
        settings_repo.set_active_omnia(self.conn, kind)
        widgets["name_input"].clear()
        self._refresh_omnia_display()
        self.statusBar().showMessage(f"Đã bắt đầu nuôi '{name.strip()}'.")

    def _on_activate_creature_clicked(self, kind: str) -> None:
        widgets = self.creature_widgets[kind]
        creature_id = widgets["owned"].currentData()
        if creature_id is None:
            return
        try:
            creatures_repo.activate_creature(self.conn, int(creature_id))
        except ValueError as exc:
            QMessageBox.warning(self, "Không thể đổi sinh vật", str(exc))
            return

        settings_repo.set_active_omnia(self.conn, kind)
        self._refresh_omnia_display()
        self.statusBar().showMessage(
            "Đã đổi sinh vật đang nuôi (giữ nguyên tiến độ của con cũ)."
        )

    def _on_debug_add_points_clicked(self) -> None:
        target = settings_repo.get_active_omnia(self.conn)
        if target == "house":
            self.statusBar().showMessage(
                "Đang nuôi Nhà — chọn Thú hoặc Cây để dùng nút cộng điểm thử."
            )
            return

        rewards = reward.add_care_points(
            self.conn, config.DEBUG_ADD_POINTS, kind=target
        )
        self._refresh_omnia_display()

        if not rewards:
            self.statusBar().showMessage("Ô nuôi đang trống nên không cộng điểm thử.")
            return

        parts = []
        for item in rewards:
            emoji = "🐾" if item.kind == "pet" else "🌱"
            text = (
                f"{emoji} {item.name} +{item.added_points} điểm"
                f" (tổng {item.new_growth:,})"
            )
            parts.append(text)
        self.statusBar().showMessage("Cộng điểm thử: " + " | ".join(parts))
        self._notify_matured(rewards)

    def _notify_matured(self, rewards) -> None:
        """Hộp thoại báo khi sinh vật vừa đạt stage 3 (giống hộp thoại ô trống)."""
        adults = [r for r in rewards if r.became_adult]
        if not adults:
            return

        names = ", ".join(
            f"{'🐾' if r.kind == 'pet' else '🌱'} {r.name}" for r in adults
        )
        QMessageBox.information(
            self,
            "Omnia trưởng thành",
            f"🎉 {names} đã trưởng thành!\n"
            "Đã thêm vào bộ sưu tập và vẫn tiếp tục nhận điểm khi được nuôi.",
        )

    # ------------------------------------------------------------------
    # Xử lý click đồng hồ
    # ------------------------------------------------------------------
    def _on_start_clicked(self) -> None:
        self.overlay.hide_overlay()
        # Việc được chọn gắn vào engine khi bấm Bắt đầu (không bắt buộc chọn việc)
        effects = self.engine.handle(Event.START, task_id=self.selected_task_id)
        self._apply_effects(effects)
        self._refresh_ui()
        self._refresh_current_task_label()

    def _on_pause_clicked(self) -> None:
        if self.engine.state is State.PAUSED:
            self._send(Event.RESUME)
        else:
            self._send(Event.PAUSE)

    def _on_stop_clicked(self) -> None:
        self._send(Event.STOP)
        self.overlay.hide_overlay()
        # Ghi chú ghim không tự ẩn ở đây: _send() -> _refresh_ui() và nhịp
        # tick đã gọi _sync_transient_windows(), nơi duy nhất quyết định
        # hiện/ẩn theo engine.is_break_phase.
        self._sync_transient_windows()

    def _on_confirm_clicked(self) -> None:
        self._send(Event.CONFIRM)
        self.overlay.hide_overlay()
        # Đang nghỉ thì ghi chú vẫn phải hiện; hết nghỉ mới ẩn.
        self._sync_transient_windows()

    def _on_extend_requested(self, seconds: float) -> None:
        """Overlay chọn mốc gia hạn (chế độ Linh hoạt).

        Gia hạn xong thì ĐÓNG overlay ngay để không chắn màn hình khi người
        dùng quay lại làm việc. Đồng hồ chính hiện thời gian gia hạn còn lại.
        """
        effects = self.engine.handle(Event.EXTEND_FOCUS, seconds=seconds)
        applied = bool(effects)
        self._apply_effects(effects)

        if applied:
            self.overlay.hide_overlay(animate=False)
            self.statusBar().showMessage(
                "Đã gia hạn "
                f"{format_duration(self.engine.grace_extended_seconds)} focus "
                "- làm việc tiếp trên cửa sổ chính."
            )
        self._refresh_ui()

    def _on_skip_clicked(self) -> None:
        self._apply_effects(self.engine.fast_forward())
        self._refresh_ui()

    def _send(self, event: Event) -> None:
        self._apply_effects(self.engine.handle(event))
        self._refresh_ui()
        self._refresh_current_task_label()

    # ------------------------------------------------------------------
    # Nhịp tim của giao diện
    # ------------------------------------------------------------------
    def _on_tick(self) -> None:
        self._apply_effects(self.engine.update())
        self._sync_transient_windows()
        self._refresh_ui()

    def _apply_effects(self, effects: list[Effect]) -> None:
        """Ghi CSDL và hiện thông báo cho những gì engine vừa báo."""
        self.controller.apply(effects)

        for effect in effects:
            if isinstance(effect, CycleFinished):
                self.statusBar().showMessage(self._finished_message(effect))
                self._show_cycle_overlay(effect)
            elif isinstance(effect, NeedNewTask):
                self._refresh_current_task_label()
                self.statusBar().showMessage(
                    "Việc hiện tại đã xong. Đồng hồ vẫn chạy - chọn việc mới."
                )
            elif isinstance(effect, OpenQuickNote):
                self._open_quick_note()

    def _finished_message(self, effect: CycleFinished) -> str:
        if effect.next_state is State.IDLE:
            return "Hết nghỉ dài. Chu kỳ tiếp theo bắt đầu lại từ 1."
        if effect.next_state is State.LONG_BREAK:
            duration_str = format_duration(self.engine.long_break_seconds)
            return f"Hết giờ tập trung. Nghỉ dài {duration_str} nhé."
        if effect.next_state in BREAK_STATES:
            duration_str = format_duration(self.engine.short_break_seconds)
            return f"Hết giờ tập trung. Nghỉ {duration_str} nhé."
        return "Hết giờ nghỉ. Bấm Xác nhận để bắt đầu chu kỳ tiếp."

    # ------------------------------------------------------------------
    # Cửa sổ nổi: overlay hết chu kỳ + ghi chú ghim lúc nghỉ
    # ------------------------------------------------------------------
    def _omnia_for_overlay(self) -> dict:
        """Dữ liệu Omnia đang nhận tiến trình, để overlay hiển thị (không đụng CSDL)."""
        kind = settings_repo.get_active_omnia(self.conn)
        if kind == "house":
            floors = house_repo.get_house_floors(self.conn)
            return {
                "omnia_kind": "house",
                "omnia_name": "Ngôi nhà",
                "omnia_caption": f"{floors:,} tầng",
            }

        label = "Thú ảo" if kind == "pet" else "Cây trồng"
        active = creatures_repo.get_active_creature(self.conn, kind)
        if active is None:
            return {
                "omnia_kind": kind,
                "omnia_species": None,
                "omnia_name": label,
                "omnia_caption": "ô nuôi trống",
            }

        stage = int(active["stage"])
        growth = int(active["growth"])
        if stage >= 3:
            caption = f"Trưởng thành · {growth:,} điểm"
        else:
            caption = (
                f"{config.CREATURE_STAGE_LABELS[stage]}"
                f" · {growth}/{config.GROWTH_THRESHOLDS[stage]} điểm"
            )
        return {
            "omnia_kind": kind,
            "omnia_species": active["species"],
            "omnia_stage": stage,
            "omnia_name": active["name"],
            "omnia_caption": caption,
        }

    def _show_cycle_overlay(self, effect: CycleFinished) -> None:
        """Hiện overlay Omnia ở 1/4 màn hình bên phải."""
        auto_seconds = None
        if effect.next_state in BREAK_STATES:
            auto_seconds = self.engine.auto_confirm_seconds

        # Chế độ Linh hoạt vừa hết giờ focus: overlay là nơi chọn mốc gia hạn.
        extend_options = self.engine.extend_options_seconds

        self.overlay.show_cycle(
            effect,
            focus_seconds=self.engine.focus_seconds,
            short_break_seconds=self.engine.short_break_seconds,
            long_break_seconds=self.engine.long_break_seconds,
            auto_confirm_seconds=auto_seconds,
            extend_options=extend_options,
            extended_total=self.engine.grace_extended_seconds,
            **self._omnia_for_overlay(),
        )

    def _open_quick_note(self) -> None:
        """Focus vừa kết thúc: mở ô ghi chú nhanh cho bước đang làm dở.

        Nếu ô đang có nội dung CHƯA lưu (người dùng đang gõ dở) thì lưu dòng
        đó lại trước, rồi mới mở ô trống cho chu kỳ mới — không được xoá mất
        chữ người dùng vừa gõ.
        """
        # Lưu phần đang gõ trước; nếu lỗi thì _open_quick_note không chạy
        # tiếp để không mất chữ.
        self.pinned_note.flush_save()

        # Mỗi chu kỳ focus kết thúc là một ghi chú MỚI: ô trống, gắn với
        # session vừa đóng. Muốn xem ghi chú cũ thì dùng tab "Ghi chú".
        self.pinned_note.start_new_note(
            task_id=self.engine.current_task_id,
            session_id=self.controller.last_closed_session_id,
        )
        self._pinned_note_dismissed = False
        self.pinned_note.show_note(activate=True)

    def _current_duration_minutes(self, key: str) -> int:
        """Thời lượng (phút) đang áp dụng trong engine cho một giai đoạn."""
        seconds = {
            config.SETTING_FOCUS_MINUTES: self.engine.focus_seconds,
            config.SETTING_SHORT_BREAK_MINUTES: self.engine.short_break_seconds,
            config.SETTING_LONG_BREAK_MINUTES: self.engine.long_break_seconds,
        }[key]
        return max(1, round(seconds / 60))

    def _apply_saved_durations(self) -> bool:
        """Nạp thời lượng từ settings vào engine. Trả về True nếu đã áp dụng."""
        focus = settings_repo.get_duration_minutes(
            self.conn, config.SETTING_FOCUS_MINUTES, config.FOCUS_MINUTES
        )
        short = settings_repo.get_duration_minutes(
            self.conn, config.SETTING_SHORT_BREAK_MINUTES, config.SHORT_BREAK_MINUTES
        )
        long = settings_repo.get_duration_minutes(
            self.conn, config.SETTING_LONG_BREAK_MINUTES, config.LONG_BREAK_MINUTES
        )
        return self.engine.set_durations(
            focus_seconds=focus * 60,
            short_break_seconds=short * 60,
            long_break_seconds=long * 60,
        )

    def _open_settings_dialog(self) -> None:
        """Hộp thoại Cài đặt: thời lượng chu kỳ, chế độ, ghi chú ghim."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Cài đặt")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)

        duration_group = QGroupBox("Thời lượng chu kỳ (phút)", dialog)
        duration_layout = QFormLayout(duration_group)
        self.duration_spins: dict[str, QSpinBox] = {}
        # Giá trị lúc mở hộp thoại, để biết người dùng có sửa hay không.
        self._opened_duration_minutes: dict[str, int] = {}
        for key, label in (
            (config.SETTING_FOCUS_MINUTES, "Tập trung"),
            (config.SETTING_SHORT_BREAK_MINUTES, "Nghỉ ngắn"),
            (config.SETTING_LONG_BREAK_MINUTES, "Nghỉ dài"),
        ):
            minimum, maximum = config.DURATION_LIMITS_MINUTES[key]
            spin = QSpinBox(duration_group)
            spin.setRange(minimum, maximum)
            spin.setSuffix(" phút")
            current = self._current_duration_minutes(key)
            spin.setValue(current)
            spin.setKeyboardTracking(False)
            duration_layout.addRow(label, spin)
            self.duration_spins[key] = spin
            self._opened_duration_minutes[key] = current
        duration_hint = QLabel(
            "Thay đổi có hiệu lực từ chu kỳ kế tiếp (không cắt ngang "
            "giai đoạn đang chạy).",
            duration_group,
        )
        duration_hint.setWordWrap(True)
        duration_hint.setStyleSheet("color: #777; font-size: 11px;")
        duration_layout.addRow(duration_hint)
        layout.addWidget(duration_group)

        mode_group = QGroupBox("Chế độ Pomodoro", dialog)
        mode_layout = QVBoxLayout(mode_group)
        self.strict_radio = QRadioButton(config.POMODORO_MODES["strict"], mode_group)
        self.flexible_radio = QRadioButton(
            config.POMODORO_MODES["flexible"], mode_group
        )
        mode_buttons = QButtonGroup(mode_group)
        mode_buttons.addButton(self.strict_radio)
        mode_buttons.addButton(self.flexible_radio)
        if settings_repo.get_strict_mode(self.conn):
            self.strict_radio.setChecked(True)
        else:
            self.flexible_radio.setChecked(True)
        mode_layout.addWidget(self.strict_radio)
        mode_layout.addWidget(self.flexible_radio)
        mode_hint = QLabel(
            "Linh hoạt: khi hết giờ focus được gia hạn thêm "
            f"{format_duration(self.engine.grace_seconds)} để làm nốt.\n"
            "Đổi chế độ có hiệu lực từ chu kỳ focus kế tiếp.",
            mode_group,
        )
        mode_hint.setWordWrap(True)
        mode_hint.setStyleSheet("color: #777; font-size: 11px;")
        mode_layout.addWidget(mode_hint)
        layout.addWidget(mode_group)

        notes_group = QGroupBox("Ghi chú nhanh (lúc nghỉ)", dialog)
        notes_layout = QVBoxLayout(notes_group)
        self.autohide_checkbox = QCheckBox(
            "Tự ẩn ghi chú khi hết giờ nghỉ", notes_group
        )
        self.autohide_checkbox.setChecked(
            settings_repo.get_pinned_note_autohide(self.conn)
        )
        notes_layout.addWidget(self.autohide_checkbox)
        notes_hint = QLabel(
            "Bỏ chọn để ghi chú ở lại trên màn hình cả trong giờ làm việc;\n"
            "khi đó chỉ tắt bằng nút ✕ trên cửa sổ ghi chú.",
            notes_group,
        )
        notes_hint.setWordWrap(True)
        notes_hint.setStyleSheet("color: #777; font-size: 11px;")
        notes_layout.addWidget(notes_hint)
        layout.addWidget(notes_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        autohide = settings_repo.set_pinned_note_autohide(
            self.conn, self.autohide_checkbox.isChecked()
        )
        self._pinned_note_dismissed = False
        self._sync_transient_windows()

        # Lưu thời lượng CHỈ khi người dùng thực sự đổi giá trị; nếu không,
        # một lần bấm OK không được ghi đè thời lượng đang dùng (vd engine
        # được tiêm với giá trị khác config).
        durations_changed = False
        for key, spin in self.duration_spins.items():
            if spin.value() != self._opened_duration_minutes.get(key):
                settings_repo.set_duration_minutes(self.conn, key, spin.value())
                durations_changed = True

        if durations_changed:
            durations_applied = self._apply_saved_durations()
        else:
            durations_applied = True
        self._refresh_ui()

        strict = settings_repo.set_strict_mode(
            self.conn, self.strict_radio.isChecked()
        )
        # Áp dụng ngay nếu đồng hồ chưa chạy; nếu đang giữa chu kỳ thì chỉ
        # lưu lại, chế độ mới có hiệu lực từ chu kỳ focus kế tiếp.
        applied = self.engine.set_strict_mode(strict)
        self._refresh_ui()

        notes_msg = (
            "ghi chú tự ẩn khi hết giờ nghỉ"
            if autohide
            else "ghi chú giữ lại sau giờ nghỉ"
        )
        mode_msg = "Nghiêm ngặt" if strict else "Linh hoạt"
        if not applied:
            mode_msg += " (áp dụng từ chu kỳ kế tiếp)"
        if not durations_applied:
            duration_msg = "thời lượng đang chạy, sẽ áp dụng từ chu kỳ kế tiếp"
        else:
            duration_msg = (
                f"tập trung {self.duration_spins[config.SETTING_FOCUS_MINUTES].value()} phút"
            )
        self.statusBar().showMessage(
            f"Đã lưu cài đặt: {notes_msg}; {duration_msg}; chế độ {mode_msg}."
        )

    def _pinned_note_has_content(self) -> bool:
        """Ghi chú ghim có nội dung thật sự đã ghi không.

        Ô giữ chỗ mặc định của QPlainTextEdit (vd "Ghi bước đang làm dở...")
        không tính là nội dung.
        """
        text = self.pinned_note.editor.toPlainText().strip()
        placeholder = self.pinned_note.editor.placeholderText()
        return bool(text) and text != placeholder

    def _on_pinned_note_closed(self) -> None:
        """Người dùng bấm ✕ trên ghi chú ghim: tắt cho tới chu kỳ nghỉ sau."""
        self._pinned_note_dismissed = True
        self.pinned_note.hide_note()
        self.statusBar().showMessage(
            "Đã tắt ghi chú nhanh. Ghi chú sẽ hiện lại ở giờ nghỉ tiếp theo."
        )

    def _on_pinned_note_save_requested(
        self,
        note_id: int | None,
        content: str,
        task_id: int | None,
        session_id: int | None,
    ) -> None:
        """Ghi chú ghim phát signal -> lưu vào bảng notes."""
        if note_id is None:
            new_id = notes_repo.create_note(
                self.conn,
                content,
                task_id=task_id,
                session_id=session_id,
            )
            self.pinned_note.set_note_id(new_id)
        else:
            notes_repo.update_note(self.conn, int(note_id), content)

        self._refresh_notes_display()

    def _sync_transient_windows(self) -> None:
        """Bật/tắt ghi chú ghim và overlay theo trạng thái đồng hồ.

        Ghi chú ghim:
          - Trong giờ nghỉ: luôn hiện (trừ khi người dùng vừa tắt).
          - Ra khỏi giờ nghỉ: nếu setting tự ẩn BẬT thì ẩn; nếu TẮT thì giữ
            nguyên trên màn hình cho tới khi người dùng bấm nút tắt.
        """
        if self.engine.is_break_phase:
            # KHÔNG reset _pinned_note_dismissed ở đây: hàm này chạy mỗi nhịp
            # tick, reset sẽ làm nút ✕ vô hiệu (tắt xong tick sau hiện lại).
            # Cờ chỉ được reset khi BƯỚC VÀO giờ nghỉ mới (xem _apply_effects).
            if not self._pinned_note_dismissed:
                self.pinned_note.show_note()
        else:
            autohide = settings_repo.get_pinned_note_autohide(self.conn)
            keep_open = (
                not autohide
                and not self._pinned_note_dismissed
                and self._pinned_note_has_content()
            )
            if keep_open:
                self.pinned_note.show_note()
            else:
                self.pinned_note.hide_note()

        if not self.overlay.isVisible():
            return

        if self.engine.state is State.GRACE:
            # Chế độ Linh hoạt: overlay là bảng điều khiển gia hạn nên phải ở
            # lại KHI CHƯA chọn gì (đồng hồ đang dừng chờ). Nhưng đã bấm một
            # mốc gia hạn thì đồng hồ chạy và overlay phải đóng để làm việc.
            if self.engine.clock_is_running:
                self.overlay.hide_overlay()
            return

        if self.engine.awaiting_confirm:
            self.overlay.set_countdown(self.engine.seconds_until_auto_confirm)
        elif self.engine.state is not State.IDLE:
            # Nghỉ đã tự chạy hoặc người dùng đã xác nhận -> đóng overlay.
            self.overlay.hide_overlay()

    # ------------------------------------------------------------------
    # Vẽ lại từ trạng thái engine (một chiều: engine -> giao diện)
    # ------------------------------------------------------------------
    def _refresh_ui(self) -> None:
        engine = self.engine
        state = engine.state

        self.state_label.setText(STATE_LABELS[state])
        self.cycle_label.setText(
            f"Chu kỳ {engine.display_cycle_index}/{config.CYCLES_BEFORE_LONG_BREAK}"
        )

        clock_text = self._format_time(engine.phase_seconds)
        if clock_text != self.clock_label.text():
            self.clock_label.setText(clock_text)

        # Vòng tiến độ = phần thời gian đã trôi của giai đoạn hiện tại.
        # Lưu ý: engine.phase_seconds trả về REMAINING khi đang chạy, không
        # phải tổng, nên phải lấy tổng theo state từ các property độ dài.
        total = {
            State.FOCUS: engine.focus_seconds,
            State.GRACE: engine.grace_seconds,
            State.SHORT_BREAK: engine.short_break_seconds,
            State.LONG_BREAK: engine.long_break_seconds,
        }.get(state, 0.0)
        paused_from = engine.resume_state if state is State.PAUSED else None
        if state is State.PAUSED and paused_from is not None:
            total = {
                State.FOCUS: engine.focus_seconds,
                State.GRACE: engine.grace_seconds,
                State.SHORT_BREAK: engine.short_break_seconds,
                State.LONG_BREAK: engine.long_break_seconds,
            }.get(paused_from, 0.0)

        if total > 0 and state is not State.IDLE:
            self.clock_ring.set_progress(
                (total - engine.remaining_seconds) / total
            )
        else:
            self.clock_ring.set_progress(0.0)

        self._refresh_buttons(state)
        self._refresh_house_display()
        self._refresh_main_omnia_display()

    def _refresh_buttons(self, state: State) -> None:
        engine = self.engine
        running = state in (State.FOCUS, State.GRACE, State.SHORT_BREAK, State.LONG_BREAK)

        self.start_button.setEnabled(state is State.IDLE)
        self.pause_button.setEnabled((running and not engine.awaiting_confirm) or state is State.PAUSED)
        self.pause_button.setText("Tiếp tục" if state is State.PAUSED else "Tạm dừng")
        self.stop_button.setEnabled(state is not State.IDLE)

        # Nút "Tua hết giờ" chỉ hiện và kích hoạt trong chế độ DEBUG
        if config.DEBUG:
            can_skip = self.engine.clock_is_running or (
                self.engine.awaiting_confirm and self.engine.auto_confirm_at is not None
            )
            self.skip_button.setVisible(True)
            self.skip_button.setEnabled(can_skip)
            self.skip_shortcut.setEnabled(can_skip)
        else:
            self.skip_button.setVisible(False)
            self.skip_shortcut.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Xử lý đóng cửa sổ: dừng nhịp tim, lưu ghi chú, đóng cửa sổ nổi, dọn session."""
        self.tick_timer.stop()
        if self.note_viewer is not None:
            self.note_viewer.close()
        self.pinned_note.flush_save()
        self.overlay.hide_overlay(animate=False)
        self.pinned_note.close()

        is_focus_or_grace = self.engine.state in RUNNING_STATES
        is_paused_from_focus = (
            self.engine.state is State.PAUSED
            and self.engine.resume_state in RUNNING_STATES
        )
        if is_focus_or_grace or is_paused_from_focus:
            self._send(Event.STOP)
        super().closeEvent(event)

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Đổi số giây thành mm:ss, làm tròn LÊN để 25:00 hiện đủ 1 giây đầu."""
        total = max(0, int(math.ceil(seconds)))
        return f"{total // 60:02d}:{total % 60:02d}"
