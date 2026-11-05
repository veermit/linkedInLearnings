@echo off
REM Builds dist\LinkedInLearningDownloader.exe  (run this ON a Windows PC with Python 3.9+ installed)
cd /d "%~dp0"
python -m venv .build_venv || goto :err
call .build_venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :err
pyinstaller --noconfirm --clean --onefile --windowed --name LinkedInLearningDownloader ^
  --collect-all yt_dlp --collect-all browser_cookie3 llcd_gui.py || goto :err
echo.
echo DONE. Share this file:  %~dp0dist\LinkedInLearningDownloader.exe
pause
exit /b 0
:err
echo BUILD FAILED. Make sure Python 3.9+ is installed and on PATH.
pause
exit /b 1
