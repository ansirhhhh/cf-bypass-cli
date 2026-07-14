@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: ============================================================
::  cf-bypass-cli  Quick Launch (after setup)
::
::  Accepts optional URL as first argument:
::      run.bat https://example.com
::  If no URL is given, the monitor command prompts for it.
:: ============================================================

if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] First run? Please execute setup.bat first.
    echo.
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat

echo.
echo  +----------------------------------------------------+
echo        cf-bypass-cli  --  Monitor Quick Launch
echo  +----------------------------------------------------+
echo.

set TARGET_URL=%~1

if "%TARGET_URL%"=="" (
    echo   No URL supplied.  You will be prompted for one.
    echo   Alternatively: run.bat https://example.com
    echo.
    echo   Starting interactive monitor...
    echo.
    cf-bypass monitor
    goto :eof
)

echo   Target URL : %TARGET_URL%
echo   Starting interactive monitor...
echo.
cf-bypass monitor "%TARGET_URL%"
