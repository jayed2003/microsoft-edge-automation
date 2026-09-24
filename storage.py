import json
import os
import datetime

APP_NAME = "RewardsSearcher"
DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME
)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
PROGRESS_FILE = os.path.join(DATA_DIR, "progress.json")
DAILY_SET_FILE = os.path.join(DATA_DIR, "dailyset.json")
# The app's own Edge profile, signed in once by the user.
EDGE_PROFILE_DIR = os.path.join(DATA_DIR, "EdgeProfile")
LOG_FILE = os.path.join(DATA_DIR, "log.txt")
MAX_LOG_BYTES = 512 * 1024

DEFAULT_SETTINGS = {
    "schedule_enabled": False,
    "time": "09:00",
    "searches_per_day": 50,
    "signed_in": False,
}


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    ensure_data_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    settings.update(_read_json(SETTINGS_FILE))
    for obsolete in ("use_profile", "profile_dir"):  # replaced by the app's own profile
        settings.pop(obsolete, None)
    return settings


def save_settings(settings):
    _write_json(SETTINGS_FILE, settings)


def today_date():
    return datetime.date.today()


def today():
    return today_date().isoformat()


def load_progress(target):
    """Today's progress. A saved entry from an earlier day counts as 0 done."""
    data = _read_json(PROGRESS_FILE)
    if data.get("date") != today():
        return {"date": today(), "done": 0, "target": target, "last_run": data.get("last_run")}
    data["target"] = target
    data["done"] = int(data.get("done", 0))
    return data


def save_progress(done, target):
    _write_json(PROGRESS_FILE, {
        "date": today(),
        "done": done,
        "target": target,
        "last_run": datetime.datetime.now().isoformat(timespec="seconds"),
    })


def load_daily_set():
    """Today's Daily Set result: {"date", "done", "total", "failed": [titles]}."""
    data = _read_json(DAILY_SET_FILE)
    if data.get("date") != today():
        return {"date": today(), "done": 0, "total": 0, "failed": []}
    return data


def save_daily_set(done, total, failed=()):
    _write_json(DAILY_SET_FILE, {"date": today(), "done": done, "total": total,
                                 "failed": list(failed)})


def log(message):
    try:
        ensure_data_dir()
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_BYTES:
            os.replace(LOG_FILE, LOG_FILE + ".old")
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {message}\n")
    except OSError:
        pass
