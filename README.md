Cài môi trường:

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install PySide6 pyinstaller pillow

Build:

.\.venv\Scripts\python.exe -m PyInstaller omnia.spec --noconfirm
