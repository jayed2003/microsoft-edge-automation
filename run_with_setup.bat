@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo === Microsoft Rewards Search Launcher ===
echo.

call :resolve_python
if errorlevel 1 (
    echo Python was not found.
    call :install_python
    if errorlevel 1 goto :python_install_failed
    call :resolve_python
    if errorlevel 1 goto :python_install_failed
)

echo Using Python command: %PYTHON_CMD%
echo.

echo Ensuring pip is available...
%PYTHON_CMD% -m ensurepip --upgrade >nul 2>&1

echo Checking Selenium...
%PYTHON_CMD% -c "import selenium" >nul 2>&1
if errorlevel 1 (
    echo Selenium is not installed. Installing now...
    %PYTHON_CMD% -m pip install --upgrade pip
    %PYTHON_CMD% -m pip install selenium
    if errorlevel 1 goto :selenium_install_failed
) else (
    echo Selenium is already installed.
)

echo.
echo Starting the Python script...
%PYTHON_CMD% "%~dp0__pycache__\script.cpython-314.pyc"
goto :done

:resolve_python
set "PYTHON_CMD="
where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
    exit /b 0
)

where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON_CMD=python"
    exit /b 0
)

exit /b 1

:install_python
where winget >nul 2>&1
if errorlevel 1 (
    echo winget is not available on this PC.
    echo Please install Python manually from https://www.python.org/downloads/
    exit /b 1
)

echo Attempting to install Python automatically with winget...
winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo Python 3.13 install failed. Trying Python 3.12...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo Automatic Python installation failed.
        exit /b 1
    )
)

echo Python installation command completed.
set "PATH=%LocalAppData%\Programs\Python\Python313\;%LocalAppData%\Programs\Python\Python313\Scripts\;%LocalAppData%\Programs\Python\Python312\;%LocalAppData%\Programs\Python\Python312\Scripts\;%PATH%"
exit /b 0

:python_install_failed
echo.
echo Could not install or detect Python automatically.
echo Install Python, then run this batch file again.
goto :pause_and_exit

:selenium_install_failed
echo.
echo Selenium installation failed.
echo Try running this manually in Command Prompt:
echo python -m pip install selenium
goto :pause_and_exit

:done
echo.
echo Finished.

:pause_and_exit
echo.
pause
