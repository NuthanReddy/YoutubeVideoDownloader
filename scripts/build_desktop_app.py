"""Build native desktop app bundles using PyInstaller.

Run with uv so the build dependency group is resolved automatically:
    uv run --group build python scripts/build_desktop_app.py
"""

from __future__ import annotations

import platform
import shutil
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


def _stage_ffmpeg(stage_dir: Path, is_windows: bool) -> Path | None:
    """Copy imageio-ffmpeg's bundled binary to a clean ``ffmpeg`` name.

    ``imageio-ffmpeg`` ships an architecture-matched ffmpeg inside its wheel, so
    the binary automatically matches the interpreter PyInstaller is freezing
    (Windows x64, macOS x86_64 under Rosetta, macOS arm64). We copy it to a
    predictable filename so the app can point ``ffmpeg_location`` at the folder
    without depending on imageio's versioned name.
    """

    try:
        import imageio_ffmpeg
    except ImportError:
        print(
            "WARNING: imageio-ffmpeg is not installed; the app will be built "
            "WITHOUT a bundled ffmpeg. Install the build dependency group "
            "(uv run --group build ...) so downloads can merge HD streams.",
            file=sys.stderr,
        )
        return None

    source = Path(imageio_ffmpeg.get_ffmpeg_exe())
    if not source.exists():
        print(f"WARNING: imageio-ffmpeg binary not found at {source}", file=sys.stderr)
        return None

    stage_dir.mkdir(parents=True, exist_ok=True)
    target = stage_dir / ("ffmpeg.exe" if is_windows else "ffmpeg")
    shutil.copy2(source, target)
    if not is_windows:
        target.chmod(0o755)
    print(f"Staged ffmpeg: {source} -> {target}")
    return target


def build() -> int:
    dist_path = ROOT / "dist" / _platform_suffix()
    build_path = ROOT / "build" / _platform_suffix()
    is_windows = platform.system().lower() == "windows"
    is_macos = platform.system().lower() == "darwin"
    data_sep = ";" if is_windows else ":"
    icon_png = ROOT / "assets" / "app_icon.png"
    icon_ico = ROOT / "assets" / "app_icon.ico"
    icon_icns = ROOT / "assets" / "app_icon.icns"

    ffmpeg_binary = _stage_ffmpeg(build_path / "ffmpeg_stage", is_windows)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
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

    if ffmpeg_binary is not None:
        command[-1:-1] = ["--add-binary", f"{ffmpeg_binary}{data_sep}ffmpeg_bin"]

    if is_windows:
        command.extend(["--icon", str(icon_ico)])
    elif is_macos:
        command.extend(["--icon", str(icon_icns)])

    print("Building desktop app bundle...")
    print(" ".join(command))
    result = subprocess.run(command, cwd=ROOT, check=False)

    if result.returncode == 0:
        if is_windows:
            artifact = dist_path / APP_NAME / f"{APP_NAME}.exe"
        elif is_macos:
            artifact = dist_path / f"{APP_NAME}.app"
        else:
            artifact = dist_path / APP_NAME / APP_NAME
        print(f"Build complete: {artifact}")

    return result.returncode


if __name__ == "__main__":
    raise SystemExit(build())
