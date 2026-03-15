@echo off
setlocal
cd /d "%~dp0\.."

if not exist .venv (
  uv venv
)

call .venv\Scripts\activate.bat
uv pip install -r requirements.txt -r requirements-windows.txt
pyinstaller sf6_overlay.spec --noconfirm
if exist dist\sf6_overlay.zip del /q dist\sf6_overlay.zip
powershell -NoProfile -Command "Compress-Archive -Path dist\sf6_overlay.exe,config.json,matchups,templates -DestinationPath dist\sf6_overlay.zip -Force"

echo.
echo Build complete: dist\sf6_overlay.exe
echo Package complete: dist\sf6_overlay.zip
