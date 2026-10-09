@echo off
title Kill Flask Processes
echo =============================================
echo   Kill Flask Processes on Port 5000
echo =============================================
echo.

echo Checking for Flask processes on port 5000...
python kill_flask.py

echo.
echo Process cleanup complete.
echo You can now restart the dashboard.
echo.
pause 