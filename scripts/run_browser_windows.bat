@echo off
setlocal
cd /d "%~dp0\.."

if not exist .venv (
  uv venv
)

call .venv\Scripts\activate.bat
uv pip install -r requirements.txt
python app.py watch %*
