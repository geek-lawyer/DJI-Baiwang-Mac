from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path


LABEL = "com.goodday00.baiwang-connect"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def installed() -> bool:
    return PLIST_PATH.exists()


def install() -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    if getattr(sys, "frozen", False):
        app_bundle = Path(sys.executable).resolve().parents[2]
        # Launch through LaunchServices so a later Finder/Dock open activates
        # this same app instance instead of starting a second USB controller.
        arguments = ["/usr/bin/open", "-gj", str(app_bundle), "--args", "--background"]
        environment = {}
    else:
        source_root = Path(__file__).resolve().parents[1]
        arguments = [str(Path(sys.executable).resolve()), "-m", "baiwang_mac", "--background"]
        environment = {"PYTHONPATH": str(source_root)}
    payload = {
        "Label": LABEL,
        "ProgramArguments": arguments,
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    }
    if environment:
        payload["EnvironmentVariables"] = environment
    PLIST_PATH.write_bytes(plistlib.dumps(payload))
    domain = f"gui/{subprocess.check_output(['id', '-u'], text=True).strip()}"
    subprocess.run(["launchctl", "bootout", domain, str(PLIST_PATH)], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(PLIST_PATH)], check=True)


def uninstall() -> None:
    if not PLIST_PATH.exists():
        return
    domain = f"gui/{subprocess.check_output(['id', '-u'], text=True).strip()}"
    subprocess.run(["launchctl", "bootout", domain, str(PLIST_PATH)], capture_output=True)
    PLIST_PATH.unlink(missing_ok=True)
