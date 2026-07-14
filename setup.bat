@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

:: ============================================================
::  cf-bypass-cli  one-click setup script
:: ============================================================

cd /d "%~dp0"

echo.
echo  +----------------------------------------------------+
echo        cf-bypass-cli  Setup Script
echo  +----------------------------------------------------+
echo.

:: --- Check Python ------------------------------------------------
echo [1/5] Checking Python environment...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo         Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

for /f "tokens=2" %%V in ('python --version 2^>^&1') do set PYVER=%%V
echo         Python %PYVER% OK
echo.

:: --- Create venv -------------------------------------------------
echo [2/5] Creating virtual environment...
if not exist ".venv" (
    python -m venv .venv
    echo         Virtual environment created OK
) else (
    echo         Virtual environment exists, skipped OK
)
echo.

:: --- Activate venv -----------------------------------------------
echo [3/5] Activating virtual environment...
call .venv\Scripts\activate.bat
echo.

:: --- Install dependencies ----------------------------------------
echo [4/5] Installing Python dependencies...
pip install -e . -q 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Dependency installation failed
    pause
    exit /b 1
)
echo         Dependencies installed OK
echo.

:: --- Install browser engine --------------------------------------
echo [5/5] Installing Playwright browser engine...
echo         Downloading Chromium (~150MB on first run, please wait)...
playwright install chromium 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Chromium installation failed. L3 strategy unavailable.
    echo           Manual install: playwright install chromium
) else (
    echo         Chromium installed OK
)
echo.

:: --- Done --------------------------------------------------------
echo  +----------------------------------------------------+
echo               Installation Complete!
echo  +----------------------------------------------------+
echo.
echo   Quick Start (recommended):
echo     run.bat                         Interactive monitor (prompts URL)
echo     run.bat https://example.com     Start monitor directly on URL
echo.
echo   Command line usage:
echo     cf-bypass monitor [url]         Interactive mode (/change etc.)
echo     cf-bypass https://example.com   Single-shot bypass (prints HTML)
echo     cf-bypass --cookie-only url     Single-shot cookie extraction
echo     cf-bypass serve --port 8191     HTTP API server
echo     cf-bypass status                Show stored cookies
echo     cf-bypass clear                 Clear cached cookies
echo     cf-bypass batch urls.txt -o results.csv   Batch process
echo.
echo   Monitor slash commands:
echo     /change [URL]   Close current page, open new URL
echo     /nav URL        Navigate (keep page)
echo     /status         Show current URL + cookies
echo     /bypass         Run L1..L4 bypass on current URL
echo     /reload /wait N /cookies /help /quit
echo.
echo   NOTE: Activate venv before each use:
echo     .venv\Scripts\activate
echo.
echo  +----------------------------------------------------+
echo.

:: Activate and keep console open
endlocal
call .venv\Scripts\activate.bat
echo Virtual environment activated. You can now use cf-bypass command.
echo.
cmd /k
