import ctypes
import datetime
import json
import os
import platform
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import storage
import scheduler
import widgets

try:
    import script
    SELENIUM_IMPORT_ERROR = None
except ImportError as exc:  # only possible when running from source
    script = None
    SELENIUM_IMPORT_ERROR = str(exc)

WINDOW_TITLE = "Rewards Searcher"
EDGE_CLIENT_KEY = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{56EB18F8-B008-4CBD-B6D2-8C97FE7E9062}"
EDGE_WAIT_MINUTES = 30
AUTO_CLOSE_SECONDS = 10

C = {
    "bg": "#f3f5f9",
    "card": "#ffffff",
    "border": "#e1e5ee",
    "text": "#1b1f2a",
    "muted": "#5f6878",
    "accent": "#0f6cbd",
    "accent_dark": "#0c5aa0",
    "ok": "#107c10",
    "warn": "#b96a00",
    "error": "#c42b1c",
    "pending": "#8a93a3",
}
FONT = "Segoe UI"
STATE_ICONS = {"ok": "✓", "warn": "!", "error": "✗", "pending": "…"}


def plural(n):
    return f"{n} search" if n == 1 else f"{n} searches"


# --- Environment checks ---------------------------------------------------

def edge_version():
    import winreg
    for hive, key in (
        (winreg.HKEY_LOCAL_MACHINE, EDGE_CLIENT_KEY.replace("SOFTWARE\\", "SOFTWARE\\WOW6432Node\\", 1)),
        (winreg.HKEY_LOCAL_MACHINE, EDGE_CLIENT_KEY),
        (winreg.HKEY_CURRENT_USER, EDGE_CLIENT_KEY),
    ):
        try:
            with winreg.OpenKey(hive, key) as k:
                return winreg.QueryValueEx(k, "pv")[0]
        except OSError:
            continue
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base and os.path.exists(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe")):
            return "installed"
    return None


def list_edge_profiles():
    """[(folder, display name)] from Edge's Local State, Default first."""
    profiles = []
    try:
        with open(os.path.join(script.EDGE_USER_DATA_DIR, "Local State"), encoding="utf-8") as f:
            cache = json.load(f)["profile"]["info_cache"]
        for folder, info in cache.items():
            profiles.append((folder, info.get("name") or folder))
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        pass
    if not profiles:
        profiles = [("Default", "Default")]
    profiles.sort(key=lambda p: (p[0] != "Default", p[0]))
    return profiles


def check_environment(put):
    frozen = scheduler.is_frozen()
    put(("status", "python", "ok", platform.python_version(),
         "Bundled inside the app" if frozen else "Installed on this PC"))

    if script is None:
        put(("status", "selenium", "error", "Not installed", "Run: pip install selenium"))
        put(("status", "edge", "error", "Cannot check", "Selenium is required first"))
        return
    import selenium
    put(("status", "selenium", "ok", selenium.__version__,
         "Bundled inside the app" if frozen else "Installed"))

    version = edge_version()
    if not version:
        put(("status", "edge", "error", "Not found", "Install Microsoft Edge from microsoft.com/edge"))
        return
    put(("status", "edge", "pending", version, "Checking Edge driver…"))
    try:
        from selenium.webdriver.common.selenium_manager import SeleniumManager
        SeleniumManager().binary_paths(["--browser", "MicrosoftEdge"])
        put(("status", "edge", "ok", version, "Driver ready (matched automatically)"))
    except Exception:
        put(("status", "edge", "error", version,
             "Driver download failed. Connect to the internet and reopen the app."))


# --- Single instance --------------------------------------------------------

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.CreateEventW.restype = ctypes.c_void_p
_kernel32.SetEvent.argtypes = [ctypes.c_void_p]
_kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
_kernel32.WaitForSingleObject.restype = ctypes.c_uint32


def acquire_single_instance():
    handle = _kernel32.CreateMutexW(None, False, "Local\\RewardsSearcherSingleInstance")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def create_schedule_signal():
    """Auto-reset event a scheduled launch sets when a window is already open."""
    return _kernel32.CreateEventW(None, False, False, "Local\\RewardsSearcherScheduledStart")


def signal_received(handle):
    return bool(handle) and _kernel32.WaitForSingleObject(handle, 0) == 0  # WAIT_OBJECT_0


def focus_existing_window():
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return bool(hwnd)


# --- GUI ------------------------------------------------------------------

class App:
    def __init__(self, root, autorun, signal):
        self.root = root
        self.autorun = autorun
        self.signal = signal
        self.q = queue.Queue()
        self.settings = storage.load_settings()
        self.worker = None
        self.stop_event = threading.Event()
        self.auto_mode = False
        self.closing = False
        self.start_after_close = False
        self.edge_wait_deadline = None
        self.close_countdown = None
        self.schedule_info = None
        self.schedule_error = None
        self.schedule_busy = True
        self.shown_date = None
        self.edge_profiles = list_edge_profiles() if script else [("Default", "Default")]

        self._style()
        self._build()
        self.refresh_progress()

        threading.Thread(target=check_environment, args=(self.q.put,), daemon=True).start()
        self._refresh_schedule_async()
        self.root.after(100, self._poll)
        self.root.after(30000, self._tick)
        self._clock()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        if autorun:
            storage.log("Started by the daily schedule.")
            self.root.after(800, lambda: self.start_run(auto=True))

    # ----- layout -----
    def _style(self):
        self.root.title(WINDOW_TITLE)
        self.root.configure(bg=C["bg"])
        self.root.geometry("820x860")
        self.root.minsize(720, 760)
        s = ttk.Style(self.root)
        s.theme_use("clam")
        s.configure(".", font=(FONT, 10), background=C["card"], foreground=C["text"])
        widgets.install_styles(self.root, s, C, FONT)
        s.configure("Horizontal.TProgressbar", troughcolor="#e8ecf3", background=C["accent"],
                    bordercolor="#e8ecf3", lightcolor=C["accent"], darkcolor=C["accent"],
                    thickness=14)
        s.configure("Done.Horizontal.TProgressbar", background=C["ok"],
                    lightcolor=C["ok"], darkcolor=C["ok"])

    def _card(self, parent, title, subtitle=None):
        outer = tk.Frame(parent, bg=C["card"], highlightbackground=C["border"],
                         highlightthickness=1)
        inner = tk.Frame(outer, bg=C["card"])
        inner.pack(fill="both", expand=True, padx=18, pady=14)
        head = tk.Frame(inner, bg=C["card"])
        head.pack(fill="x")
        tk.Label(head, text=title, bg=C["card"], fg=C["text"],
                 font=(FONT, 12, "bold")).pack(side="left")
        if subtitle:
            tk.Label(head, text=subtitle, bg=C["card"], fg=C["muted"],
                     font=(FONT, 9)).pack(side="left", padx=(10, 0), pady=(3, 0))
        return outer, inner, head

    def _label(self, parent, text="", size=10, color="text", bold=False, **kw):
        return tk.Label(parent, text=text, bg=C["card"], fg=C[color],
                        font=(FONT, size, "bold" if bold else "normal"), **kw)

    def _build(self):
        main = tk.Frame(self.root, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=20, pady=16)

        header = tk.Frame(main, bg=C["bg"])
        header.pack(fill="x", pady=(0, 12))
        tk.Label(header, text=WINDOW_TITLE, bg=C["bg"], fg=C["text"],
                 font=(FONT, 18, "bold")).pack(side="left")
        tk.Label(header, text="Daily Bing searches in Microsoft Edge", bg=C["bg"],
                 fg=C["muted"], font=(FONT, 10)).pack(side="left", padx=(12, 0), pady=(8, 0))

        # 1. Status boxes
        status_row = tk.Frame(main, bg=C["bg"])
        status_row.pack(fill="x")
        self.status_boxes = {}
        for i, (key, title) in enumerate((("python", "Python"), ("selenium", "Selenium"),
                                          ("edge", "Microsoft Edge"))):
            status_row.columnconfigure(i, weight=1, uniform="status")
            box = tk.Frame(status_row, bg=C["card"], highlightbackground=C["border"],
                           highlightthickness=1)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))
            inner = tk.Frame(box, bg=C["card"])
            inner.pack(fill="both", expand=True, padx=14, pady=12)
            top = tk.Frame(inner, bg=C["card"])
            top.pack(fill="x")
            icon = tk.Label(top, text=STATE_ICONS["pending"], width=2, bg=C["pending"],
                            fg="white", font=(FONT, 11, "bold"))
            icon.pack(side="left")
            self._label(top, title, 11, bold=True).pack(side="left", padx=(8, 0))
            value = self._label(inner, "Checking…", 10, "text", anchor="w")
            value.pack(fill="x", pady=(8, 0))
            detail = self._label(inner, "", 9, "muted", anchor="w", justify="left",
                                 wraplength=210)
            detail.pack(fill="x")
            self.status_boxes[key] = (icon, value, detail)

        # 2. Schedule
        card, body, head = self._card(main, "Automatic daily start")
        card.pack(fill="x", pady=(12, 0))
        self.clock_label = self._label(head, "", 9, "muted")
        self.clock_label.pack(side="right")
        row = tk.Frame(body, bg=C["card"])
        row.pack(fill="x", pady=(10, 0))
        self._label(row, "Start every day at").pack(side="left")
        self.hour_var = tk.StringVar()
        self.min_var = tk.StringVar()
        self.ampm_var = tk.StringVar()
        hour_spin = ttk.Spinbox(row, values=[str(h) for h in range(1, 13)], width=3, wrap=True,
                                textvariable=self.hour_var, justify="center",
                                style="Round.TSpinbox")
        hour_spin.pack(side="left", padx=(10, 4))
        self._label(row, ":", 11, bold=True).pack(side="left")
        ttk.Spinbox(row, values=[f"{m:02d}" for m in range(60)], width=3, wrap=True,
                    textvariable=self.min_var, justify="center",
                    style="Round.TSpinbox").pack(side="left", padx=(4, 8))
        self.root.update_idletasks()
        widgets.SegmentedToggle(row, ["AM", "PM"], self.ampm_var, C,
                                height=hour_spin.winfo_reqheight(),
                                font_family=FONT).pack(side="left")
        self.tz_label = self._label(row, "", 9, "muted")
        self.tz_label.pack(side="left", padx=(8, 0))
        self._set_time_fields(*map(int, (self.settings.get("time") or "09:00").split(":")))
        self.remove_btn = ttk.Button(row, text="Turn off", command=self.remove_schedule)
        self.remove_btn.pack(side="right")
        self.save_btn = ttk.Button(row, text="Save schedule", style="Accent.TButton",
                                   command=self.save_schedule)
        self.save_btn.pack(side="right", padx=(0, 8))
        self.sched_label = self._label(body, "Checking schedule…", 10, "muted", anchor="w",
                                       justify="left", wraplength=720)
        self.sched_label.pack(fill="x", pady=(10, 0))
        self._label(body, "The PC must be on and signed in. If it is off or asleep at that time, "
                          "the searches start as soon as you are back.",
                    9, "muted", anchor="w", justify="left", wraplength=720).pack(fill="x", pady=(2, 0))

        # 3. Today's progress
        card, body, head = self._card(main, "Today's searches")
        card.pack(fill="both", expand=True, pady=(12, 0))
        self.date_label = self._label(head, "", 9, "muted")
        self.date_label.pack(side="right")
        mid = tk.Frame(body, bg=C["card"])
        mid.pack(fill="x", pady=(8, 0))
        self.count_label = self._label(mid, "0 / 50", 28, bold=True)
        self.count_label.pack(side="left")
        btns = tk.Frame(mid, bg=C["card"])
        btns.pack(side="right")
        self.start_btn = ttk.Button(btns, text="Start now", style="Accent.TButton",
                                    command=lambda: self.start_run(auto=False))
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="Stop", command=self.stop_run, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.bar = ttk.Progressbar(body, mode="determinate", maximum=50)
        self.bar.pack(fill="x", pady=(8, 0))
        status_line = tk.Frame(body, bg=C["card"])
        status_line.pack(fill="x", pady=(8, 0))
        self.run_label = self._label(status_line, "Ready", 10, "muted", anchor="w",
                                     justify="left", wraplength=620)
        self.run_label.pack(side="left", fill="x", expand=True)
        self.keep_btn = ttk.Button(status_line, text="Keep open", command=self.cancel_auto_close)

        log_frame = tk.Frame(body, bg=C["card"])
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.log_text = tk.Text(log_frame, height=7, bg="#f7f8fb", fg=C["text"], relief="flat",
                                font=("Consolas", 9), wrap="word", state="disabled",
                                highlightthickness=1, highlightbackground=C["border"],
                                padx=8, pady=6)
        scroll = ttk.Scrollbar(log_frame, command=self.log_text.yview,
                               style="Slim.Vertical.TScrollbar")
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        # 4. Settings
        card, body, _ = self._card(main, "Settings")
        card.pack(fill="x", pady=(12, 0))
        row = tk.Frame(body, bg=C["card"])
        row.pack(fill="x", pady=(10, 0))
        self._label(row, "Searches per day").pack(side="left")
        self.target_var = tk.StringVar(value=str(self.settings.get("searches_per_day", 50)))
        self.target_spin = ttk.Spinbox(row, from_=1, to=150, width=5, justify="center",
                                       textvariable=self.target_var, command=self.on_target_change,
                                       style="Round.TSpinbox")
        self.target_spin.pack(side="left", padx=(10, 0))
        self.target_spin.bind("<FocusOut>", lambda e: self.on_target_change())
        self.target_spin.bind("<Return>", lambda e: self.on_target_change())

        row = tk.Frame(body, bg=C["card"])
        row.pack(fill="x", pady=(10, 0))
        self.profile_var = tk.BooleanVar(value=bool(self.settings.get("use_profile")))
        widgets.ToggleSwitch(row, "Use my signed-in Edge profile", self.profile_var, C,
                             command=self.on_profile_change, font_family=FONT).pack(side="left")
        names = [f"{name} ({folder})" if name != folder else folder
                 for folder, name in self.edge_profiles]
        self.profile_combo = ttk.Combobox(row, values=names, state="readonly", width=26,
                                          style="Round.TCombobox")
        current = self.settings.get("profile_dir", "Default")
        folders = [p[0] for p in self.edge_profiles]
        self.profile_combo.current(folders.index(current) if current in folders else 0)
        self.profile_combo.bind("<<ComboboxSelected>>", lambda e: self.on_profile_change())
        self.profile_combo.pack(side="left", padx=(14, 0))
        self.close_edge_btn = ttk.Button(row, text="Close Edge now", command=self.close_edge_clicked)
        self.close_edge_btn.pack(side="right")
        self.profile_note = self._label(
            body, "Searches then count for the Microsoft account signed in to that Edge profile. "
                  "Edge must be fully closed while the searches run.",
            9, "muted", anchor="w", justify="left", wraplength=720)
        self.profile_note.pack(fill="x", pady=(4, 0))
        self._update_profile_widgets()

    # ----- helpers -----
    def append_log(self, msg):
        stamp = datetime.datetime.now().strftime("%I:%M:%S %p").lstrip("0")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{stamp}  {msg}\n")
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 500:
            self.log_text.delete("1.0", f"{lines - 500}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def set_run_status(self, text, color="muted"):
        self.run_label.configure(text=text, fg=C[color])

    def target(self):
        try:
            return max(1, min(150, int(self.target_var.get())))
        except ValueError:
            return int(self.settings.get("searches_per_day", 50))

    def running(self):
        return self.worker is not None and self.worker.is_alive()

    def set_progress(self, done, target):
        self.count_label.configure(text=f"{done} / {target}")
        self.bar.configure(maximum=target, value=min(done, target))
        self.bar.configure(style="Done.Horizontal.TProgressbar" if done >= target
                           else "Horizontal.TProgressbar")
        self.date_label.configure(text=storage.today_date().strftime("%A %d %B"))

    def refresh_progress(self):
        target = self.target()
        p = storage.load_progress(target)
        self.shown_date = p["date"]
        self.set_progress(p["done"], target)
        if not self.running() and self.edge_wait_deadline is None:
            if p["done"] >= target:
                self.set_run_status("Completed for today ✓", "ok")
            elif p["done"]:
                self.set_run_status(f"Paused at {p['done']} / {target}. Start again to finish today's searches.")
            else:
                self.set_run_status("Ready")
        return p

    def _set_buttons(self, running):
        self.start_btn.configure(state="disabled" if running or script is None else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")
        self.target_spin.configure(state="disabled" if running else "normal")

    # ----- settings -----
    def on_target_change(self):
        value = self.target()
        self.target_var.set(str(value))
        if value != self.settings.get("searches_per_day"):
            self.settings["searches_per_day"] = value
            storage.save_settings(self.settings)
        if not self.running():
            self.refresh_progress()

    def selected_profile_dir(self):
        idx = self.profile_combo.current()
        return self.edge_profiles[idx][0] if 0 <= idx < len(self.edge_profiles) else "Default"

    def on_profile_change(self):
        self.settings["use_profile"] = bool(self.profile_var.get())
        self.settings["profile_dir"] = self.selected_profile_dir()
        storage.save_settings(self.settings)
        self._update_profile_widgets()

    def _update_profile_widgets(self):
        on = bool(self.profile_var.get())
        self.profile_combo.configure(state="readonly" if on else "disabled")
        if on:
            self.close_edge_btn.pack(side="right")
        else:
            self.close_edge_btn.pack_forget()

    def close_edge_clicked(self):
        self.close_edge_btn.configure(state="disabled")
        self.append_log("Closing Microsoft Edge…")
        threading.Thread(target=lambda: self.q.put(("edge_closed", script.close_edge())),
                         daemon=True).start()

    # ----- schedule -----
    def _refresh_schedule_async(self, error=None):
        def work():
            try:
                info = scheduler.query()
            except scheduler.SchedulerError as exc:
                info, err = None, str(exc)
            else:
                err = error
            self.q.put(("schedule", info, err))
        threading.Thread(target=work, daemon=True).start()

    def _show_schedule(self, info, error):
        self.schedule_info = info
        self.schedule_error = error
        self.schedule_busy = False
        if info:
            self.remove_btn.configure(state="normal")
            if info.get("time"):
                self._set_time_fields(*map(int, info["time"].split(":")))
        else:
            self.remove_btn.configure(state="disabled")
        self._render_schedule()

    def _render_schedule(self):
        """Refreshes the schedule line (called on change and every second by the clock)."""
        info, error = self.schedule_info, self.schedule_error
        if self.schedule_busy:
            return
        if error:
            self.sched_label.configure(text=f"✗ Could not update the schedule: {error}", fg=C["error"])
            return
        if not info:
            self.sched_label.configure(text="Not scheduled. Pick a time and click Save schedule.",
                                       fg=C["muted"])
            return
        command = info.get("command", "")
        if command and not os.path.exists(command):
            self.sched_label.configure(
                text="! The schedule points to a missing file. Click Save schedule to fix it.",
                fg=C["warn"])
            return
        h, m = map(int, (info.get("time") or self.settings.get("time", "09:00")).split(":"))
        now = datetime.datetime.now()
        nxt = scheduler.next_run(h, m, now)
        day = "today" if nxt.date() == now.date() else "tomorrow"
        mins = int((nxt - now).total_seconds() // 60)
        if mins < 1:
            left = "in less than a minute"
        elif mins < 60:
            left = f"in {mins} min"
        else:
            left = f"in {mins // 60} h {mins % 60} min"
        self.sched_label.configure(
            text=f"✓ Runs every day at {scheduler.format_12h(h, m)}. "
                 f"Next run: {day} at {scheduler.format_12h(h, m)} ({left})",
            fg=C["ok"])

    def _set_time_fields(self, hour24, minute):
        self.hour_var.set(str((hour24 % 12) or 12))
        self.min_var.set(f"{minute:02d}")
        self.ampm_var.set("AM" if hour24 < 12 else "PM")

    def _read_time(self):
        """(hour 0-23, minute) from the 12-hour fields, or None if invalid."""
        try:
            h12, m = int(self.hour_var.get()), int(self.min_var.get())
        except ValueError:
            return None
        ampm = self.ampm_var.get()
        if not (1 <= h12 <= 12 and 0 <= m <= 59 and ampm in ("AM", "PM")):
            return None
        return (h12 % 12 + (12 if ampm == "PM" else 0), m)

    def _clock(self):
        self.clock_label.configure(
            text="Time now: " + datetime.datetime.now().strftime("%I:%M:%S %p").lstrip("0"))
        self.tz_label.configure(text=f"({scheduler.timezone_name()})")
        self._render_schedule()
        self.root.after(1000, self._clock)

    def save_schedule(self):
        hm = self._read_time()
        if not hm:
            messagebox.showerror(WINDOW_TITLE, "Enter a valid time: hour 1-12, minutes 0-59, AM or PM.")
            return
        self._set_time_fields(*hm)
        self.settings["time"] = f"{hm[0]:02d}:{hm[1]:02d}"
        self.settings["schedule_enabled"] = True
        storage.save_settings(self.settings)
        self.schedule_busy = True
        self.sched_label.configure(text="Saving…", fg=C["muted"])
        self.save_btn.configure(state="disabled")

        def work():
            try:
                path = scheduler.register(*hm)
                storage.log(f"Schedule saved for {scheduler.format_12h(*hm)} "
                            f"({scheduler.timezone_name()}) -> {path}")
                err = None
            except scheduler.SchedulerError as exc:
                storage.log(f"Schedule save failed: {exc}")
                err = str(exc)
            self.q.put(("schedule_saved",))
            self._refresh_schedule_async(err)
        threading.Thread(target=work, daemon=True).start()

    def remove_schedule(self):
        self.settings["schedule_enabled"] = False
        storage.save_settings(self.settings)

        def work():
            err = None
            try:
                scheduler.delete()
                storage.log("Schedule removed.")
            except scheduler.SchedulerError as exc:
                err = str(exc)
            self._refresh_schedule_async(err)
        threading.Thread(target=work, daemon=True).start()

    # ----- running -----
    def start_run(self, auto=False):
        if self.running() or script is None:
            return
        self.cancel_auto_close()
        self.auto_mode = auto
        target = self.target()
        progress = storage.load_progress(target)
        if progress["done"] >= target:
            self.set_progress(progress["done"], target)
            self.set_run_status("Completed for today ✓", "ok")
            if auto and self.autorun:
                self.begin_auto_close()
            return

        use_profile = bool(self.profile_var.get())
        if use_profile and script.is_edge_running():
            if auto:
                self.wait_for_edge()
            elif messagebox.askyesno(
                    WINDOW_TITLE,
                    "Microsoft Edge is open, so your profile can't be used.\n\n"
                    "Close all Edge windows now? Your tabs can be restored the next time you open Edge."):
                self.start_after_close = True
                self.close_edge_clicked()
            return

        self.edge_wait_deadline = None
        self.stop_event = threading.Event()
        self.set_progress(progress["done"], target)
        self.set_run_status(f"Running… {plural(target - progress['done'])} to go", "accent")
        self.append_log(f"Starting ({progress['done']}/{target} done today)")
        storage.log(f"Run started at {progress['done']}/{target} "
                    f"({'scheduled' if auto else 'manual'}, profile={'on' if use_profile else 'off'})")
        self._set_buttons(True)
        self.worker = threading.Thread(
            target=self._worker,
            args=(target, progress["done"], use_profile, self.selected_profile_dir()),
            daemon=True)
        self.worker.start()

    def _worker(self, target, done, use_profile, profile_dir):
        def on_event(kind, *args):
            if kind == "progress":
                storage.save_progress(args[0], args[1])
            elif kind == "log":
                storage.log(args[0])
            self.q.put((kind, *args))
        try:
            final = script.run_searches(target, done, self.stop_event, on_event,
                                        use_profile, profile_dir)
            self.q.put(("done", final, target))
        except script.EdgeRunningError as exc:
            self.q.put(("edge_running", str(exc)))
        except script.BrowserClosedError as exc:
            storage.log(str(exc))
            self.q.put(("browser_closed", str(exc)))
        except Exception as exc:
            storage.log(f"Error: {exc}")
            self.q.put(("error", str(exc)))
        finally:
            self.q.put(("worker_end",))

    def stop_run(self):
        if self.edge_wait_deadline is not None:
            self.edge_wait_deadline = None
            self.set_run_status("Stopped waiting for Edge.")
            self._set_buttons(False)
            return
        if self.running():
            self.stop_event.set()
            self.stop_btn.configure(state="disabled")
            self.set_run_status("Stopping after the current search…")

    def wait_for_edge(self):
        if self.edge_wait_deadline is None:
            self.edge_wait_deadline = datetime.datetime.now() + datetime.timedelta(minutes=EDGE_WAIT_MINUTES)
            self.append_log("Edge is open. Waiting for it to close so your profile can be used.")
        self.set_run_status("Waiting for Microsoft Edge to close… (or click Close Edge now)", "warn")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.root.after(5000, self._check_edge_wait)

    def _check_edge_wait(self):
        if self.edge_wait_deadline is None:
            return
        if self.running():
            self.root.after(1000, self._check_edge_wait)
        elif not script.is_edge_running():
            self.start_run(auto=True)
        elif datetime.datetime.now() > self.edge_wait_deadline:
            self.edge_wait_deadline = None
            self._set_buttons(False)
            self.set_run_status("Gave up waiting for Edge to close. Close Edge and click Start now.", "error")
            storage.log("Gave up waiting for Edge to close.")
        else:
            self.root.after(5000, self._check_edge_wait)

    def begin_auto_close(self):
        self.close_countdown = AUTO_CLOSE_SECONDS
        self.keep_btn.pack(side="right")
        self._auto_close_step()

    def _auto_close_step(self):
        if self.close_countdown is None:
            return
        if self.close_countdown <= 0:
            self.root.destroy()
            return
        self.set_run_status(f"Completed for today ✓  Closing in {self.close_countdown} s", "ok")
        self.close_countdown -= 1
        self.root.after(1000, self._auto_close_step)

    def cancel_auto_close(self):
        if self.close_countdown is not None:
            self.close_countdown = None
            self.keep_btn.pack_forget()
            self.set_run_status("Completed for today ✓", "ok")

    # ----- event loop -----
    def _poll(self):
        try:
            while True:
                self._handle(self.q.get_nowait())
        except queue.Empty:
            pass
        if signal_received(self.signal):
            self.on_scheduled_signal()
        self.root.after(100, self._poll)

    def _handle(self, ev):
        kind = ev[0]
        if kind == "status":
            _, key, state, value, detail = ev
            icon, value_lbl, detail_lbl = self.status_boxes[key]
            icon.configure(text=STATE_ICONS[state], bg=C[state])
            value_lbl.configure(text=value)
            detail_lbl.configure(text=detail, fg=C["error"] if state == "error" else C["muted"])
        elif kind == "schedule":
            self._show_schedule(ev[1], ev[2])
        elif kind == "schedule_saved":
            self.save_btn.configure(state="normal")
        elif kind == "log":
            self.append_log(ev[1])
        elif kind == "progress":
            _, done, target, _query = ev
            self.set_progress(done, target)
            if not self.stop_event.is_set():
                self.set_run_status(f"Running… {plural(target - done)} to go", "accent")
        elif kind == "stopped":
            self.set_run_status(f"Stopped at {ev[1]} / {ev[2]}. Start again to continue.")
        elif kind == "done":
            _, final, target = ev
            self.set_progress(final, target)
            if final >= target:
                storage.log(f"Completed {final}/{target} for today.")
                self.set_run_status("Completed for today ✓", "ok")
                if self.auto_mode and self.autorun and not self.closing:
                    self.begin_auto_close()
        elif kind == "error":
            self.set_run_status(f"✗ {ev[1].splitlines()[0]}", "error")
            self.append_log(ev[1])
            if not self.auto_mode and not self.closing:
                messagebox.showerror(WINDOW_TITLE, ev[1])
        elif kind == "browser_closed":
            self.set_run_status(ev[1], "warn")
            self.append_log(ev[1])
        elif kind == "edge_running":
            if self.auto_mode:
                self.wait_for_edge()
            else:
                self.set_run_status(ev[1], "warn")
        elif kind == "edge_closed":
            self.close_edge_btn.configure(state="normal")
            ok = ev[1]
            self.append_log("Edge closed." if ok else "Edge is still running.")
            if self.start_after_close:
                self.start_after_close = False
                if ok:
                    self.start_run(auto=False)
                else:
                    messagebox.showwarning(WINDOW_TITLE, "Edge could not be closed. Close it manually and try again.")
            elif ok and self.edge_wait_deadline is not None:
                self.start_run(auto=True)
        elif kind == "worker_end":
            self.worker = None
            if self.edge_wait_deadline is None:
                self._set_buttons(False)
            if self.closing:
                self.root.destroy()

    def _tick(self):
        """Every 30 s: roll over to a new day at midnight."""
        if (self.shown_date != storage.today() and not self.running()
                and self.edge_wait_deadline is None and self.close_countdown is None):
            self.refresh_progress()
        self.root.after(30000, self._tick)

    def on_scheduled_signal(self):
        """The scheduled task started while this window was open. That copy exits
        (only one may run) and signals us to start instead."""
        storage.log("Started by the daily schedule (app window was already open).")
        self.append_log("Scheduled start time reached.")
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass
        if not self.running() and self.edge_wait_deadline is None:
            self.start_run(auto=True)

    def on_close(self):
        if self.running():
            if not messagebox.askyesno(WINDOW_TITLE, "Searches are running. Stop them and close?"):
                return
            self.closing = True
            self.stop_event.set()
            self.set_run_status("Stopping and closing…")
            return
        self.root.destroy()


def main():
    autorun = "--autorun" in sys.argv
    signal = create_schedule_signal()
    mutex = acquire_single_instance()
    if mutex is None:
        if autorun:
            # Hand the scheduled start to the window that is already open.
            _kernel32.SetEvent(signal)
            storage.log("Scheduled start passed to the open app window.")
        elif not focus_existing_window():
            r = tk.Tk()
            r.withdraw()
            messagebox.showinfo(WINDOW_TITLE, "Rewards Searcher is already running.")
            r.destroy()
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    storage.ensure_data_dir()
    root = tk.Tk()
    App(root, autorun, signal)
    root.mainloop()


if __name__ == "__main__":
    main()
