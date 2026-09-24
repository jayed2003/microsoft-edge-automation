# Microsoft Edge Automation: Rewards Searcher

A Windows app that runs your 50 daily Bing searches in Microsoft Edge. It can start by itself every day at a time you choose.

![Rewards Searcher window](docs/screenshot.png)

> **Heads-up:** automating searches is against the Microsoft Rewards terms. Microsoft can suspend accounts that do it. Use at your own risk.

## Features

- **One file, nothing to install:** Python and Selenium are packed inside `RewardsSearcher.exe`.
- **Status checks:** boxes show whether Python, Selenium and Microsoft Edge are ready.
- **Daily automatic start:** pick a time in 12-hour format. It runs in your PC's own time zone, including daylight saving.
- **Live progress:** an *x / 50* counter and a log. Interrupted runs continue where they stopped, and the count resets at midnight.
- **Edge driver handled for you:** the matching driver is downloaded from Microsoft on each PC. No driver is shipped with the app.
- **Optional signed-in profile:** use your own Edge profile so the searches count for your Microsoft account.

## Download and run

You need:
- Windows 10 or 11
- Microsoft Edge
- Internet

Steps:
1. Download `RewardsSearcher.exe` from the [**Releases**](https://github.com/jayed2003/microsoft-edge-automation/releases) page, or [build it yourself](#build-it-yourself).
2. Double-click it.
   - If Windows says **"Windows protected your PC"**, click **More info → Run anyway**. It says this for any app that isn't from a big publisher.
   - Some antivirus programs flag packed Python apps. If yours blocks the file, allow it.
3. Wait for the **Python**, **Selenium** and **Microsoft Edge** boxes to turn green ✓. The first time, the Edge box downloads the driver that matches your Edge.
4. Click **Start now**, or set up the daily start below.

## Using it

### Start automatically every day

1. Under **Automatic daily start**, pick the hour, minutes and **AM | PM**.
2. Click **Save schedule**. You only do this once.

Good to know:
- **Time zone:** your PC's time zone is shown next to the time field. If it's wrong, fix it in **Settings → Time & Language → Date & time**.
- **At the chosen time:** the app opens, Edge opens, and the searches run. The window closes 10 seconds after they finish.
- **App already open:** the open window starts the searches itself.
- **PC off or asleep:** the searches start as soon as you're back. The PC has to be on and you have to be signed in to Windows.
- **On a laptop:** it also runs on battery.
- **The downloaded exe:** you can move or delete it after saving. The app installs its own copy in `%LOCALAPPDATA%\RewardsSearcher\`, and the schedule uses that copy.
- **Stopping it:** click **Turn off**.

### Getting the points on your account

By default, Edge opens with a fresh profile. That profile is only signed in to your Microsoft account if Windows itself is signed in with the same account.

If your points aren't going up:
1. Turn on **Use my signed-in Edge profile** in **Settings**.
2. Pick your profile.
3. Edge must be **fully closed** while the searches run. **Close Edge now** does that for you, and a scheduled run waits up to 30 minutes for it.

You can also change **Searches per day** in **Settings** (default 50).

### Problems

| What you see | What to do |
|---|---|
| Edge box is ✗ *"Driver download failed"* | Connect to the internet and reopen the app. A driver download is needed the first time and after each Edge update. |
| Edge box is ✗ *"Not found"* | Install Microsoft Edge from [microsoft.com/edge](https://www.microsoft.com/edge). |
| *"Edge was closed, so the searches stopped at x/50"* | The Edge window was closed during the run. Click **Start now** to continue. |
| *"The schedule points to a missing file"* | Click **Save schedule** again. |
| Anything else, or a scheduled run didn't happen | Open `%LOCALAPPDATA%\RewardsSearcher\log.txt`. Every run is logged there, including scheduled ones. |

### Uninstall

1. Click **Turn off** in the app.
2. Delete the folder `%LOCALAPPDATA%\RewardsSearcher`.

## Build it yourself

You need Python 3.12 or newer on Windows.

```bat
git clone https://github.com/jayed2003/microsoft-edge-automation.git
cd microsoft-edge-automation
build_exe.bat
```

`build_exe.bat` does three things:
1. Creates a local `.venv`.
2. Installs Selenium and PyInstaller into it.
3. Builds a single self-contained `dist\RewardsSearcher.exe`. That is the only file you need to share.

To run from source instead:

```bat
pip install selenium
python app.py
```

`python script.py` runs the 50 searches without the window.

### Project files

| File | Purpose |
|---|---|
| `app.py` | The window and entry point. The scheduled task starts it with `--autorun`. |
| `script.py` | The search engine: starts Edge through Selenium and runs the Bing searches |
| `scheduler.py` | Creates, reads and removes the Windows Task Scheduler task |
| `storage.py` | Settings, today's progress and the log |
| `widgets.py` | The rounded boxes, buttons, AM/PM toggle and on/off switch, drawn in code with no extra libraries |
| `build_exe.bat` | Builds `dist\RewardsSearcher.exe` with PyInstaller |

### How it works

- **Edge driver:** Selenium Manager, which is part of Selenium, downloads the driver matching the installed Edge from Microsoft. It caches the driver in `%USERPROFILE%\.cache\selenium`, and downloads a new one only after Edge updates.
- **Schedule:** a per-user task named `RewardsSearcher` is registered with `schtasks /Create /XML`, so no admin rights are needed. Its settings:
  - Daily trigger in local time.
  - Start when available: missed runs happen later.
  - Runs on battery.
  - Runs only while the user is logged on, because Edge must be visible.
  - The action is `%LOCALAPPDATA%\RewardsSearcher\RewardsSearcher.exe --autorun`.
- **One copy at a time:** a named mutex keeps a second copy from starting. When the scheduled copy finds the app already open, it signals the open window through a named event and exits, and the open window starts the searches.
- **Data:** everything is stored in `%LOCALAPPDATA%\RewardsSearcher\`:
  - `settings.json`: time, searches per day and profile choice
  - `progress.json`: today's count
  - `log.txt`: run history
  - `RewardsSearcher.exe`: the installed copy the schedule runs
