import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

from storage import APP_NAME, DATA_DIR, ensure_data_dir

TASK_NAME = APP_NAME
INSTALLED_EXE = os.path.join(DATA_DIR, f"{APP_NAME}.exe")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SchedulerError(RuntimeError):
    pass


def is_frozen():
    return getattr(sys, "frozen", False)


def _run_schtasks(args):
    try:
        proc = subprocess.run(["schtasks", *args], capture_output=True, text=True,
                              creationflags=NO_WINDOW)
    except OSError as exc:
        raise SchedulerError(f"Could not run schtasks: {exc}")
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def install_copy():
    """Copy the running exe to a fixed folder so the task keeps working even if
    the original was run from Downloads/a zip and later moved or deleted."""
    ensure_data_dir()
    current = os.path.abspath(sys.executable)
    if os.path.normcase(current) == os.path.normcase(INSTALLED_EXE):
        return INSTALLED_EXE
    try:
        shutil.copy2(current, INSTALLED_EXE)
    except OSError as exc:
        raise SchedulerError(f"Could not copy the app to {INSTALLED_EXE}: {exc}")
    return INSTALLED_EXE


def _task_command():
    if is_frozen():
        exe = install_copy()
        return exe, "--autorun", os.path.dirname(exe)
    # Running from source (testing): use pythonw so no console window appears.
    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
    return pythonw, f'"{app}" --autorun', os.path.dirname(app)


def timezone_name():
    """The PC's time zone as Windows names it, e.g. "Bangladesh Standard Time"."""
    return datetime.datetime.now().astimezone().tzname() or "local time"


def format_12h(hour, minute):
    return f"{(hour % 12) or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def next_run(hour, minute, now=None):
    """Next occurrence of hour:minute in the PC's local time."""
    now = now or datetime.datetime.now()
    run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if run <= now:
        run += datetime.timedelta(days=1)
    return run


def _task_xml(hour, minute, command, arguments, workdir):
    # Start at the next occurrence so registering never counts as a "missed" run.
    # No UTC offset: Task Scheduler then follows the PC's own time zone (and DST).
    start = next_run(hour, minute).strftime("%Y-%m-%dT%H:%M:%S")
    user = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}".lstrip("\\")
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Runs the daily Bing searches for Microsoft Rewards.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(command)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(workdir)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def register(hour, minute):
    command, arguments, workdir = _task_command()
    xml = _task_xml(hour, minute, command, arguments, workdir)
    fd, path = tempfile.mkstemp(suffix=".xml", prefix="rewards_task_")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(xml)
        code, out, err = _run_schtasks(["/Create", "/TN", TASK_NAME, "/XML", path, "/F"])
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if code != 0:
        raise SchedulerError(err or out or f"schtasks failed with code {code}")
    return command


def delete():
    code, out, err = _run_schtasks(["/Delete", "/TN", TASK_NAME, "/F"])
    if code != 0 and exists():
        raise SchedulerError(err or out or f"schtasks failed with code {code}")


def exists():
    code, _, _ = _run_schtasks(["/Query", "/TN", TASK_NAME])
    return code == 0


def query():
    """Returns None if no task is registered, else
    {"time": "HH:MM" (24h, PC's local time) or None, "command": str}."""
    code, out, _ = _run_schtasks(["/Query", "/TN", TASK_NAME, "/XML"])
    if code != 0:
        return None
    start_match = re.search(r"<StartBoundary>([^<]+)</StartBoundary>", out)
    cmd_match = re.search(r"<Command>([^<]*)</Command>", out)
    return {
        "time": _boundary_to_local(start_match.group(1).strip()) if start_match else None,
        "command": cmd_match.group(1) if cmd_match else "",
    }


def _boundary_to_local(value):
    try:
        start = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if start.tzinfo is not None:  # task pinned to a fixed UTC offset
        start = start.astimezone()
    return start.strftime("%H:%M")
