"""
omnia_art.py - Nạp ảnh PNG của Omnia cho overlay hết chu kỳ.

Quy ước tên file (xem assets/omnia/README.md):
    house.png
    pet_<species>_<stage>.png
    plant_<species>_<stage>.png

Thiếu ảnh là chuyện bình thường (người dùng đặt dần), nên hàm trả `None` để
nơi gọi tự lùi về emoji sprite. Không có exception nào bị nuốt ở đây: chỉ
kiểm tra tồn tại file rồi để QPixmap báo lỗi đọc ảnh qua `isNull()`.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

import config


def sprite_for(kind: str, species: str | None, stage: int | None) -> str:
    """Emoji sprite theo (kind, species, stage); loài lạ dùng bộ dự phòng."""
    if kind == "house":
        return "🏠"
    meta = config.CREATURE_SPECIES.get(kind, {}).get(species)
    if meta is None:
        return {1: "🥚", 2: "🐣", 3: "⭐"}.get(stage or 1, "❓")
    sprites = meta["sprites"]
    return sprites[min(max(stage or 1, 1), 3) - 1]


def omnia_art_filename(kind: str, species: str | None, stage: int | None) -> str:
    """Tên file ảnh theo quy ước. Nhà không có species/stage."""
    if kind == "house":
        return "house.png"
    if not species:
        return f"{kind}_unknown_{stage or 1}.png"
    return f"{kind}_{species}_{stage or 1}.png"


def omnia_art_path(
    kind: str,
    species: str | None = None,
    stage: int | None = None,
    *,
    art_dir: Path | None = None,
) -> Path:
    """Đường dẫn đầy đủ tới file ảnh (có thể chưa tồn tại)."""
    base = config.OMNIA_ART_DIR if art_dir is None else Path(art_dir)
    return base / omnia_art_filename(kind, species, stage)


def load_omnia_pixmap(
    kind: str,
    species: str | None = None,
    stage: int | None = None,
    *,
    art_dir: Path | None = None,
    display_size: int | None = None,
) -> QPixmap | None:
    """Trả ảnh đã thu nhỏ vừa `display_size`, hoặc None nếu chưa có ảnh.

    None cũng trả về khi file hỏng/không đọc được — overlay sẽ lùi về emoji.
    """
    path = omnia_art_path(kind, species, stage, art_dir=art_dir)
    if not path.is_file():
        return None

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None

    size = config.OMNIA_ART_DISPLAY_SIZE if display_size is None else display_size
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
