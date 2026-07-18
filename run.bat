@echo off
REM Superfast Download Manager launcher
cd /d "%~dp0"

REM Use the bundled ffmpeg from the sibling project if present (optional).
if exist "..\download-manager\download-manager_workspace\bundle\bin\ffmpeg.exe" (
    set "SDM_FFMPEG=..\download-manager\download-manager_workspace\bundle\bin"
)

python main.py
if errorlevel 1 (
    echo.
    echo App exited with an error. If dependencies are missing, run:
    echo     pip install -r requirements.txt
    pause
)
