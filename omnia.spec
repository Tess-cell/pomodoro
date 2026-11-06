# -*- mode: python ; coding: utf-8 -*-
# spec đóng gói Pomodoro Omnia bằng PyInstaller.
# Chạy:  .\.venv\Scripts\pyinstaller omnia.spec
#
# add-data: assets/ (qss, icons, ảnh Omnia) và db/schema.sql vào gói, vì app
# đọc chúng theo đường dẫn tương đối (xem config.RESOURCE_DIR và
# db/database.SCHEMA_PATH). CSDL người dùng KHÔNG gói kèm — tạo lúc chạy cạnh .exe.

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("assets", "assets"),              # style.qss, app_icon.png, icons/, omnia/
        ("db/schema.sql", "db"),           # nạp schema khi tạo CSDL
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PomodoroOmnia",
    # Icon hiển thị cho file .exe trong Explorer (khác icon cửa sổ app lúc chạy,
    # cái đó do main.py setWindowIcon lấy từ assets/app_icon.png).
    icon="assets/app_icon.png",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,                         # app GUI: không mở cửa sổ console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
