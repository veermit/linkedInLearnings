#!/bin/bash
# Builds dist/LinkedInLearningDownloader.app (+ .zip to share). Needs a Python with Tk (python.org installer).
set -e
cd "$(dirname "$0")"
PY=""
for c in /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 python3; do
  if "$c" -c "import tkinter" 2>/dev/null; then PY="$c"; break; fi
done
[ -z "$PY" ] && { echo "No Python with Tk found. Install Python from python.org."; exit 1; }
"$PY" -m venv .build_venv
source .build_venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pyinstaller --noconfirm --clean --windowed --name LinkedInLearningDownloader \
  --collect-all yt_dlp --collect-all browser_cookie3 llcd_gui.py
(cd dist && rm -f LinkedInLearningDownloader.zip && ditto -c -k --keepParent LinkedInLearningDownloader.app LinkedInLearningDownloader.zip)
echo "DONE: $(pwd)/dist/LinkedInLearningDownloader.zip"
