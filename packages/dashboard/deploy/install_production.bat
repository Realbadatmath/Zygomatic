@echo off
echo ============================================================
echo CREWAI PRODUCTION DEPENDENCIES INSTALLER
echo ============================================================
echo.

echo Installing core dependencies...
pip install Flask==3.0.0
pip install crewai==0.70.0
pip install langchain-ollama

echo.
echo Installing production server...
pip install waitress==3.0.0

echo.
echo Installing additional utilities...
pip install psutil==5.9.6
pip install flask-cors==4.0.0
pip install flask-limiter==3.5.0

echo.
echo Installation complete!
echo.
echo To start the production server, run:
echo start_production.bat
echo.
pause 