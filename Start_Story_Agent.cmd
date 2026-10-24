@echo off
setlocal
title Reverse 1999 Story Agent
cd /d "%~dp0"

if not exist ".venv\Scripts\r1999-agent.exe" (
    echo [ERROR] Agent environment was not found.
    echo Expected: %~dp0.venv\Scripts\r1999-agent.exe
    pause
    exit /b 1
)

set "R1999_DRY_RUN=false"
echo Starting Reverse 1999 story agent...
echo Keep MuMu Player and the game running.
echo Press Ctrl+C to stop.
echo.

".venv\Scripts\r1999-agent.exe" run story --max-steps 500

echo.
echo Agent stopped with exit code %ERRORLEVEL%.
pause
endlocal
