import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path


def take_screenshot():
    path = Path(tempfile.gettempdir()) / "obris_capture.png"

    if sys.platform == "darwin":
        cmd = ["screencapture", "-i", str(path)]
    elif sys.platform.startswith("linux"):
        cmd = ["scrot", "-s", str(path)]
    else:
        raise SystemExit(f"Unsupported platform: {sys.platform}")

    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise SystemExit("Screenshot cancelled.")

    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit("Screenshot cancelled.")

    return path


def prompt_name():
    if sys.platform == "darwin":
        result = subprocess.run(
            [
                "osascript",
                "-e",
                'display dialog "Name this capture:" default answer ""',
                "-e",
                "text returned of result",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SystemExit("Cancelled.")
        return result.stdout.strip()
    else:
        import click

        return click.prompt("Name this capture")


def auto_name():
    return datetime.now().strftime("ObrisCapture %Y-%m-%d at %H.%M.%S")
