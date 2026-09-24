@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === Building RewardsSearcher.exe ===
echo.

rem Pick a real Python (py launcher first; "python" alone may be the Microsoft Store stub).
set "PY="
for %%V in (3.13 3.12 3) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Python was not found. Install it from https://www.python.org/downloads/ and try again.
    goto :fail
)
echo Using: %PY%

if not exist ".venv\Scripts\python.exe" (
    echo Creating build environment...
    %PY% -m venv .venv || goto :fail
)
set "VPY=.venv\Scripts\python.exe"

echo Installing build tools...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install --upgrade selenium pyinstaller || goto :fail

echo Building...
rem Temporary build files go to %TEMP% so only dist\ is left in this folder.
set "WORK=%TEMP%\RewardsSearcher-build"
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name RewardsSearcher ^
    --collect-all selenium ^
    --workpath "%WORK%" --specpath "%WORK%" ^
    "%~dp0app.py" || goto :fail
rmdir /s /q "%WORK%" >nul 2>&1

echo.
echo Done: %~dp0dist\RewardsSearcher.exe
echo Share that single file.
goto :end

:fail
echo.
echo Build failed.
exit /b 1

:end
endlocal
