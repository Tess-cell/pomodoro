## 🚀 Hướng dẫn Cài đặt & Build

### 🛠 Cài đặt môi trường

1. Tạo môi trường ảo (Virtual Environment):
```bash
py -3 -m venv .venv
```

2. Cài đặt các thư viện cần thiết:
```bash
.venv\Scripts\python.exe -m pip install PySide6 pyinstaller pillow
```

### 📦 Build ứng dụng

Tiến hành đóng gói ứng dụng thông qua cấu hình `omnia.spec`:
```bash
.\.venv\Scripts\python.exe -m PyInstaller omnia.spec --noconfirm
```
