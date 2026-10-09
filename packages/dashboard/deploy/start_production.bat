@echo off
echo ============================================================
echo CREWAI PRODUCTION SERVER LAUNCHER
echo ============================================================
echo.

echo Checking if waitress is installed...
python -c "import waitress" 2>nul
if errorlevel 1 (
    echo Waitress not found. Installing production dependencies...
    call install_production.bat
)

echo.
echo Starting production server...
echo The web browser will open automatically to http://localhost:5000
echo.
echo Press Ctrl+C to stop the server
echo.

python production_server.py

echo.
echo Server stopped.
pause 