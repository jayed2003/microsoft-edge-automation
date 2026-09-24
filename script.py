import time
import random
import os
import subprocess
from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException, NoSuchWindowException, WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.edge.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from storage import EDGE_PROFILE_DIR

# --- Configuration ---
NUMBER_OF_SEARCHES = 50
MIN_WAIT = 3
MAX_WAIT = 6
MAX_CONSECUTIVE_FAILURES = 5
BING_URL = "https://www.bing.com"
REWARDS_URL = "https://rewards.bing.com/"
EDGE_CLIENT_KEY = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{56EB18F8-B008-4CBD-B6D2-8C97FE7E9062}"
EDGE_APP_PATH_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class ProfileInUseError(RuntimeError):
    """The app's Edge profile is still open in another Edge window (e.g. sign-in)."""


class BrowserClosedError(RuntimeError):
    """The Edge window was closed (or crashed) while the searches were running."""


def _browser_gone(exc):
    if isinstance(exc, (InvalidSessionIdException, NoSuchWindowException)):
        return True
    msg = (getattr(exc, "msg", None) or str(exc)).lower()
    return any(s in msg for s in ("disconnected", "not reachable", "invalid session id",
                                  "no such window", "target window already closed"))


# --- Microsoft Edge on this PC -------------------------------------------------

def _registry_value(hive, key, name):
    import winreg
    try:
        with winreg.OpenKey(hive, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def edge_version():
    import winreg
    for hive, key in (
        (winreg.HKEY_LOCAL_MACHINE, EDGE_CLIENT_KEY.replace("SOFTWARE\\", "SOFTWARE\\WOW6432Node\\", 1)),
        (winreg.HKEY_LOCAL_MACHINE, EDGE_CLIENT_KEY),
        (winreg.HKEY_CURRENT_USER, EDGE_CLIENT_KEY),
    ):
        version = _registry_value(hive, key, "pv")
        if version:
            return version
    return "installed" if edge_exe_path() else None


def edge_exe_path():
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        path = _registry_value(hive, EDGE_APP_PATH_KEY, "")
        if path and os.path.exists(path.strip('"')):
            return path.strip('"')
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        path = os.path.join(base or "", "Microsoft", "Edge", "Application", "msedge.exe")
        if base and os.path.exists(path):
            return path
    return None


# --- The app's own Edge profile ----------------------------------------------------
# The app signs in once in its own profile folder, so searches and the Daily Set
# count for the user's account while their normal Edge stays open.

def app_profile_edge_pids():
    """PIDs of Edge processes using the app's profile folder."""
    needle = EDGE_PROFILE_DIR.lower().replace("'", "''")
    command = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object "
               f"{{ $_.CommandLine -and $_.CommandLine.ToLower().Contains('{needle}') }} | "
               "ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                             capture_output=True, text=True, creationflags=NO_WINDOW).stdout
    except OSError:
        return []
    return [int(pid) for pid in out.split() if pid.isdigit()]


def close_app_profile_edge():
    """Closes Edge windows that use the app's profile (never the user's own Edge).
    Asks them to close first, so cookies such as the sign-in are saved."""
    pids = app_profile_edge_pids()
    if not pids:
        return True
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
    for _ in range(10):
        time.sleep(0.5)
        pids = app_profile_edge_pids()
        if not pids:
            return True
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"],
                       capture_output=True, creationflags=NO_WINDOW)
    time.sleep(1)
    return not app_profile_edge_pids()


def open_signin_window():
    """Opens a normal (not automated) Edge window on the app's profile at the
    Rewards page, where the user signs in themselves. Returns the process."""
    exe = edge_exe_path()
    if not exe:
        raise RuntimeError("Microsoft Edge was not found. Install it from microsoft.com/edge.")
    os.makedirs(EDGE_PROFILE_DIR, exist_ok=True)
    return subprocess.Popen([exe, f"--user-data-dir={EDGE_PROFILE_DIR}", "--no-first-run",
                             "--no-default-browser-check", "--new-window", REWARDS_URL])


class BingUnavailableError(RuntimeError):
    """Bing showed its "It's not you, it's us" error page."""


def is_bing_error_page(driver):
    return bool(driver.find_elements(By.CSS_SELECTOR, "#sw_content .panda, .panda img"))


def is_signed_in_page(driver):
    """On rewards.bing.com: signed-out visitors are sent to /about with Sign in links;
    signed-in ones stay on the dashboard, which has the site's navigation tabs."""
    url = driver.current_url.lower()
    if "/about" in url or "login.live.com" in url or is_bing_error_page(driver):
        return False
    sign_in = driver.find_elements(By.CSS_SELECTOR, "a[href^='/auth/login']")
    if any(link.is_displayed() for link in sign_in):
        return False
    return bool(driver.find_elements(By.CSS_SELECTOR, "a[href='/dashboard'], a[href='/earn']"))


def check_signed_in(log=print):
    """True if the app's Edge profile is signed in to Microsoft Rewards."""
    if not os.path.isdir(EDGE_PROFILE_DIR):
        return False
    driver = start_edge(EDGE_PROFILE_DIR, headless=True, log=log)
    try:
        for attempt in range(3):
            driver.get(REWARDS_URL + "dashboard")
            time.sleep(5)  # let the page finish redirecting
            if not is_bing_error_page(driver):
                return is_signed_in_page(driver)
            time.sleep(10)
        raise BingUnavailableError("Bing isn't available right now. Try again in a few minutes.")
    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass


def build_edge_options(profile_dir=None, headless=False):
    edge_options = Options()
    edge_options.add_argument("--start-maximized")
    edge_options.add_argument("--no-first-run")
    edge_options.add_argument("--no-default-browser-check")
    # edge_options.add_argument("--inprivate") # Optional: Use Incognito mode
    if profile_dir:
        edge_options.add_argument(f"--user-data-dir={profile_dir}")
    if headless:
        edge_options.add_argument("--headless=new")
        edge_options.add_argument("--window-size=1280,900")
    return edge_options


