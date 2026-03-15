@echo off
setlocal

if not exist .venv (
  uv venv
)

call .venv\Scripts\activate.bat
uv pip install -r requirements.txt -r requirements-windows.txt
pyinstaller sf6_overlay.spec --noconfirm

echo.
echo Build complete: dist\sf6_overlay.exe
