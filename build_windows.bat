@echo off
setlocal
REM ============================================================
REM  Builds dist\LinkedInLearningDownloader.exe  (single file)
REM  Run this ON Windows. Needs Python 3.9+ (python.org installer,
REM  "Add python.exe to PATH" ticked, Tcl/Tk included by default).
REM ============================================================
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo Python not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  goto :err
)

%PY% -c "import tkinter" 2>nul || (
  echo This Python has no Tkinter. Re-run the python.org installer, choose Modify, and enable "tcl/tk and IDLE".
  goto :err
)

echo Creating build environment...
if exist .build_venv rmdir /s /q .build_venv
%PY% -m venv .build_venv || goto :err
call .build_venv\Scripts\activate.bat || goto :err

python -m pip install --upgrade pip || goto :err
python -m pip install -r requirements.txt || goto :err

echo Building executable (takes a few minutes)...
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name LinkedInLearningDownloader ^
  --collect-all yt_dlp --collect-all browser_cookie3 ^
  llcd_gui.py || goto :err

if not exist "dist\LinkedInLearningDownloader.exe" goto :err
echo.
echo ============================================================
echo  DONE. Share this file:
echo  %~dp0dist\LinkedInLearningDownloader.exe
echo ============================================================
pause
exit /b 0

:err
echo.
echo BUILD FAILED - see the messages above.
pause
exit /b 1
