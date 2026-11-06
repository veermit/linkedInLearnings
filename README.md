# LinkedIn Learning Downloader (Python GUI)

A desktop app (Python + Tkinter) that downloads LinkedIn Learning **courses** and **whole learning paths** for offline viewing, plus a second tab for YouTube / Instagram / Facebook videos (via yt-dlp).

Endpoints and folder layout are ported from
[ahmedayman4a/Linkedin-Learning-Courses-Downloader](https://github.com/ahmedayman4a/Linkedin-Learning-Courses-Downloader).
Use it only with **your own** LinkedIn Learning subscription, for personal offline viewing.

## Features

- Paste a **course** link or a **learning path** link (e.g. `https://www.linkedin.com/learning/paths/atlassian-agile-project-management-professional-certificate`) and the whole thing is downloaded.
- Lesson links work too (`.../learning/<course>/<lesson>`): the full course is downloaded.
- **Queue**: add as many courses/paths as you like (Add, Enter, or "Paste several"); they download one by one, in order. Remove or clear entries before starting.
- Video quality 720 / 540 / 360, optional subtitles (`.srt`) and exercise files.
- Resumable: files that already exist are skipped, so you can stop and re-run.
- **Summary at the end** (log + popup): how many courses succeeded / were partial / failed, with each link and the reason.
- **Clear log** button on both tabs.
- "Get from browser" token import (Safari, Firefox, Chrome/Edge).

## Output layout

```
<chosen folder>/
  <Learning path title>/            (only for path links)
    01 - <Course title>/
      01 - <Chapter>/
        01 - <Video>.mp4
        01 - <Video>.srt
      <exercise files>
      _exercise_files_NOT_downloaded.txt   (only if some could not be fetched)
    02 - <Course title>/ ...
  <Course title>/                   (for single course links)
```

## Quick start (run from source)

Requires Python 3.9+ **with Tkinter** (python.org installers include it; Homebrew Python needs `brew install python-tk`).

```bash
python3 -m pip install requests yt-dlp          # yt-dlp only for the YouTube/Instagram tab
python3 llcd_gui.py                             # Windows: python llcd_gui.py
```

## How to use

1. **Get your login token (`li_at`)**
   - Log in at linkedin.com/learning in your browser, then press **Get from browser** (pick the browser in the dropdown), **or**
   - copy it by hand: press `F12` > Application (Chrome/Edge) or Storage (Firefox) > Cookies > `linkedin.com` > copy the value of `li_at`.
   - Safari on macOS needs Full Disk Access for the app that runs this (System Settings > Privacy & Security > Full Disk Access).
   - On Windows, Chrome/Edge import often fails (encrypted cookies); paste the token manually or use Firefox.
2. **Add links**: paste a course or path URL, press **Add** (or Enter). Repeat. Use **Paste several** for a list.
3. Choose the **save folder**, quality, and whether to include subtitles / exercise files. Optional: raise *Delay/video* if you get rate-limited.
4. Press **Download**. Items are processed in order; **Stop** cancels cleanly.
5. When finished, read the **SUMMARY** in the log (also shown as a popup). Re-run only the failed links if needed.

## Build an executable to share

Each friend uses **their own** LinkedIn account/token. Executables must be built on the OS they target.

**Windows (.exe)** - two ways:

*A. On a Windows PC* (Python 3.9+ from python.org, "Add python.exe to PATH" ticked, Tcl/Tk included):
1. Copy `llcd_gui.py`, `requirements.txt`, `build_windows.bat` to the PC.
2. Double-click `build_windows.bat` (it checks Python/Tk, builds a clean venv, runs PyInstaller).
3. Share `dist\LinkedInLearningDownloader.exe` (single file, no Python needed). SmartScreen may warn about an unknown publisher: *More info > Run anyway*.

*B. No Windows PC - GitHub Actions:* push this repo to GitHub, open **Actions > Build Windows exe > Run workflow**, then download the `LinkedInLearningDownloader-windows` artifact. Pushing a tag such as `v1.0` also attaches the `.exe` to a GitHub Release you can send to friends.

**macOS (.app / .zip)**:
```bash
./build_mac.sh        # uses a Python that has Tk (python.org build)
```
Share `dist/LinkedInLearningDownloader.zip`. The app is unsigned, so on first launch right-click > Open.

Some antivirus tools flag PyInstaller apps as false positives.

## Known limitations

- **Exercise files may fail**: LinkedIn's API often returns download links on the retired host `lilcdn-a.akamaihd.net`, which no longer resolves in DNS. The downloader logs a warning, marks the course **Partial**, keeps going, and writes `_exercise_files_NOT_downloaded.txt` in the course folder. Download those files manually from the course page's *Exercise Files* tab.
- Learning-path course discovery scrapes the path page's HTML for `/learning/<course>` links and validates each against the API. If LinkedIn changes that page, you will see "No courses found on the path page".
- Tokens expire; if you see "Invalid or expired token", log in again and copy a fresh one.

## Repository files

| File | Purpose |
|---|---|
| `llcd_gui.py` | The application |
| `requirements.txt` | Python dependencies (+ PyInstaller) |
| `build_windows.bat` | Builds the Windows `.exe` (run on Windows) |
| `.github/workflows/build-windows.yml` | Builds the Windows `.exe` on GitHub's servers |
| `build_mac.sh` | Builds the macOS `.app` and `.zip` |