def start_edge(profile_dir=None, headless=False, log=print):
    """Starts Selenium-controlled Edge, on the app's profile when profile_dir is given."""
    if profile_dir and app_profile_edge_pids():
        log("Closing a leftover Edge window that uses the app's profile...")
        if not close_app_profile_edge():
            raise ProfileInUseError("Close the Edge window you signed in with, then try again.")
    return create_edge_driver(build_edge_options(profile_dir, headless), log)


def create_edge_driver(edge_options, log=print):
    # No driver is shipped with the app. Selenium Manager downloads the driver
    # matching the installed Edge from Microsoft on each PC and caches it.
    try:
        log("Starting Edge with Selenium Manager...")
        return webdriver.Edge(options=edge_options)
    except WebDriverException as exc:
        if "already in use" in (exc.msg or str(exc)).lower():
            raise ProfileInUseError("Close the Edge window you signed in with, then try again.")
        raise RuntimeError("\n".join([
            "Unable to start Microsoft Edge.",
            "Make sure Microsoft Edge is installed and up to date.",
            "The first run (and the first run after an Edge update) needs internet "
            "so the matching Edge driver can be downloaded.",
            f"Details: {exc.msg or exc}",
        ]))

def get_random_search_query():
    search_intents = [
        "how to", "best", "top 10", "latest news about", "history of",
        "why is", "reviews for", "cheap", "guide to", "alternatives to"
    ]

    topics = [
        "python programming", "artificial intelligence", "stock market", "cryptocurrency",
        "gaming laptops", "wireless headphones", "electric cars", "sustainable living",
        "remote work tips", "digital marketing", "healthy recipes", "yoga for beginners",
        "marvel movies", "space exploration", "new iphone", "android features",
        "travel destinations 2025", "home workout"
    ]

    intent = random.choice(search_intents)
    topic = random.choice(topics)

    return f"{intent} {topic}"


def _print_event(kind, *args):
    if kind == "log":
        print(args[0])


def _close_old_tab(driver, old_tab):
    # Close the OLD tab and switch to whatever tab is left.
    # After closing a tab, Selenium needs to be told explicitly where to look next
    try:
        handles = driver.window_handles
        if len(handles) > 1 and old_tab in handles:
            driver.switch_to.window(old_tab)
            driver.close()
        driver.switch_to.window(driver.window_handles[-1])
    except WebDriverException:
        pass


def run_searches(target=NUMBER_OF_SEARCHES, already_done=0, stop_event=None,
                 on_event=None, profile_dir=None):
    """Run searches until `target` is reached, starting from `already_done`.

    on_event(kind, *args) receives ("log", msg), ("progress", done, target, query)
    and ("stopped", done, target). Returns the number of searches done.
    profile_dir: the app's signed-in Edge profile, or None for a fresh profile.
    Raises ProfileInUseError / RuntimeError when Edge cannot be started, and
    BrowserClosedError when the Edge window is closed mid-run.
    """
    emit = on_event or _print_event
    log = lambda msg: emit("log", msg)

    def stopped():
        return stop_event is not None and stop_event.is_set()

    def pause(seconds):
        if stop_event is not None:
            stop_event.wait(seconds)
        else:
            time.sleep(seconds)

    done = already_done
    if done >= target:
        log(f"Already done today ({done}/{target}).")
        return done

    driver = start_edge(profile_dir, log=log)
    failures = 0

    try:
        log("Browser started...")

        # Open Bing initially to have a starting point
        driver.get(BING_URL)
        pause(2)

        while done < target:
            if stopped():
                log(f"Stopped at {done}/{target}.")
                emit("stopped", done, target)
                break

            # 1. Identify the current tab (which will become the 'old' tab)
            old_tab = driver.current_window_handle
            try:
                # 2. Open a NEW tab and go to Bing homepage in it
                driver.switch_to.new_window('tab')
                driver.get(BING_URL)

                query = get_random_search_query()
                log(f"[{done + 1}/{target}] Typing: '{query}'")

                # 3. Find the search box and type the query
                # Bing's search box usually has the name attribute "q"
                search_box = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.NAME, "q"))
                )
                search_box.clear() # Clear any pre-filled text
                search_box.send_keys(query) # Type the plain text
                time.sleep(0.5) # Tiny pause like a human thinking
                search_box.send_keys(Keys.RETURN) # Press Enter

                done += 1
                failures = 0
                emit("progress", done, target, query)

                # 4. Wait for results to load
                pause(random.uniform(MIN_WAIT, MAX_WAIT))

            except WebDriverException as e:
                if _browser_gone(e):
                    raise
                failures += 1
                log(f"Search failed ({failures}/{MAX_CONSECUTIVE_FAILURES}): {e.msg or e}")
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    raise RuntimeError(
                        "Too many failed searches in a row. Check your internet connection."
                    )
            finally:
                _close_old_tab(driver, old_tab)

        if done >= target:
            log("All searches completed successfully.")

    except WebDriverException as e:
        if _browser_gone(e):
            raise BrowserClosedError(
                f"Edge was closed, so the searches stopped at {done}/{target}. "
                "Click Start now to continue."
            ) from None
        raise RuntimeError(f"Edge stopped responding: {e.msg or e}") from None

    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass
        log("Browser closed.")

    return done


def perform_typing_searches():
    try:
        run_searches(NUMBER_OF_SEARCHES)
    except Exception as e:
        print(f"Critical Error: {e}")


if __name__ == "__main__":
    perform_typing_searches()
