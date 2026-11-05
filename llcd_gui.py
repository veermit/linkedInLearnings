#!/usr/bin/env python3
"""LinkedIn Learning Courses Downloader - desktop GUI (Python/Tkinter port).

Ported from https://github.com/ahmedayman4a/Linkedin-Learning-Courses-Downloader
(same endpoints, same folder layout). Use only with your own LinkedIn Learning
subscription, for personal offline viewing.

Output layout:
    <chosen folder>/<Course title>/<NN - Chapter>/<NN - Video>.mp4 (+ .srt)
    <chosen folder>/<Course title>/<exercise files>
"""
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import tkinter as tk
from datetime import timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  python3 -m pip install requests")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:88.0) Gecko/20100101 Firefox/88.0"
API = "https://www.linkedin.com/learning-api/detailedCourses"
URL_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/learning/(?P<slug>[a-zA-Z0-9-]+)")
PATH_RE = re.compile(r"https?://(?:www\.)?linkedin\.com/learning/paths/(?P<slug>[a-zA-Z0-9-]+)")
# /learning/<x> links that are site pages, not courses
NON_COURSE = {"paths", "search", "me", "topics", "subjects", "instructors", "subscription",
              "login", "signup", "my-library", "community", "content-library", "resources",
              "certificates", "free-learning", "for-business", "premium", "learning-paths",
              "teams", "assessments", "styles", "scripts", "images", "assets", "api",
              "browse", "popular", "career-paths", "featured", "new-releases", "collections"}
CONFIG = Path.home() / ".llcd_gui.json"


class Cancelled(Exception):
    pass


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name or "").strip().rstrip(".")
    return name or "untitled"


def srt_time(ms: int) -> str:
    td = timedelta(milliseconds=int(ms))
    total = int(td.total_seconds())
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d},{int(ms) % 1000:03d}"


def build_srt(lines, duration_s):
    out = []
    for i, ln in enumerate(lines):
        start = ln["transcriptStartAt"]
        end = lines[i + 1]["transcriptStartAt"] if i + 1 < len(lines) else duration_s * 1000
        out.append(f"{i + 1}\n{srt_time(start)} --> {srt_time(end)}\n{ln['caption']}\n")
    return "\n".join(out)


def firefox_token():
    """Read li_at from Firefox's default profiles (no decryption needed)."""
    roots = [Path.home() / "Library/Application Support/Firefox/Profiles",
             Path.home() / ".mozilla/firefox",
             Path(os.environ.get("APPDATA", "")) / "Mozilla/Firefox/Profiles"]
    for root in roots:
        for db in root.glob("*/cookies.sqlite") if root.exists() else []:
            tmp = Path(tempfile.mkdtemp()) / "c.sqlite"
            shutil.copy(db, tmp)
            try:
                con = sqlite3.connect(tmp)
                row = con.execute("select value from moz_cookies where name='li_at' "
                                  "and host like '%linkedin.com' limit 1").fetchone()
                con.close()
                if row:
                    return row[0]
            except sqlite3.Error:
                pass
    return None


SAFARI_PATHS = [
    Path.home() / "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies",
    Path.home() / "Library/Cookies/Cookies.binarycookies",
]


def parse_binarycookies(data: bytes):
    """Yield (domain, name, value) from a Safari Cookies.binarycookies blob."""
    import struct
    if data[:4] != b"cook":
        raise ValueError("Not a Safari cookie file")
    npages = struct.unpack(">I", data[4:8])[0]
    sizes = struct.unpack(">" + "I" * npages, data[8:8 + 4 * npages])
    pos = 8 + 4 * npages

    def cstr(buf, off):
        end = buf.index(b"\x00", off)
        return buf[off:end].decode("utf-8", "replace")

    for size in sizes:
        page, pos = data[pos:pos + size], pos + size
        n = struct.unpack("<I", page[4:8])[0]
        offs = struct.unpack("<" + "I" * n, page[8:8 + 4 * n])
        for o in offs:
            rec = page[o:]
            url_o, name_o, _path_o, val_o = struct.unpack("<IIII", rec[16:32])
            yield cstr(rec, url_o), cstr(rec, name_o), cstr(rec, val_o)


