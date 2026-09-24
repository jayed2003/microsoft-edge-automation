"""Completes the Microsoft Rewards Daily Set on rewards.bing.com.

Opening a Daily Set card from the dashboard is what earns its points (the quiz or
page inside doesn't have to be finished), so each card is clicked, the tab it
opens is given a few seconds to load, and then closed. The dashboard's own
"Daily Set  Activity: x/3" counter is read before and after to verify.

The dashboard changes from time to time; if it does, the lookups in _FIND_CARDS
and _READ_COUNTER are the parts to update.
"""
import random
import time

from selenium.common.exceptions import (
    ElementClickInterceptedException, TimeoutException, WebDriverException,
)
from selenium.webdriver.support.ui import WebDriverWait

import script
from storage import EDGE_PROFILE_DIR

DASHBOARD_URL = script.REWARDS_URL + "dashboard"

# The "Daily set" section's cards: links inside the section headed "Daily set".
_FIND_CARDS = """
const heading = [...document.querySelectorAll('h1,h2,h3')]
    .find(e => e.textContent.trim().toLowerCase() === 'daily set');
if (!heading) return [];
let box = heading.closest('.react-aria-Disclosure');
if (!box) {
  box = heading;
  while (box && box.querySelectorAll('a[href]').length === 0) box = box.parentElement;
}
return box ? [...box.querySelectorAll('a[href]')] : [];
"""

# [done, total] from the "Your activity" tile: "Daily Set" / "Activity: 0/3".
_READ_COUNTER = """
const label = [...document.querySelectorAll('p,span,div')]
    .find(e => e.children.length === 0 && e.textContent.trim() === 'Daily Set');
let box = label;
while (box && !/Activity:\\s*\\d+\\s*\\/\\s*\\d+/.test(box.innerText)) box = box.parentElement;
const m = box && box.innerText.match(/Activity:\\s*(\\d+)\\s*\\/\\s*(\\d+)/);
return m ? [parseInt(m[1]), parseInt(m[2])] : null;
"""


class NotSignedInError(RuntimeError):
    """The app's Edge profile isn't signed in to Microsoft Rewards."""


def _card_title(card):
    lines = [line.strip() for line in (card.text or "").splitlines() if line.strip()]
    return lines[0] if lines else "Daily Set activity"


def _load_dashboard(driver, pause):
    """Opens the dashboard and returns its Daily Set cards."""
    for attempt in range(3):
        driver.get(DASHBOARD_URL)
        pause(6)
        if script.is_bing_error_page(driver):
            pause(10)
            continue
        if not script.is_signed_in_page(driver):
            raise NotSignedInError(
                "The app isn't signed in to Microsoft Rewards. Click Sign in… in Settings.")
        for _ in range(5):  # the cards render a moment after the page
            cards = driver.execute_script(_FIND_CARDS)
            if cards:
                return cards
            pause(2)
        raise RuntimeError("Couldn't find the Daily set on the Rewards dashboard. "
                           "Microsoft may have changed the page; the app needs an update.")
    raise script.BingUnavailableError("Bing isn't available right now. Try again in a few minutes.")


def _open_card(driver, card, dashboard, pause):
    """Clicks a card, waits on the tab it opens, closes it, returns to the dashboard."""
    before = set(driver.window_handles)
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'})", card)
    pause(random.uniform(1, 2))
    try:
        card.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click()", card)
    try:
        WebDriverWait(driver, 10).until(lambda d: len(set(d.window_handles) - before) > 0)
    except TimeoutException:
        # Opened in the same tab instead: give it time, then go back.
        pause(random.uniform(6, 9))
        driver.get(DASHBOARD_URL)
        pause(4)
        return
    new_tab = (set(driver.window_handles) - before).pop()
    driver.switch_to.window(new_tab)
    pause(random.uniform(6, 9))
    driver.close()
    driver.switch_to.window(dashboard)


def run_daily_set(stop_event=None, on_event=None):
    """Opens every card of today's Daily Set. Returns (done, total, failed_titles).

    on_event(kind, *args) receives ("log", msg) and ("dailyset", step, total, title).
    Raises NotSignedInError, script.BingUnavailableError, script.ProfileInUseError,
    script.BrowserClosedError or RuntimeError.
    """
    emit = on_event or (lambda kind, *a: print(*a) if kind == "log" else None)
    log = lambda msg: emit("log", msg)

    def pause(seconds):
        if stop_event is not None:
            stop_event.wait(seconds)
        else:
            time.sleep(seconds)

    driver = script.start_edge(EDGE_PROFILE_DIR, log=log)
    failed = []
    try:
        log("Opening the Rewards dashboard...")
        cards = _load_dashboard(driver, pause)
        counter = driver.execute_script(_READ_COUNTER)
        total = counter[1] if counter else len(cards)
        if counter and counter[0] >= counter[1]:
            log(f"Daily Set already done today ({counter[0]}/{counter[1]}).")
            return counter[0], counter[1], []
        log(f"Daily Set: {counter[0]}/{counter[1]} done so far." if counter
            else f"Found {len(cards)} Daily Set activities.")

        dashboard = driver.current_window_handle
        count = len(cards)
        for i in range(count):
            if stop_event is not None and stop_event.is_set():
                log("Stopped.")
                break
            cards = driver.execute_script(_FIND_CARDS)  # re-find: the page may re-render
            if i >= len(cards):
                break
            title = _card_title(cards[i])
            emit("dailyset", i + 1, count, title)
            log(f"[{i + 1}/{count}] Opening '{title}'")
            try:
                _open_card(driver, cards[i], dashboard, pause)
            except WebDriverException as exc:
                if script._browser_gone(exc):
                    raise
                failed.append(title)
                log(f"Couldn't open '{title}': {exc.msg or exc}")
                driver.switch_to.window(dashboard)
            pause(random.uniform(2, 4))

        log("Checking the result...")
        driver.get(DASHBOARD_URL)
        pause(6)
        counter = driver.execute_script(_READ_COUNTER)
        if counter:
            done, total = counter
        else:
            done = count - len(failed)
            log("Couldn't read the Daily Set counter to double-check.")
        log(f"Daily Set: {done}/{total} done.")
        return done, total, failed

    except WebDriverException as exc:
        if script._browser_gone(exc):
            raise script.BrowserClosedError(
                "Edge was closed, so the Daily Set stopped. Click Do Daily Set now to continue."
            ) from None
        raise RuntimeError(f"Edge stopped responding: {exc.msg or exc}") from None

    finally:
        try:
            driver.quit()
        except WebDriverException:
            pass
