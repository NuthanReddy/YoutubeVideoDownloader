"""Build native desktop app bundles using PyInstaller.

Run with uv so the build dependency group is resolved automatically:
    uv run --group build python scripts/build_desktop_app.py
"""

from __future__ import annotations

import io
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRY_SCRIPT = ROOT / "src" / "youtube_video_downloader" / "gui_main.py"
APP_NAME = "YouTubeVideoDownloader"

# Deno is bundled so packaged apps have the JavaScript runtime that YouTube's
# ``n``-signature challenge needs; without it yt-dlp only sees pre-muxed <=360p
# streams (or "video not available"). Pinned to a known-good release for
# reproducible CI builds. Paired with the bundled ``yt-dlp-ejs`` solver scripts
# (``--collect-all yt_dlp_ejs``) Deno runs fully offline via its minified core
# script -- no npm, no network at solve time.
DENO_VERSION = "v2.9.2"
_DENO_ASSETS = {
    ("windows", "amd64"): "deno-x86_64-pc-windows-msvc.zip",
    ("windows", "x86_64"): "deno-x86_64-pc-windows-msvc.zip",
    ("darwin", "arm64"): "deno-aarch64-apple-darwin.zip",
    ("darwin", "aarch64"): "deno-aarch64-apple-darwin.zip",
    ("darwin", "x86_64"): "deno-x86_64-apple-darwin.zip",
    ("linux", "x86_64"): "deno-x86_64-unknown-linux-gnu.zip",
    ("linux", "amd64"): "deno-x86_64-unknown-linux-gnu.zip",
}


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


def _stage_deno(stage_dir: Path, is_windows: bool) -> Path:
    """Download the arch-matched Deno binary and stage it for bundling.

    Selects the Deno release asset that matches the interpreter PyInstaller is
    freezing (so the frozen app ships a runnable binary on each CI target),
    downloads and extracts it, and returns the path to the ``deno`` executable.

    Raises on failure -- a build without Deno would silently regress packaged
    apps back to a 360p cap, so we fail loudly rather than ship that.
    """

    system = platform.system().lower()
    machine = platform.machine().lower()
    asset = _DENO_ASSETS.get((system, machine))
    if asset is None:
        raise RuntimeError(
            f"No known Deno release asset for {system}/{machine}; "
            "add it to _DENO_ASSETS in scripts/build_desktop_app.py."
        )

    url = (
        f"https://github.com/denoland/deno/releases/download/{DENO_VERSION}/{asset}"
    )
    stage_dir.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            print(f"Downloading Deno {DENO_VERSION} ({asset}) [attempt {attempt}/3]...")
            with urllib.request.urlopen(url, timeout=120) as response:
                payload = response.read()
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                binary_name = "deno.exe" if is_windows else "deno"
                member = next(
                    (
                        name
                        for name in archive.namelist()
                        if Path(name).name == binary_name
                    ),
                    None,
                )
                if member is None:
                    raise RuntimeError(
                        f"'{binary_name}' not found in Deno archive {asset}"
                    )
                target = stage_dir / binary_name
                with archive.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
            if not is_windows:
                target.chmod(0o755)
            print(f"Staged Deno: {url} -> {target}")
            return target
        except Exception as error:  # noqa: BLE001 - retried, then re-raised below
            last_error = error
            print(f"WARNING: Deno download failed: {error}", file=sys.stderr)
            time.sleep(2 * attempt)

    raise RuntimeError(
        f"Failed to download Deno {DENO_VERSION} for {system}/{machine} "
        f"after 3 attempts: {last_error}"
    )


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
    deno_binary = _stage_deno(build_path / "deno_stage", is_windows)

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
        "--collect-data",
        "yt_dlp",
        "--collect-all",
        "yt_dlp_ejs",
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

    command[-1:-1] = ["--add-binary", f"{deno_binary}{data_sep}deno_bin"]

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