def safari_token():
    """Read li_at from Safari. Needs Full Disk Access for the app running this."""
    denied = False
    for p in SAFARI_PATHS:
        try:
            data = p.read_bytes()
        except PermissionError:
            denied = True
            continue
        except OSError:
            continue
        for domain, name, value in parse_binarycookies(data):
            if name == "li_at" and "linkedin.com" in domain:
                return value
    if denied:
        raise PermissionError("macOS blocked access to Safari's cookies. Grant Full Disk Access "
                              "to your Terminal / VS Code (System Settings > Privacy & Security > "
                              "Full Disk Access), restart it, and try again.")
    return None


def browser_token(browser="Safari"):
    if browser == "Safari":
        return safari_token()
    if browser == "Firefox":
        return firefox_token()
    tok = firefox_token()
    if tok:
        return tok
    try:  # optional: pip install browser-cookie3 (Chrome/Edge/Safari/...)
        import browser_cookie3
        for fn in (browser_cookie3.chrome, browser_cookie3.edge, browser_cookie3.safari):
            try:
                for c in fn(domain_name="linkedin.com"):
                    if c.name == "li_at":
                        return c.value
            except Exception:
                continue
    except ImportError:
        pass
    return None


class Downloader:
    def __init__(self, token, quality, subtitles, exercises, delay, log, progress, cancel):
        self.quality, self.subtitles, self.exercises = quality, subtitles, exercises
        self.delay, self.log, self.progress, self.cancel = delay, log, progress, cancel
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA
        self.s.cookies.set("li_at", token, domain=".www.linkedin.com", path="/")
        self.home = None
        self.results = []  # (group, url, status, detail)
        self.warn = 0

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def login(self):
        r = self.s.get("https://www.linkedin.com/learning")
        self.home = r.text
        if re.search(r"nav__button-tertiary.*\n?.\r?.*Start free trial", self.home) \
                or "JSESSIONID" not in self.s.cookies:
            raise ValueError("Invalid or expired LinkedIn token (li_at). Log in again and copy a fresh one.")
        self.s.headers["Csrf-Token"] = self.s.cookies.get("JSESSIONID")
        m = re.search(r'enterpriseProfileHash":"(.*?)"', self.home.replace("&quot;", '"'))
        if m:
            self.s.headers["x-li-identity"] = m.group(1)

    def get_json(self, url):
        r = self.s.get(url)
        try:
            return r.json()
        except ValueError:
            if "CSRF check failed" in r.text:
                raise ValueError("Token expired. Please use a new one.")
            raise ValueError("Unexpected response from LinkedIn: " + r.text[:200])

    def fetch(self, url, dest: Path, label):
        if dest.exists() and dest.stat().st_size > 0:
            self.log(f"   skip (exists): {dest.name}")
            return
        part = dest.with_suffix(dest.suffix + ".part")
        with self.s.get(url, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            done = 0
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    self.check()
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        self.progress(label, done / total * 100)
        part.replace(dest)

    def tracked(self, url, root, group="", **kw):
        """Run course() and record the outcome. Returns True / False / None (not a course)."""
        self.warn = 0
        try:
            ok = self.course(url, root, **kw)
        except Cancelled:
            raise
        except Exception as e:
            self.log(f"ERROR for {url}: {e}")
            self.results.append((group, url, "FAILED", str(e)[:200]))
            return False
        if ok:
            self.results.append((group, url, "PARTIAL" if self.warn else "OK",
                                 f"{self.warn} warning(s), e.g. exercise file skipped" if self.warn else ""))
        return ok

    def path(self, url, root: Path):
        """Download every course of a learning path into <root>/<Path title>/NN - <Course>."""
        m = PATH_RE.search(url if "://" in url else "https://" + url)
        slug = m.group("slug")
        r = self.s.get(f"https://www.linkedin.com/learning/paths/{slug}")
        if r.status_code != 200:
            raise ValueError(f"Could not open learning path (HTTP {r.status_code}).")
        html = (r.text.replace("&quot;", '"').replace("&#61;", "=").replace("\\u002F", "/")
                .replace("\\/", "/").replace("&amp;", "&"))
        t = re.search(r'<meta property="og:title" content="([^"]+)"', html) \
            or re.search(r"<title>(.*?)</title>", html, re.S)
        title = re.sub(r"\s*\|\s*LinkedIn.*$", "", t.group(1)).strip() if t else slug
        slugs = []
        for s in re.findall(r"/learning/([a-z0-9][a-z0-9-]+)(?=[\"'?#/\\\s<]|$)", html):
            if s not in NON_COURSE and s not in slugs:
                slugs.append(s)
        if not slugs:
            raise ValueError("No courses found on the path page - token may be invalid, "
                             "or the page layout changed.")
        pdir = root / safe_name(title)
        pdir.mkdir(parents=True, exist_ok=True)
        self.log(f"\n##### Learning path: {title} ({len(slugs)} candidate links) #####")
        n = 0
        for s in slugs:
            self.check()
            if self.tracked(f"https://www.linkedin.com/learning/{s}", pdir, group=title,
                            prefix=f"{n + 1:02d} - ", skip_invalid=True):
                n += 1
        self.log(f"Learning path finished: {n} courses -> {pdir}")

    def course(self, url, root: Path, prefix="", skip_invalid=False):
        m = URL_RE.search(url if "://" in url else "https://" + url)
        if not m:
            raise ValueError(f"Invalid course URL: {url}")
        slug = m.group("slug")
        data = self.get_json(f"{API}?courseSlug={slug}&fields=chapters,title,exerciseFiles"
                             f"&addParagraphsToTranscript=true&q=slugs")
        if skip_invalid and not data.get("elements"):
            return False  # link on the path page that isn't a course
        el = data["elements"][0]
        title, chapters = el["title"], el.get("chapters", [])
        cdir = root / (prefix + safe_name(title))
        cdir.mkdir(parents=True, exist_ok=True)
        self.log(f"\n=== {title} ===")
        vids_total = sum(len(c["videos"]) for c in chapters)
        n = 0
        for ci, ch in enumerate(chapters, 1):
            chdir = cdir / f"{ci:02d} - {safe_name(ch['title'])}"
            chdir.mkdir(exist_ok=True)
            for vi, v in enumerate(ch["videos"], 1):
                self.check()
                n += 1
                vd = self.get_json(f"{API}?courseSlug={slug}&resolution=_{self.quality}&q=slugs"
                                   f"&fields=selectedVideo&videoSlug={v['slug']}")
                sv = vd["elements"][0]["selectedVideo"]
                link = (sv.get("url") or {}).get("progressiveUrl")
                if not link:
                    raise ValueError("Could not get a video link - token probably invalid or no access to this course.")
                base = f"{vi:02d} - {safe_name(sv['title'])}"
                self.log(f"[{n}/{vids_total}] {ch['title']} / {sv['title']}")
                lines = (sv.get("transcript") or {}).get("lines")
                if self.subtitles and lines:
                    (chdir / f"{base}.srt").write_text(build_srt(lines, sv.get("durationInSeconds", 0)),
                                                       encoding="utf-8")
                self.fetch(link, chdir / f"{base}.mp4", base)
                self.progress(None, n / vids_total * 100)
                if self.delay:
                    self.cancel.wait(self.delay)
        if self.exercises:
            for ef in el.get("exerciseFiles") or []:
                self.check()
                self.log(f"   exercise file: {ef['name']}")
                try:
                    self.fetch(ef["url"], cdir / safe_name(ef["name"]), ef["name"])
                except Cancelled:
                    raise
                except Exception as e:
                    reason = "host not reachable (dead CDN link)" \
                        if "NameResolutionError" in str(e) else str(e)[:150]
                    self.log(f"   WARNING: exercise file skipped - {reason}")
                    self.warn += 1
                    with open(cdir / "_exercise_files_NOT_downloaded.txt", "a", encoding="utf-8") as nf:
                        nf.write(f"{ef['name']}\n  reason: {reason}\n  "
                                 f"get it manually from the course page > Exercise Files tab\n\n")
        self.log(f"Finished: {cdir}")
        return True


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Downloader")
        self.geometry("780x720")
        self.cancel = threading.Event()
        self.worker = None
        pad = {"padx": 10, "pady": 4}

        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        li = ttk.Frame(nb); nb.add(li, text="LinkedIn Learning")
        md = ttk.Frame(nb); nb.add(md, text="YouTube / Instagram / Facebook")
        self.build_media(md)

        ttk.Label(li, text="LinkedIn ID (li_at login token)").pack(anchor="w", **pad)
        row = ttk.Frame(li); row.pack(fill="x", **pad)
        self.token = tk.StringVar()
        ttk.Entry(row, textvariable=self.token, show="•").pack(side="left", fill="x", expand=True)
        self.browser = tk.StringVar(value="Safari")
        ttk.Combobox(row, textvariable=self.browser, values=["Safari", "Firefox", "Chrome/Edge"],
                     width=11, state="readonly").pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Get from browser", command=self.pull_token).pack(side="left", padx=(6, 0))

        ttk.Label(li, text="Course or Learning Path URL (paste, then press Add / Enter)").pack(anchor="w", **pad)
        row = ttk.Frame(li); row.pack(fill="x", **pad)
        self.url_in = tk.StringVar()
        ent = ttk.Entry(row, textvariable=self.url_in)
        ent.pack(side="left", fill="x", expand=True)
        ent.bind("<Return>", lambda e: self.add_url())
        ttk.Button(row, text="Add", command=self.add_url).pack(side="left", padx=(6, 0))
        ttk.Button(row, text="Paste several", command=self.paste_many).pack(side="left", padx=(6, 0))
        qrow = ttk.Frame(li); qrow.pack(fill="x", **pad)
        self.queue = tk.Listbox(qrow, height=6, selectmode="extended", activestyle="none")
        self.queue.pack(side="left", fill="x", expand=True)
        sb = ttk.Scrollbar(qrow, command=self.queue.yview); sb.pack(side="left", fill="y")
        self.queue.config(yscrollcommand=sb.set)
        btns = ttk.Frame(qrow); btns.pack(side="left", padx=(6, 0), anchor="n")
        ttk.Button(btns, text="Remove selected", command=self.remove_urls).pack(fill="x")
        ttk.Button(btns, text="Clear all", command=lambda: self.queue.delete(0, "end")).pack(fill="x", pady=(4, 0))
        self.qcount = ttk.Label(li, text="Queue: 0 item(s) - downloaded one by one, in order", foreground="gray")
        self.qcount.pack(anchor="w", padx=10)

        ttk.Label(li, text="Save into folder").pack(anchor="w", **pad)
        row = ttk.Frame(li); row.pack(fill="x", **pad)
        self.folder = tk.StringVar(value=str(Path.home() / "Downloads" / "LinkedInLearning"))
        ttk.Entry(row, textvariable=self.folder).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self.browse).pack(side="left", padx=(6, 0))

        row = ttk.Frame(li); row.pack(fill="x", **pad)
        ttk.Label(row, text="Quality").pack(side="left")
        self.quality = tk.StringVar(value="720")
        ttk.Combobox(row, textvariable=self.quality, values=["720", "540", "360"],
                     width=5, state="readonly").pack(side="left", padx=6)
        self.subs = tk.BooleanVar(value=True)
        self.ex = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Subtitles", variable=self.subs).pack(side="left", padx=10)
        ttk.Checkbutton(row, text="Exercise files", variable=self.ex).pack(side="left")
        ttk.Label(row, text="Delay/video (s)").pack(side="left", padx=(14, 4))
        self.delay = tk.IntVar(value=1)
        ttk.Spinbox(row, from_=0, to=60, textvariable=self.delay, width=4).pack(side="left")

        row = ttk.Frame(li); row.pack(fill="x", **pad)
        self.go = ttk.Button(row, text="Download", command=self.start); self.go.pack(side="left")
        self.stop = ttk.Button(row, text="Stop", command=self.cancel.set, state="disabled")
        self.stop.pack(side="left", padx=6)
        ttk.Button(row, text="Clear log", command=lambda: self.clear_box(self.logbox)).pack(side="left")

        self.status = ttk.Label(li, text="Idle"); self.status.pack(anchor="w", **pad)
        self.bar = ttk.Progressbar(li, maximum=100); self.bar.pack(fill="x", **pad)
        self.bar2 = ttk.Progressbar(li, maximum=100); self.bar2.pack(fill="x", **pad)
        self.logbox = scrolledtext.ScrolledText(li, height=12, state="disabled")
        self.logbox.pack(fill="both", expand=True, **pad)

    # --- YouTube / Instagram / Facebook tab (yt-dlp) ---
    def build_media(self, tab):
        pad = {"padx": 10, "pady": 4}
        self.m_cancel = threading.Event()
        ttk.Label(tab, text="Video / reel / playlist URLs (one per line)").pack(anchor="w", **pad)
        self.m_urls = scrolledtext.ScrolledText(tab, height=7)
        self.m_urls.pack(fill="x", **pad)
        ttk.Label(tab, text="Save into folder").pack(anchor="w", **pad)
        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        self.m_folder = tk.StringVar(value=str(Path.home() / "Downloads" / "Videos"))
        ttk.Entry(row, textvariable=self.m_folder).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=lambda: self.m_folder.set(
            filedialog.askdirectory(initialdir=self.m_folder.get()) or self.m_folder.get())
        ).pack(side="left", padx=(6, 0))
        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        ttk.Label(row, text="Quality").pack(side="left")
        self.m_quality = tk.StringVar(value="Best")
        ttk.Combobox(row, textvariable=self.m_quality, width=10, state="readonly",
                     values=["Best", "1080p", "720p", "480p", "360p", "Audio only (mp3)"]
                     ).pack(side="left", padx=6)
        ttk.Label(row, text="Login cookies from").pack(side="left", padx=(14, 4))
        self.m_cookies = tk.StringVar(value="None")
        ttk.Combobox(row, textvariable=self.m_cookies, width=9, state="readonly",
                     values=["None", "Safari", "Chrome", "Firefox", "Edge"]).pack(side="left")
        ttk.Label(tab, text="Cookies are only needed for private/age-restricted content "
                  "(Safari needs Full Disk Access).", foreground="gray").pack(anchor="w", padx=10)
        row = ttk.Frame(tab); row.pack(fill="x", **pad)
        self.m_go = ttk.Button(row, text="Download", command=self.m_start); self.m_go.pack(side="left")
        self.m_stop = ttk.Button(row, text="Stop", command=self.m_cancel.set, state="disabled")
        self.m_stop.pack(side="left", padx=6)
        ttk.Button(row, text="Clear log", command=lambda: self.clear_box(self.m_log)).pack(side="left")
        self.m_status = ttk.Label(tab, text="Idle"); self.m_status.pack(anchor="w", **pad)
        self.m_bar = ttk.Progressbar(tab, maximum=100); self.m_bar.pack(fill="x", **pad)
        self.m_log = scrolledtext.ScrolledText(tab, height=12, state="disabled")
        self.m_log.pack(fill="both", expand=True, **pad)

    @staticmethod
    def clear_box(box):
        box.config(state="normal"); box.delete("1.0", "end"); box.config(state="disabled")

    def mlog(self, msg):
        def f():
            self.m_log.config(state="normal"); self.m_log.insert("end", msg + "\n")
            self.m_log.see("end"); self.m_log.config(state="disabled")
        self.after(0, f)

    def m_start(self):
        urls = [u.strip() for u in self.m_urls.get("1.0", "end").splitlines() if u.strip()]
        if not urls or not self.m_folder.get().strip():
            messagebox.showwarning("Missing input", "Provide at least one URL and a folder.")
            return
        self.m_cancel.clear()
        self.m_go.config(state="disabled"); self.m_stop.config(state="normal")
        threading.Thread(target=self.m_run, daemon=True, args=(
            urls, Path(self.m_folder.get()).expanduser(), self.m_quality.get(),
            self.m_cookies.get())).start()

    def m_run(self, urls, root, quality, cookies):
        try:
            import yt_dlp
        except ImportError:
            self.mlog("Missing dependency. Run:  python3 -m pip install yt-dlp")
            self.after(0, lambda: (self.m_go.config(state="normal"), self.m_stop.config(state="disabled")))
            return

        def hook(d):
            if self.m_cancel.is_set():
                raise yt_dlp.utils.DownloadCancelled()
            if d["status"] == "downloading":
                tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                pct = d["downloaded_bytes"] / tot * 100 if tot else 0
                name = Path(d.get("filename", "")).name
                self.after(0, lambda: (self.m_bar.config(value=pct),
                                       self.m_status.config(text=f"{name} – {pct:.0f}%")))
            elif d["status"] == "finished":
                self.mlog(f"Downloaded: {Path(d['filename']).name}")

        class Q:
            debug = warning = staticmethod(lambda m: None)
            @staticmethod
            def error(m): pass
        opts = {"outtmpl": str(root / "%(extractor_key)s" / "%(playlist_title|)s" /
                               "%(title).150B [%(id)s].%(ext)s"),
                "progress_hooks": [hook], "noprogress": True, "quiet": True, "no_warnings": True,
                "ignoreerrors": False, "continuedl": True, "windowsfilenames": True}
        if quality.startswith("Audio"):
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
        elif quality == "Best":
            opts["format"] = "bv*+ba/b"; opts["merge_output_format"] = "mp4"
        else:
            h = quality[:-1]
            opts["format"] = f"bv*[height<={h}]+ba/b[height<={h}]/b"; opts["merge_output_format"] = "mp4"
        if cookies != "None":
            opts["cookiesfrombrowser"] = (cookies.lower(),)
        try:
            root.mkdir(parents=True, exist_ok=True)
            for u in urls:
                if self.m_cancel.is_set():
                    break
                self.mlog(f"\n=== {u}")
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.download([u])
                except yt_dlp.utils.DownloadCancelled:
                    self.mlog("Stopped by user."); break
                except Exception as e:
                    self.mlog(f"ERROR: {e}")
            self.mlog("\nAll done." if not self.m_cancel.is_set() else "")
        finally:
            self.after(0, lambda: (self.m_go.config(state="normal"), self.m_stop.config(state="disabled"),
                                   self.m_status.config(text="Idle")))

    # --- UI helpers (thread-safe via after) ---
    def log(self, msg):
        def f():
            self.logbox.config(state="normal")
            self.logbox.insert("end", msg + "\n")
            self.logbox.see("end")
            self.logbox.config(state="disabled")
        self.after(0, f)

    def progress(self, label, pct):
        def f():
            if label is None:
                self.bar2["value"] = pct
            else:
                self.bar["value"] = pct
                self.status.config(text=f"Downloading {label} – {pct:.0f}%")
        self.after(0, f)

    def _add(self, text):
        have = set(self.queue.get(0, "end"))
        bad = []
        for u in re.split(r"[\s,]+", text.strip()):
            if not u:
                continue
            if not (PATH_RE.search(u) or URL_RE.search(u)):
                bad.append(u); continue
            if u not in have:
                self.queue.insert("end", u); have.add(u)
        self.qcount.config(text=f"Queue: {self.queue.size()} item(s) - downloaded one by one, in order")
        if bad:
            messagebox.showwarning("Not a LinkedIn Learning link", "Skipped:\n" + "\n".join(bad[:10]))

    def add_url(self):
        if self.url_in.get().strip():
            self._add(self.url_in.get())
            self.url_in.set("")

    def paste_many(self):
        win = tk.Toplevel(self); win.title("Paste several links"); win.geometry("640x320")
        ttk.Label(win, text="One link per line:").pack(anchor="w", padx=10, pady=6)
        box = scrolledtext.ScrolledText(win, height=10); box.pack(fill="both", expand=True, padx=10)
        def ok():
            self._add(box.get("1.0", "end")); win.destroy()
        ttk.Button(win, text="Add all", command=ok).pack(pady=8)

    def remove_urls(self):
        for i in reversed(self.queue.curselection()):
            self.queue.delete(i)
        self.qcount.config(text=f"Queue: {self.queue.size()} item(s) - downloaded one by one, in order")

    def browse(self):
        d = filedialog.askdirectory(initialdir=self.folder.get())
        if d:
            self.folder.set(d)

    def pull_token(self):
        try:
            t = browser_token(self.browser.get())
        except PermissionError as e:
            messagebox.showwarning("Permission needed", str(e))
            return
        except Exception as e:
            messagebox.showerror("Error", f"Could not read cookies: {e}")
            return
        if t:
            self.token.set(t)
            self.log(f"Token imported from {self.browser.get()}.")
        else:
            messagebox.showinfo("Not found",
                f"No li_at cookie found in {self.browser.get()}. Make sure you're logged in at "
                "linkedin.com/learning in that browser (Chrome/Edge needs 'pip install "
                "browser-cookie3').")

    def start(self):
        token = self.token.get().strip()
        self.add_url()  # include anything still typed in the box
        urls = list(self.queue.get(0, "end"))
        if not token or not urls or not self.folder.get().strip():
            messagebox.showwarning("Missing input", "Provide the token, at least one course URL, and a folder.")
            return
        self.cancel.clear()
        self.go.config(state="disabled"); self.stop.config(state="normal")
        args = (token, urls, Path(self.folder.get()).expanduser(), self.quality.get(),
                self.subs.get(), self.ex.get(), self.delay.get())
        self.worker = threading.Thread(target=self.run, args=args, daemon=True)
        self.worker.start()

    def run(self, token, urls, root, quality, subs, ex, delay):
        d = None
        try:
            root.mkdir(parents=True, exist_ok=True)
            d = Downloader(token, quality, subs, ex, delay, self.log, self.progress, self.cancel)
            d.login()
            for i, u in enumerate(urls, 1):
                self.log(f"\n##### Item {i}/{len(urls)}: {u}")
                if PATH_RE.search(u):
                    try:
                        d.path(u, root)
                    except Cancelled:
                        raise
                    except Exception as e:
                        self.log(f"ERROR for {u}: {e}")
                        d.results.append(("", u, "FAILED", str(e)[:200]))
                else:
                    d.tracked(u, root)
            self.log("\nAll done.")
        except Cancelled:
            self.log("\nStopped by user.")
        except Exception as e:
            self.log(f"\nERROR: {e}")
            if d is not None:
                d.results.append(("", "(login/setup)", "FAILED", str(e)[:200]))
        finally:
            if d is not None and d.results:
                self.summary(d.results, len(urls))
            self.after(0, lambda: (self.go.config(state="normal"), self.stop.config(state="disabled"),
                                   self.status.config(text="Idle")))

    def summary(self, results, n_inputs):
        ok = [r for r in results if r[2] == "OK"]
        part = [r for r in results if r[2] == "PARTIAL"]
        bad = [r for r in results if r[2] == "FAILED"]
        lines = ["", "=" * 60, "SUMMARY",
                 f"  Success: {len(ok)}   Partial: {len(part)}   Failed: {len(bad)}   "
                 f"(courses attempted: {len(results)})", "=" * 60]
        for label, rows in (("SUCCESS", ok), ("PARTIAL (course saved, some extras skipped)", part),
                            ("FAILED", bad)):
            if rows:
                lines.append(f"\n{label}:")
                for g, u, _st, det in rows:
                    lines.append(f"  - {u}" + (f"   [path: {g}]" if g else "") + (f"\n      {det}" if det else ""))
        text = "\n".join(lines)
        self.log(text)
        msg = f"Success: {len(ok)}\nPartial: {len(part)}\nFailed: {len(bad)}"
        if bad:
            msg += "\n\nFailed links:\n" + "\n".join(r[1] for r in bad[:15])
        self.after(0, lambda: messagebox.showinfo("Download complete", msg))


if __name__ == "__main__":
    App().mainloop()
