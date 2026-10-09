@echo off
REM Change to the project directory first. Override ZYG_PROJECT_DIR to run from
REM somewhere other than the default Desktop checkout.
if not defined ZYG_PROJECT_DIR set "ZYG_PROJECT_DIR=%USERPROFILE%\Desktop\Zygomatic Origin\Agents\crewai_project"
cd /d "%ZYG_PROJECT_DIR%"

title CrewAI Dashboard Launcher
:launcher
cls
echo =============================================
echo   CrewAI Dashboard Launcher
echo   With Integrated Timeline System
echo =============================================
echo.
echo Checking Python installation...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python and try again
    pause
    exit /b 1
)

echo Python found. Checking dependencies...
python -c "import flask" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo WARNING: Flask not found. Installing dependencies...
    pip install flask matplotlib numpy
)

echo.
echo =============================================
echo Starting CrewAI Dashboard...
echo =============================================
echo.
echo The dashboard will open automatically in your browser
echo If it doesn't open, go to: http://localhost:5000
echo.
echo Press Ctrl+C to stop the server
echo.

:run
REM PATCH: Run production_server.py instead of empty app.py
python production_server.py
set EXITCODE=%ERRORLEVEL%
echo.
echo Dashboard exited with code %EXITCODE%
if %EXITCODE%==100 (
    echo Restart requested. Relaunching dashboard in 3 seconds...
    timeout /t 3 /nobreak >nul
    goto run
) else (
    echo.
    echo Dashboard stopped. Press any key to exit...
    pause >nul
    exit /b %EXITCODE%
) 