"""
cycle_overlay.py - Cửa sổ Omnia trượt ra khi hết chu kỳ (Mốc 7).

Đặc điểm theo đặc tả:
  - Không viền, luôn nằm trên cùng, chiếm 1/4 màn hình phía bên phải.
  - Kích thước tính theo QScreen.availableGeometry() (không hard-code pixel).
  - Trượt vào/ra bằng QPropertyAnimation.
  - Nút X và nút "Xác nhận" đều phát signal `confirmed` để MainWindow xử lý.

UI này không tự gọi TimerEngine: nó chỉ hiển thị và báo ý định xác nhận,
giữ nguyên nguyên tắc "engine quyết định trạng thái".

Ở chế độ Linh hoạt, overlay là nơi chọn mốc gia hạn (1/2 phút trước nghỉ ngắn,
1..5 phút trước nghỉ dài) hoặc bắt đầu nghỉ ngay — phát `extend_requested(giây)`.

Bố cục Lời thoại Omnia (Speech Bubble):
  - Cửa sổ nền trong suốt (WA_TranslucentBackground).
  - Khối Omnia (ảnh PNG hoặc emoji + nhãn tên) neo ở góc dưới bên phải.
  - Thẻ thông báo / bong bóng thoại thu nhỏ nằm ngay phía trên Omnia với đuôi
    hướng xuống, trông như lời thoại trực tiếp từ Omnia.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config
from core.states import BREAK_STATES, State
from core.timer_engine import format_duration
from ui.omnia_art import load_omnia_pixmap, sprite_for


class SpeechBubbleCard(QWidget):
    """Thẻ thông báo dạng bong bóng thoại với đuôi hướng về Omnia."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.show_tail: bool = False

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        tail_h = 10 if self.show_tail else 0
        tail_w = 16
        w = float(self.width())
        h = float(self.height())

        body_rect = QRectF(2, 2, w - 4, h - tail_h - 4)
        path = QPainterPath()
        path.addRoundedRect(body_rect, 14, 14)

        if self.show_tail:
            tail = QPainterPath()
            tail_x = w - 64
            tail.moveTo(tail_x, h - tail_h - 2)
            tail.lineTo(tail_x + tail_w / 2, h - 2)
            tail.lineTo(tail_x + tail_w, h - tail_h - 2)
            tail.closeSubpath()
            bubble_path = path.united(tail)
        else:
            bubble_path = path

        painter.fillPath(bubble_path, QColor("#2b2f3a"))
        pen = QPen(QColor("#7c5cff"), 2)
        painter.setPen(pen)
        painter.drawPath(bubble_path)


