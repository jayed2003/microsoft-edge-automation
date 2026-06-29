# Microsoft Rewards Search Launcher

This folder contains a Python script and a batch file that help run the browser automation.

## Files

- `run_with_setup.bat` - Checks for Python and Selenium, installs them if possible, then runs the script
- `script.py` - The Python automation script

## Before You Start

The user should have:

- Windows
- Microsoft Edge installed
- An internet connection

## Only if you have problems with the script ##

- Fallback Microsoft Edge driver "msedgedriver.exe" if you have problems with the script.

The batch file can try to install Python automatically, but this only works if `winget` is available on the PC.

## Easiest Way To Run

1. Put the whole folder on the other PC.
2. Double-click `run_with_setup.bat`.
3. Wait while it checks for Python and Selenium.
4. If needed, allow Windows prompts for installation.
5. The script will start automatically after setup finishes.

## What The Batch File Does

When `run_with_setup.bat` runs, it:

1. Checks whether Python is installed
2. Tries to install Python automatically with `winget` if Python is missing
3. Checks whether the `selenium` package is installed
4. Installs `selenium` if it is missing
5. Starts `script.py`

## If Python Does Not Install Automatically

If the batch file says Python could not be installed:

1. Install Python manually from [python.org](https://www.python.org/downloads/)
2. During setup, enable the option to add Python to `PATH` if it is shown
3. Run `run_with_setup.bat` again

## If Selenium Fails To Install

Open Command Prompt in this folder and run:

```bat
python -m pip install selenium
```

If `python` does not work, try:

```bat
py -3 -m pip install selenium
```

## Common Problems

### Edge Driver Version Problem

If Edge opens poorly or the script fails to start the browser, the local `msedgedriver.exe` may not match the installed version of Microsoft Edge on that PC.

The script first tries Selenium Manager, which usually fixes this automatically. If that still does not work, update Microsoft Edge and try again.

### `winget` Is Missing

Some Windows installs do not have `winget`. In that case, Python must be installed manually.

### Permission Prompts

Windows may ask for permission before installing software. The user must allow those prompts for automatic setup to work.

## Manual Run Option

If needed, the script can also be started manually:

```bat
python script.py
```

or:

```bat
py -3 script.py
```

## Share Tip

When sharing this project, send the entire `edgedriver_win64` folder, not just one file.
