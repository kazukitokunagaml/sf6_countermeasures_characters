@echo off
setlocal
cd /d "%~dp0\.."

if not exist .venv (
  uv venv
)

call .venv\Scripts\activate.bat
uv pip install -r requirements.txt -r requirements-windows.txt
python app.py desktop-overlay %*
