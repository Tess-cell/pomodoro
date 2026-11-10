"""
pinned_note.py - Cửa sổ ghi chú nhỏ ghim góc trên trái khi nghỉ.

Đặc điểm:
  - Không viền, luôn nằm trên cùng, kích thước nhỏ, ở góc trên trái màn hình
    nên không bị overlay Omnia (bên phải) che.
  - Chỉ hiện trong SHORT_BREAK / LONG_BREAK (kể cả lúc chờ xác nhận và PAUSED
    từ nghỉ); MainWindow quyết định bằng TimerEngine.is_break_phase.
  - Tự lưu sau NOTE_AUTOSAVE_MS kể từ lần gõ cuối. Widget này KHÔNG đụng CSDL:
    nó phát signal `save_requested(note_id, content, task_id, session_id)`,
    MainWindow gọi db/notes.py để ghi.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config


class PinnedNoteWindow(QWidget):
    """Ô ghi chú nhanh luôn nằm trên cùng ở góc trên trái."""

    # note_id (int | None), content, task_id (int | None), session_id (int | None)
    save_requested = Signal(object, str, object, object)

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(parent, flags)
        self.setObjectName("pinnedNote")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QWidget#pinnedNote {
                background-color: #fffbe6;
                border: 2px solid #e0b400;
                border-radius: 8px;
            }
            QLabel#pinnedTitle {
                color: #6b5200;
                font-size: 12px;
                font-weight: bold;
            }
            QPlainTextEdit {
                background-color: #fffdf2;
                color: #3a3200;
                border: 1px solid #e8d27a;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton#pinnedClose {
                background-color: transparent;
                color: #8a7300;
                border: none;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton#pinnedClose:hover { color: #5c4c00; }
            """
        )

        self._note_id: int | None = None
        self._task_id: int | None = None
        self._session_id: int | None = None
        self._last_saved_text = ""

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(config.NOTE_AUTOSAVE_MS)
        self._save_timer.timeout.connect(self._emit_save)

        # Cửa sổ không viền nên không có thanh tiêu đề hệ thống để kéo; ta tự
        # kéo bằng cách bắt chuột trên thanh tiêu đề tự vẽ.
        self._placed = False            # chỉ căn góc một lần đầu
        self._drag_offset = None        # điểm bấm - góc cửa sổ khi bắt đầu kéo

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 10)
        layout.setSpacing(6)

        # Thanh tiêu đề tự vẽ: giữ chuột và kéo để di chuyển cửa sổ.
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)

        self.title_label = QLabel("📝 Ghi chú nhanh (đang nghỉ)", self)
        self.title_label.setObjectName("pinnedTitle")
        self.title_label.setCursor(Qt.CursorShape.SizeAllCursor)
        self.title_label.setToolTip("Giữ chuột và kéo để di chuyển cửa sổ")
        self.title_label.setMinimumHeight(22)   # vùng bấm/kéo dễ trúng hơn
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        title_row.addWidget(self.title_label, stretch=1)

        # Người dùng chủ động tắt ghi chú ghim.
        self.close_button = QPushButton("✕", self)
        self.close_button.setObjectName("pinnedClose")
        self.close_button.setFixedSize(22, 22)
        self.close_button.setToolTip("Tắt ghi chú nhanh")
        # MainWindow nối nút này (_on_pinned_note_closed) để ghi nhớ người
        # dùng đã tắt; widget không tự quyết định.
        title_row.addWidget(self.close_button)
        layout.addLayout(title_row)

        self.editor = QPlainTextEdit(self)
        self.editor.setPlaceholderText("Ghi bước đang làm dở...")
        self.editor.textChanged.connect(self._schedule_save)
        layout.addWidget(self.editor, stretch=1)

        hint = QLabel("Tự lưu khi ngừng gõ", self)
        hint.setStyleSheet("color: #8a7300; font-size: 10px;")
        layout.addWidget(hint)

    # ------------------------------------------------------------------
    # Vòng đời ghi chú
    # ------------------------------------------------------------------
    def start_new_note(
        self,
        *,
        task_id: int | None = None,
        session_id: int | None = None,
    ) -> None:
        """Kết thúc ghi chú cũ (nếu có) và mở ô trống cho chu kỳ mới."""
        self.flush_save()

        self._note_id = None
        self._task_id = task_id
        self._session_id = session_id
        self._last_saved_text = ""

        self.editor.blockSignals(True)
        self.editor.clear()
        self.editor.blockSignals(False)

    def set_note_id(self, note_id: int | None) -> None:
        """MainWindow gọi sau khi tạo dòng mới trong bảng notes."""
        self._note_id = note_id

    def show_note(self, *, activate: bool = False) -> None:
        """Hiện cửa sổ; chỉ căn góc trên trái ở lần hiện ĐẦU TIÊN.

        Các lần sau giữ nguyên vị trí người dùng đã kéo.
        """
        if not self.isVisible():
            self.setFixedSize(config.PINNED_NOTE_WIDTH, config.PINNED_NOTE_HEIGHT)
            if not self._placed:
                rect = self._available_rect()
                self.move(
                    rect.x() + config.WINDOW_MARGIN,
                    rect.y() + config.WINDOW_MARGIN,
                )
                self._placed = True
            self.show()
            self.raise_()

        if activate:
            self.activateWindow()
            self.editor.setFocus()

    def hide_note(self) -> None:
        """Lưu phần đang gõ rồi ẩn cửa sổ (MainWindow điều khiển theo trạng thái)."""
        if self.isVisible():
            self.flush_save()
            self.hide()

    def flush_save(self) -> None:
        """Lưu ngay (bỏ qua debounce); dùng khi ẩn cửa sổ hoặc đóng app."""
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._emit_save()

    # ------------------------------------------------------------------
    # Tự lưu
    # ------------------------------------------------------------------
    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _emit_save(self) -> None:
        content = self.editor.toPlainText()
        if content == self._last_saved_text:
            return
        # Ghi chú mới mà rỗng thì chưa cần tạo dòng trong CSDL.
        if self._note_id is None and not content.strip():
            return

        self._last_saved_text = content
        self.save_requested.emit(
            self._note_id, content, self._task_id, self._session_id
        )

    # ------------------------------------------------------------------
    # Kéo cửa sổ bằng thanh tiêu đề tự vẽ
    # ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.title_label.geometry().contains(event.position().toPoint())
        ):
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:
        self.flush_save()
        super().closeEvent(event)

    @staticmethod
    def _available_rect() -> QRect:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 800, 600)
        return screen.availableGeometry()
