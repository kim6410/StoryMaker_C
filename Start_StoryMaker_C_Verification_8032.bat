@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] StoryMaker_C virtual environment not found.
    echo Expected: %CD%\.venv\Scripts\python.exe
    pause
    exit /b 1
)

echo ================================================
echo  StoryMaker_C Verification Server
echo  URL: http://127.0.0.1:8032
echo  Project: %CD%
echo ================================================
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8032

echo.
echo Verification server stopped.
pause
endlocal
