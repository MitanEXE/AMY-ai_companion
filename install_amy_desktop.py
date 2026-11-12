#!/usr/bin/env python3
"""Install the AMY launcher and Qt environment under your home directory."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def desktop_entry(interpreter, script, port):
    def quote(path):
        value = str(path)
        if any(char in value for char in ("\r", "\n", "\x00")):
            raise ValueError("Move AMY to a folder whose path fits on one line.")
        for char in ('\\', '"', '`', '$'):
            value = value.replace(char, '\\' + char)
        value = value.replace('\\', '\\\\').replace("%", "%%")
        return '"' + value + '"'

    return (
        "[Desktop Entry]\nType=Application\nName=AMY\nComment=Local AI companion\n"
        f"Exec={quote(interpreter)} {quote(script)} --port {port}\n"
        "Icon=applications-utilities\nTerminal=false\nCategories=Utility;\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=11435, help="Local Ollama port (default: 11435)")
    args = parser.parse_args()
    if sys.platform != "linux" or sys.version_info < (3, 12):
        parser.error("The Linux desktop installer requires Linux and Python 3.12 or newer.")
    if not 1 <= args.port <= 65535:
        parser.error("Choose a local port from 1 to 65535.")
    uv = shutil.which("uv")
    if not uv:
        parser.error("Install uv first. See docs/LINUX_DESKTOP.md.")
    source = Path(__file__).resolve().parent
    home = Path.home().resolve()
    data = home / ".local/share/mitan-jarvis"
    environment = data / "desktop-env"
    interpreter = environment / "bin/python"
    data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
    if not data_home.is_absolute():
        data_home = home / ".local/share"
    launcher = data_home / "applications/amy.desktop"
    for folder in (data, environment, launcher.parent):
        if not folder.resolve().is_relative_to(home):
            parser.error(f"Choose an install location inside your home folder. Check {folder}.")
    entry = desktop_entry(interpreter, source / "amy_desktop.py", args.port)
    print(f"Install Qt into {environment}.")
    print(f"Create or update the AMY app launcher at {launcher}.")
    print(f"The launcher runs AMY from {source}. Keep this folder after installation.")
    print("The Qt install may download packages. Ollama models and voice files are installed separately.")
    try:
        approve = input("Install? [Y/n] (Enter = yes): ").strip().casefold()
    except (EOFError, KeyboardInterrupt):
        approve = "no"
    if approve not in ("", "yes", "y"):
        print("Installation canceled.")
        return 0
    if launcher.is_symlink() or environment.is_symlink():
        parser.error("Inspect the existing launcher or desktop environment symlink first.")
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    variables = {**os.environ, "UV_CACHE_DIR": str(data / "uv-cache")}
    if not interpreter.is_file():
        subprocess.run([uv, "venv", "--python", sys.executable, str(environment)], check=True, env=variables)
    subprocess.run([uv, "pip", "install", "--python", str(interpreter), "-r", str(source / "requirements-desktop.txt")],
                   check=True, env=variables)
    subprocess.run([str(interpreter), "-c",
                    "from PySide6.QtWidgets import QApplication; assert QApplication([]).platformName() == 'offscreen'"],
                   check=True, env={**variables, "QT_QPA_PLATFORM": "offscreen"})
    launcher.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=launcher.parent, prefix=".amy-", suffix=".desktop",
                                     encoding="utf-8", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(entry)
    try:
        validator = shutil.which("desktop-file-validate")
        if validator:
            subprocess.run([validator, str(temporary)], check=True)
        temporary.replace(launcher)
    finally:
        temporary.unlink(missing_ok=True)
    if launcher.read_text(encoding="utf-8") != entry:
        raise RuntimeError("Could not verify the installed launcher.")
    print("Installed and verified. Open AMY from your app launcher.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as error:
        sys.exit(f"AMY install stopped: {error}")
