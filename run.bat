@echo off
cd /d "%~dp0"
if not exist .venv (
    echo [1/2] Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [2/2] Installing dependencies...
pip install -q -r requirements.txt
echo Starting StoryMaker Claude Lab on http://127.0.0.1:8031
python -m uvicorn app.main:app --host 127.0.0.1 --port 8031 --reload
pause
