Tạo file .exe:
Copy-Item temp\omnia.spec .
temp\.venv\Scripts\python.exe -m PyInstaller omnia.spec --noconfirm
