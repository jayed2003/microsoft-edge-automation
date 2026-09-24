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

# --- Configuration ---
NUMBER_OF_SEARCHES = 50
MIN_WAIT = 3
MAX_WAIT = 6
MAX_CONSECUTIVE_FAILURES = 5
BING_URL = "https://www.bing.com"
EDGE_USER_DATA_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "User Data"
)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class EdgeRunningError(RuntimeError):
    """Edge is open, so its profile is locked and cannot be used by Selenium."""


class BrowserClosedError(RuntimeError):
    """The Edge window was closed (or crashed) while the searches were running."""


def _browser_gone(exc):
    if isinstance(exc, (InvalidSessionIdException, NoSuchWindowException)):
        return True
    msg = (getattr(exc, "msg", None) or str(exc)).lower()
    return any(s in msg for s in ("disconnected", "not reachable", "invalid session id",
                                  "no such window", "target window already closed"))


def is_edge_running():
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/NH", "/FO", "CSV"],
            capture_output=True, text=True, creationflags=NO_WINDOW,
        ).stdout
    except OSError:
        return False
    return '"msedge.exe"' in out.lower()


def close_edge():
    """Ask Edge to close, then force-close leftovers (e.g. Startup boost)."""
    subprocess.run(["taskkill", "/IM", "msedge.exe"],
                   capture_output=True, creationflags=NO_WINDOW)
    for _ in range(6):
        time.sleep(0.5)
        if not is_edge_running():
            return True
    subprocess.run(["taskkill", "/IM", "msedge.exe", "/F", "/T"],
                   capture_output=True, creationflags=NO_WINDOW)
    time.sleep(1)
    return not is_edge_running()


def build_edge_options(use_profile=False, profile_dir="Default"):
    edge_options = Options()
    edge_options.add_argument("--start-maximized")
    edge_options.add_argument("--no-first-run")
    edge_options.add_argument("--no-default-browser-check")
    # edge_options.add_argument("--inprivate") # Optional: Use Incognito mode
    if use_profile:
        edge_options.add_argument(f"--user-data-dir={EDGE_USER_DATA_DIR}")
        edge_options.add_argument(f"--profile-directory={profile_dir or 'Default'}")
    return edge_options


def create_edge_driver(edge_options, log=print):
    # No driver is shipped with the app. Selenium Manager downloads the driver
    # matching the installed Edge from Microsoft on each PC and caches it.
    try:
        log("Starting Edge with Selenium Manager...")
        return webdriver.Edge(options=edge_options)
    except WebDriverException as exc:
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
                 on_event=None, use_profile=False, profile_dir="Default"):
    """Run searches until `target` is reached, starting from `already_done`.

    on_event(kind, *args) receives ("log", msg), ("progress", done, target, query)
    and ("stopped", done, target). Returns the number of searches done.
    Raises EdgeRunningError / RuntimeError when Edge cannot be started, and
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

    if use_profile and is_edge_running():
        raise EdgeRunningError(
            "Microsoft Edge is open. Close it (including background Edge) to use your profile."
        )

    driver = create_edge_driver(build_edge_options(use_profile, profile_dir), log=log)
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
