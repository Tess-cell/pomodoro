"""
note_viewer.py - Cửa sổ nổi xem / sửa một ghi chú đã lưu (Mốc 7).

- Là cửa sổ thường (không modal), người dùng kéo/di chuyển và resize được.
- Nội dung dài có thanh cuộn; nút "Sao chép" chép toàn bộ ghi chú.
- Không đụng CSDL: cửa sổ chỉ giữ `note_id` của ghi chú đang xem và phát
  signal khi người dùng muốn Sửa / Lưu / Xóa. MainWindow gọi db/notes.py.

Signal/slot: trong PySide6, một widget phát `Signal` (tín hiệu) khi có sự kiện;
`MainWindow` nối (`connect`) tín hiệu đó vào một hàm xử lý (slot). Nhờ vậy cửa
sổ nổi không cần biết CSDL hay MainWindow tồn tại.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NoteViewerWindow(QWidget):
    """Cửa sổ nổi, resize/move tự do để đọc ghi chú dài."""

    # note_id (int | None)
    edit_requested = Signal(object)
    # note_id (int | None), nội dung mới (str)
    save_requested = Signal(object, str)
    # note_id (int | None)
    delete_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Ghi chú")
        self.resize(560, 440)

        self._note_id: int | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self.meta_label = QLabel("", self)
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(self.meta_label)

        self.editor = QPlainTextEdit(self)
        self.editor.setReadOnly(True)
        self.editor.setPlaceholderText("Chưa có nội dung.")
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.editor, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)

        self.copy_button = QPushButton("Sao chép", self)
        self.copy_button.clicked.connect(self._copy_content)
        button_row.addWidget(self.copy_button)

        self.edit_button = QPushButton("Sửa", self)
        self.edit_button.setCheckable(True)
        self.edit_button.clicked.connect(self._on_edit_clicked)
        button_row.addWidget(self.edit_button)

        self.save_button = QPushButton("Lưu", self)
        self.save_button.setVisible(False)
        self.save_button.clicked.connect(self._on_save_clicked)
        button_row.addWidget(self.save_button)

        self.delete_button = QPushButton("Xóa", self)
        self.delete_button.clicked.connect(self._on_delete_clicked)
        button_row.addWidget(self.delete_button)

        self.close_button = QPushButton("Đóng", self)
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.close_button)

        layout.addLayout(button_row)

    # ------------------------------------------------------------------
    # Nạp ghi chú
    # ------------------------------------------------------------------
    @property
    def note_id(self) -> int | None:
        """Id ghi chú đang hiển thị; None khi chưa có ghi chú nào."""
        return self._note_id

    def show_note(
        self,
        *,
        note_id: int | None,
        title: str,
        meta: str,
        content: str,
        editable: bool = False,
    ) -> None:
        """Nạp ghi chú, hiện cửa sổ và đưa lên trước.

        `editable=True` mở thẳng chế độ sửa (dùng khi bấm "Sửa" ở tab).
        Đổi sang ghi chú khác khi đang sửa thì chế độ sửa được đặt lại theo
        `editable` để tránh lưu nhầm nội dung sang ghi chú khác.
        """
        self._note_id = note_id
        self.setWindowTitle(title)
        self.meta_label.setText(meta)
        self.editor.setPlainText(content)
        self._set_editing(editable and note_id is not None)

        self.show()
        self.raise_()
        self.activateWindow()

    def _set_editing(self, editing: bool) -> None:
        self.editor.setReadOnly(not editing)
        self.edit_button.setChecked(editing)
        self.edit_button.setText("Hủy sửa" if editing else "Sửa")
        self.save_button.setVisible(editing)
        self.copy_button.setEnabled(not editing)

    # ------------------------------------------------------------------
    # Nút bấm
    # ------------------------------------------------------------------
    def _on_edit_clicked(self) -> None:
        if self._note_id is None:
            return
        if self.edit_button.isChecked():
            # Lấy nội dung mới nhất từ CSDL (qua MainWindow) rồi mới cho sửa.
            self.edit_requested.emit(self._note_id)
        else:
            self._set_editing(False)

    def _on_save_clicked(self) -> None:
        if self._note_id is None:
            return
        self.save_requested.emit(self._note_id, self.editor.toPlainText())
        self._set_editing(False)

    def _on_delete_clicked(self) -> None:
        if self._note_id is None:
            return
        self.delete_requested.emit(self._note_id)

    def _copy_content(self) -> None:
        QApplication.clipboard().setText(self.editor.toPlainText())

    def closeEvent(self, event) -> None:
        """Đóng cửa sổ khi đang sửa: lưu bản nháp thay vì mất im lặng.

        `QWidget.close()` mặc định chỉ ẩn cửa sổ, nên trạng thái sửa phải được
        chốt ở đây — giống ghi chú ghim tự lưu khi ẩn.
        """
        if not self.editor.isReadOnly() and self._note_id is not None:
            self.save_requested.emit(self._note_id, self.editor.toPlainText())
            self._set_editing(False)
        super().closeEvent(event)