class CycleOverlay(QWidget):
    """Thông báo hết giai đoạn, trượt từ mép phải màn hình vào."""

    confirmed = Signal()
    # Mốc gia hạn người dùng chọn (giây). Chỉ phát khi đang ở GRACE linh hoạt.
    extend_requested = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        super().__init__(parent, flags)
        self.setObjectName("cycleOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        # QWidget mặc định không nhận focus bàn phím -> phím Esc không tới
        # keyPressEvent. StrongFocus cho phép overlay tự nhận focus khi hiện.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet(
            """
            QWidget#cycleOverlay {
                background-color: transparent;
            }
            QWidget#overlayCard {
                background: transparent;
                border: none;
            }
            QLabel#overlayTitle {
                color: #ffffff;
                font-size: 16px;
                font-weight: bold;
                background: transparent;
            }
            QLabel#overlayMessage {
                color: #e8e8f0;
                font-size: 13px;
                background: transparent;
            }
            QLabel#overlayHint {
                color: #b9bcc9;
                font-size: 11px;
                background: transparent;
            }
            QLabel#overlayOmniaArt {
                background: transparent;
            }
            QLabel#overlayOmniaName {
                color: #cfc4ff;
                font-size: 12px;
                font-weight: bold;
                background-color: rgba(43, 47, 58, 0.9);
                border: 1px solid #7c5cff;
                border-radius: 8px;
                padding: 3px 8px;
            }
            QPushButton#overlayConfirm {
                background-color: #7c5cff;
                color: white;
                border: none;
                border-radius: 7px;
                padding: 7px 14px;
                font-size: 13px;
                font-weight: bold;
                min-height: 34px;
            }
            QPushButton#overlayConfirm:hover { background-color: #9074ff; }
            QPushButton#overlayClose {
                background-color: transparent;
                color: #d0d3de;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton#overlayClose:hover { color: #ffffff; }
            QPushButton#overlayExtend {
                background-color: #3a3f4d;
                color: #e8e8f0;
                border: 1px solid #7c5cff;
                border-radius: 7px;
                padding: 5px 8px;
                font-size: 12px;
                font-weight: bold;
                min-height: 28px;
            }
            QPushButton#overlayExtend:hover { background-color: #4a5064; }
            QPushButton#overlayExtend:disabled { color: #6d7282; border-color: #4a4f5e; }
            QPushButton#overlayExtend:checked {
                background-color: #7c5cff;
                color: #ffffff;
                border-color: #9074ff;
            }
            """
        )

        self._next_state: State | None = None
        self._auto_seconds: float | None = None
        self._base_hint = "Bấm Xác nhận để tiếp tục."
        self._hide_after_animation = False
        self._hiding = False
        # Chế độ gia hạn (chỉ bật khi hết giờ focus ở chế độ Linh hoạt)
        self._extend_options: tuple[float, ...] = ()
        self._extend_cap: float = 0.0
        self._extended_total: float = 0.0

        self._animation = QPropertyAnimation(self, b"pos", self)
        self._animation.setDuration(config.OVERLAY_ANIMATION_MS)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._on_animation_finished)

        self._build_ui()
        self.set_omnia(None)

    # ------------------------------------------------------------------
    # Dựng giao diện
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(6)
        main_layout.setAlignment(
            Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight
        )

        # Thẻ thông điệp / bong bóng thoại nằm ngay phía trên Omnia
        self.card = SpeechBubbleCard(self)
        self.card.setObjectName("overlayCard")
        self.card.setMaximumWidth(360)
        self.card.setMinimumWidth(280)
        card_layout = QVBoxLayout(self.card)
        # Lề dưới 18px để chừa chỗ cho đuôi bong bóng thoại (10px)
        card_layout.setContentsMargins(14, 10, 14, 18)
        card_layout.setSpacing(6)

        top_row = QHBoxLayout()
        self.title_label = QLabel("Hết giờ", self.card)
        self.title_label.setObjectName("overlayTitle")
        self.title_label.setWordWrap(True)
        top_row.addWidget(self.title_label, stretch=1)

        self.close_button = QPushButton("✕", self.card)
        self.close_button.setObjectName("overlayClose")
        self.close_button.setFixedSize(26, 26)
        self.close_button.setToolTip("Đóng và xác nhận")
        self.close_button.clicked.connect(self._confirm)
        top_row.addWidget(self.close_button)
        card_layout.addLayout(top_row)

        self.message_label = QLabel("", self.card)
        self.message_label.setObjectName("overlayMessage")
        self.message_label.setWordWrap(True)
        card_layout.addWidget(self.message_label)

        self.hint_label = QLabel("Bấm Xác nhận để tiếp tục.", self.card)
        self.hint_label.setObjectName("overlayHint")
        self.hint_label.setWordWrap(True)
        card_layout.addWidget(self.hint_label)

        # Hàng nút gia hạn (chỉ hiện ở chế độ Linh hoạt, khi vừa hết giờ focus).
        self.extend_row = QWidget(self.card)
        self.extend_row.setObjectName("overlayExtendRow")
        extend_layout = QHBoxLayout(self.extend_row)
        extend_layout.setContentsMargins(0, 0, 0, 0)
        extend_layout.setSpacing(6)
        self._selected_button: QPushButton | None = None
        self.extend_buttons: list[QPushButton] = []
        for minutes in config.LONG_GRACE_OPTIONS_MINUTES:
            button = QPushButton(f"+{minutes} phút", self.extend_row)
            button.setObjectName("overlayExtend")
            button.setCheckable(True)
            button.setMinimumHeight(28)
            button.setProperty("minutes", minutes)
            button.clicked.connect(self._on_extend_option_clicked)
            extend_layout.addWidget(button)
            self.extend_buttons.append(button)
        self.extend_row.setVisible(False)
        card_layout.addWidget(self.extend_row)

        self.confirm_button = QPushButton("Xác nhận", self.card)
        self.confirm_button.setObjectName("overlayConfirm")
        self.confirm_button.setMinimumHeight(34)
        self.confirm_button.clicked.connect(self._confirm)
        card_layout.addWidget(self.confirm_button)

        main_layout.addWidget(
            self.card, alignment=Qt.AlignmentFlag.AlignRight
        )

        # Khối Omnia ở góc dưới bên phải: ảnh PNG hoặc emoji, kèm nhãn tên.
        self.omnia_container = QWidget(self)
        self.omnia_container.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground, True
        )
        self.omnia_container.setStyleSheet("background: transparent;")
        omnia_layout = QVBoxLayout(self.omnia_container)
        omnia_layout.setContentsMargins(0, 0, 0, 0)
        omnia_layout.setSpacing(4)

        self.omnia_art = QLabel(self.omnia_container)
        self.omnia_art.setObjectName("overlayOmniaArt")
        self.omnia_art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.omnia_art.setFixedSize(
            config.OMNIA_ART_DISPLAY_SIZE, config.OMNIA_ART_DISPLAY_SIZE
        )
        omnia_layout.addWidget(
            self.omnia_art, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        self.omnia_label = QLabel("", self.omnia_container)
        self.omnia_label.setObjectName("overlayOmniaName")
        self.omnia_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.omnia_label.setWordWrap(True)
        omnia_layout.addWidget(
            self.omnia_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        main_layout.addWidget(
            self.omnia_container, alignment=Qt.AlignmentFlag.AlignRight
        )

    def set_omnia(
        self,
        kind: str | None,
        species: str | None = None,
        stage: int | None = None,
        name: str = "",
        caption: str = "",
    ) -> None:
        """Nạp khối Omnia: ảnh PNG nếu có, không thì emoji; kèm tên + phụ đề."""
        self.omnia_art.clear()
        self.omnia_label.clear()
        if not kind:
            self.omnia_art.setVisible(False)
            self.omnia_label.setVisible(False)
            self.omnia_container.setVisible(False)
            self.card.show_tail = False
            self.card.update()
            return

        pixmap = load_omnia_pixmap(kind, species, stage)
        if pixmap is not None:
            self.omnia_art.setPixmap(pixmap)
        else:
            self.omnia_art.setText(sprite_for(kind, species, stage))
            font = self.omnia_art.font()
            font.setPointSize(72)
            self.omnia_art.setFont(font)

        text = " · ".join(part for part in (name, caption) if part)
        self.omnia_label.setText(text)
        self.omnia_container.setVisible(True)
        self.omnia_art.setVisible(True)
        self.omnia_label.setVisible(bool(text))
        self.card.show_tail = True
        self.card.update()

    # ------------------------------------------------------------------
    # Hiển thị một giai đoạn vừa kết thúc
    # ------------------------------------------------------------------
    def show_cycle(
        self,
        effect,
        *,
        focus_seconds: float,
        short_break_seconds: float,
        long_break_seconds: float,
        auto_confirm_seconds: float | None,
        extend_options: tuple[float, ...] = (),
        extended_total: float = 0.0,
        omnia_kind: str | None = None,
        omnia_species: str | None = None,
        omnia_stage: int | None = None,
        omnia_name: str = "",
        omnia_caption: str = "",
    ) -> None:
        """Nạp nội dung theo CycleFinished và trượt vào từ mép phải.

        `extend_options` khác rỗng nghĩa là đang ở chế độ Linh hoạt: hiện
        hàng nút gia hạn thay cho "Xác nhận để bắt đầu nghỉ".

        Nhóm `omnia_*`: hình ảnh Omnia đang nhận tiến trình. Overlay chỉ hiển
        thị; MainWindow đọc CSDL rồi truyền vào (widget không đụng CSDL).
        """
        self.set_omnia(omnia_kind, omnia_species, omnia_stage, omnia_name, omnia_caption)
        self._next_state = effect.next_state
        self._auto_seconds = auto_confirm_seconds
        self._extend_options = tuple(extend_options)
        self._extend_cap = max(self._extend_options) if self._extend_options else 0.0
        self._extended_total = extended_total

        if effect.next_state is State.SHORT_BREAK:
            self.title_label.setText(
                f"Hết {format_duration(focus_seconds)} tập trung"
            )
            self.message_label.setText(
                f"Nghỉ ngắn {format_duration(short_break_seconds)} nhé."
            )
            self._base_hint = "Bấm Bắt đầu nghỉ khi đã sẵn sàng."
        elif effect.next_state is State.LONG_BREAK:
            self.title_label.setText(
                f"Hết {format_duration(focus_seconds)} tập trung"
            )
            self.message_label.setText(
                f"Nghỉ dài {format_duration(long_break_seconds)} nhé."
            )
            self._base_hint = "Bấm Bắt đầu nghỉ khi đã sẵn sàng."
        elif effect.next_state is State.FOCUS:
            self.title_label.setText(
                f"Hết {format_duration(short_break_seconds)} nghỉ"
            )
            self.message_label.setText("Sẵn sàng cho chu kỳ tập trung tiếp theo?")
            self._base_hint = "Đồng hồ chưa chạy - bấm Xác nhận để bắt đầu."
        else:
            self.title_label.setText(
                f"Hết {format_duration(long_break_seconds)} nghỉ"
            )
            self.message_label.setText("Chu kỳ tiếp theo bắt đầu lại từ 1.")
            self._base_hint = "Bấm Xác nhận để đóng thông báo."

        # Nhãn nút chính do _update_extend_buttons -> _sync_confirm_button lo:
        # "Bắt đầu nghỉ" khi chưa chọn mốc, "Gia hạn thêm" khi đã chọn.
        self._update_extend_buttons()

        if self._extend_options:
            self.hint_label.setText(self._extend_hint_text())
        elif (
            effect.next_state in BREAK_STATES
            and auto_confirm_seconds is not None
            and auto_confirm_seconds > 0
        ):
            self.hint_label.setText(
                f"Tự bắt đầu sau {format_duration(auto_confirm_seconds)} "
                "nếu bạn không bấm Xác nhận."
            )
        else:
            self.hint_label.setText(self._base_hint)

        rect = self._available_rect()
        # Kích thước mong muốn là 1/4 màn hình, nhưng KHÔNG được nhỏ hơn nội
        # dung: bong bóng + ảnh Omnia + hàng nút gia hạn có thể cao ~410px.
        # Dùng minimumSizeHint() thay vì setFixedSize để Qt không cắt mất nút
        # chính trên màn hình thấp (trước đây ép 260px và mất phần đáy).
        hint = self.minimumSizeHint()
        width = max(
            config.OVERLAY_MIN_WIDTH,
            rect.width() // config.OVERLAY_SCREEN_FRACTION,
            hint.width(),
        )
        height = max(
            config.OVERLAY_MIN_HEIGHT,
            rect.height() // config.OVERLAY_SCREEN_FRACTION,
            hint.height(),
        )
        # Không vượt quá màn hình khả dụng (màn hình rất thấp), nhưng nếu nội
        # dung vẫn cao hơn thì ưu tiên nội dung để không mất nút bấm.
        width = min(width, rect.width())
        height = min(height, rect.height())
        self.setFixedSize(width, height)

        # Góc dưới bên phải: mỗi chiều 1/2 -> diện tích đúng 1/4 màn hình.
        top = rect.y() + rect.height() - height
        start = QPoint(rect.x() + rect.width(), top)
        end = QPoint(rect.x() + rect.width() - width, top)

        self._hiding = False
        self._hide_after_animation = False
        self._animation.stop()
        self.move(start)
        self.show()
        self.raise_()
        self.activateWindow()
        # Để Esc tới được keyPressEvent (widget không tự nhận focus).
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

        self._animation.setStartValue(start)
        self._animation.setEndValue(end)
        self._animation.start()

    # ------------------------------------------------------------------
    # Gia hạn (chế độ Linh hoạt)
    # ------------------------------------------------------------------
    def _extend_hint_text(self) -> str:
        """Dòng gợi ý cho chế độ gia hạn."""
        if self.selected_extend_seconds is not None:
            return (
                f"Đã chọn gia hạn {format_duration(self.selected_extend_seconds)}. "
                'Bấm "Gia hạn thêm" để bắt đầu, hoặc "Bắt đầu nghỉ".'
            )
        if self._extended_total <= 0:
            return (
                "Hết giờ nhưng bạn đang dở tay: chọn mốc gia hạn, "
                'rồi bấm "Gia hạn thêm" để xác nhận.'
            )
        return (
            f"Đã gia hạn {format_duration(self._extended_total)}. "
            "Có thể chọn mốc khác hoặc bắt đầu nghỉ."
        )

    @property
    def selected_extend_seconds(self) -> float | None:
        """Mốc đang được chọn (giây) nhưng CHƯA xác nhận; None nếu chưa chọn."""
        button = self._selected_button
        if button is None or not button.isVisible() or not button.isChecked():
            return None
        return float(button.property("minutes")) * 60

    def _on_extend_option_clicked(self) -> None:
        """Chỉ đánh dấu mốc được chọn và đổi nhãn nút chính — chưa gia hạn.

        Bấm lại đúng nút đang chọn nghĩa là bỏ chọn.
        """
        clicked = self.sender()
        if clicked is self._selected_button and not clicked.isChecked():
            self._selected_button = None        # bấm lại -> huỷ chọn
        else:
            self._selected_button = clicked
        for button in self.extend_buttons:
            if button is not self._selected_button:
                button.setChecked(False)
            else:
                button.setChecked(True)

        self._sync_confirm_button()
        if self._extend_options:
            self.hint_label.setText(self._extend_hint_text())

    def _sync_confirm_button(self) -> None:
        """Nút chính: "Gia hạn thêm" khi đã chọn mốc, ngược lại "Bắt đầu nghỉ"."""
        if self.selected_extend_seconds is not None:
            self.confirm_button.setText("Gia hạn thêm")
        elif self._extend_options:
            self.confirm_button.setText("Bắt đầu nghỉ")
        else:
            self.confirm_button.setText("Xác nhận")

    def _update_extend_buttons(self) -> None:
        """Hiện/ẩn hàng nút gia hạn và khoá mốc vượt hạn mức còn lại.

        Luôn gọi `_sync_confirm_button()` ở cuối, kể cả khi KHÔNG có chế độ
        gia hạn: nếu return sớm, nhãn nút chính sẽ giữ nguyên giá trị của
        trạng thái TRƯỚC (vd "Gia hạn thêm" còn sót lại ở màn hình nghỉ).
        """
        enabling = bool(self._extend_options)
        self.extend_row.setVisible(enabling)
        if not enabling:
            self._selected_button = None
            for button in self.extend_buttons:
                button.setChecked(False)
            self._sync_confirm_button()
            return

        remaining = self._extend_cap - self._extended_total
        for button, seconds in zip(self.extend_buttons, self._options_for_buttons()):
            allowed = seconds in self._extend_options and seconds <= remaining
            button.setVisible(seconds in self._extend_options)
            button.setEnabled(allowed)
            if not allowed:
                button.setChecked(False)
                if button is self._selected_button:
                    self._selected_button = None
            button.setToolTip(
                f"Chọn gia hạn {format_duration(seconds)} focus"
                if seconds <= remaining
                else f"Vượt hạn mức {format_duration(self._extend_cap)} mỗi chu kỳ"
            )
        self._sync_confirm_button()

    def _options_for_buttons(self) -> tuple[float, ...]:
        """Mốc tương ứng từng nút cố định (+1..+5 phút), theo thứ tự tạo."""
        return tuple(m * 60 for m in config.LONG_GRACE_OPTIONS_MINUTES)

    def set_extend_state(
        self, *, options: tuple[float, ...], extended_total: float
    ) -> None:
        """Cập nhật lại sau khi người dùng xác nhận một mốc gia hạn."""
        self._extend_options = tuple(options)
        self._extended_total = extended_total
        self._selected_button = None
        for button in self.extend_buttons:
            button.setChecked(False)
        self._update_extend_buttons()
        if self._extend_options:
            self.hint_label.setText(self._extend_hint_text())

    def set_countdown(self, seconds: float | None) -> None:
        """Cập nhật dòng gợi ý đếm ngược tự xác nhận (chỉ giai đoạn nghỉ)."""
        if self._extend_options:
            return
        if self._next_state not in BREAK_STATES or not self._auto_seconds:
            return
        if seconds is None:
            text = self._base_hint
        else:
            text = (
                f"Tự bắt đầu sau {format_duration(seconds)} "
                "nếu bạn không bấm Xác nhận."
            )
        if self.hint_label.text() != text:
            self.hint_label.setText(text)

    def keyPressEvent(self, event) -> None:
        """Esc = bấm nút chính (giống ✕ / Xác nhận).

        Chỉ hoạt động khi overlay đang có focus, nên gõ Esc ở cửa sổ chính
        hay ô ghi chú không vô tình đóng overlay.
        """
        if event.key() == Qt.Key.Key_Escape:
            self._confirm()
            event.accept()
            return
        super().keyPressEvent(event)

    def hide_overlay(self, *, animate: bool = True) -> None:
        """Ẩn overlay; animate=False dùng cho test hoặc khi cần đóng ngay."""
        if not self.isVisible() or self._hiding:
            return

        if not animate:
            self._animation.stop()
            self.hide()
            return

        rect = self._available_rect()
        target = QPoint(rect.x() + rect.width(), self.y())
        self._hiding = True
        self._hide_after_animation = True
        self._animation.stop()
        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(target)
        self._animation.start()

    # ------------------------------------------------------------------
    # Nội bộ
    # ------------------------------------------------------------------
    def _confirm(self) -> None:
        """Nút chính: xác nhận mốc gia hạn đang chọn, hoặc bắt đầu nghỉ."""
        selected = self.selected_extend_seconds
        if selected is not None and self._extend_options:
            self.extend_requested.emit(selected)
            return
        self.confirmed.emit()

    def _on_animation_finished(self) -> None:
        self._hiding = False
        if self._hide_after_animation:
            self._hide_after_animation = False
            self.hide()

    @staticmethod
    def _available_rect() -> QRect:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QRect(0, 0, 800, 600)
        return screen.availableGeometry()
