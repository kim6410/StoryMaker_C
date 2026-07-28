@echo off
setlocal

set "PROJECT_DIR=F:\StoryMaker_C"
set "CLAUDE_EXE=C:\Users\kkbbq\.local\bin\claude.exe"

if not exist "%PROJECT_DIR%\" (
    echo [ERROR] Project folder not found:
    echo %PROJECT_DIR%
    pause
    exit /b 1
)

if not exist "%CLAUDE_EXE%" (
    echo [ERROR] Claude Code executable not found:
    echo %CLAUDE_EXE%
    pause
    exit /b 1
)

set "PATH=%PATH%;C:\Users\kkbbq\.local\bin"
cd /d "%PROJECT_DIR%"

echo ================================================
echo  Claude Code - StoryMaker_C
echo  Project: %CD%
echo ================================================
echo.

"%CLAUDE_EXE%"

echo.
echo Claude Code session ended.
pause
endlocal
