"""Build native desktop app bundles using PyInstaller.

Run with uv so the build dependency group is resolved automatically:
    uv run --group build python scripts/build_desktop_app.py
"""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY_SCRIPT = ROOT / "src" / "youtube_video_downloader" / "gui_main.py"
APP_NAME = "YouTubeVideoDownloader"


def _platform_suffix() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    if system == "darwin":
        return "macos"
    return system


def build() -> int:
    dist_path = ROOT / "dist" / _platform_suffix()
    build_path = ROOT / "build" / _platform_suffix()
    is_windows = platform.system().lower() == "windows"
    data_sep = ";" if is_windows else ":"
    icon_png = ROOT / "assets" / "app_icon.png"
    icon_ico = ROOT / "assets" / "app_icon.ico"

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        APP_NAME,
        "--distpath",
        str(dist_path),
        "--workpath",
        str(build_path),
        "--specpath",
        str(build_path),
        "--collect-submodules",
        "yt_dlp",
        "--add-data",
        f"{icon_png}{data_sep}assets",
        "--add-data",
        f"{icon_ico}{data_sep}assets",
        "--paths",
        str(ROOT / "src"),
        "--hidden-import",
        "tkinter",
        str(ENTRY_SCRIPT),
    ]

    if is_windows:
        command.extend(["--icon", str(icon_ico)])

    print("Building desktop app bundle...")
    print(" ".join(command))
    result = subprocess.run(command, cwd=ROOT, check=False)

    if result.returncode == 0:
        if platform.system().lower() == "windows":
            artifact = dist_path / f"{APP_NAME}.exe"
        elif platform.system().lower() == "darwin":
            artifact = dist_path / f"{APP_NAME}.app"
        else:
            artifact = dist_path / APP_NAME
        print(f"Build complete: {artifact}")

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(build())
