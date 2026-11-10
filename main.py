from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

import config
from db.database import init_db
from ui.main_window import MainWindow


def main() -> int:
    # QApplication phải được tạo trước mọi widget.
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    if config.APP_ICON_PATH.is_file():
        app.setWindowIcon(QIcon(str(config.APP_ICON_PATH)))

    # Theme: nạp QSS một lần cho toàn app (xem assets/style.qss). Thiếu file
    # thì chạy giao diện mặc định, không làm app không mở được.
    if config.STYLE_QSS_PATH.is_file():
        app.setStyleSheet(
            config.STYLE_QSS_PATH.read_text(encoding="utf-8")
        )
    app.setFont(QFont(config.THEME_FONT_FAMILY, 10))

    # Khởi tạo CSDL trước khi mở cửa sổ: cửa sổ không nên hiện ra khi
    # chưa có dữ liệu để đọc.
    try:
        conn = init_db()
    except Exception as exc:  # không nuốt lỗi: hiện nguyên văn cho người dùng
        QMessageBox.critical(
            None,
            "Không mở được CSDL",
            f"Không thể khởi tạo CSDL tại:\n{config.DB_PATH}\n\n{exc}",
        )
        return 1

    window = MainWindow(conn)
    window.show()

    # app.exec() chặn tại đây cho tới khi cửa sổ cuối cùng đóng.
    exit_code = app.exec()

    conn.close()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
