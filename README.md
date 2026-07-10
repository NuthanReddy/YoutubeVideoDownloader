# YouTube Video Downloader

A `uv`-managed Python app for downloading YouTube videos and playlists, built on
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp). It ships both a **Typer command-line
interface** and a **tkinter desktop GUI** with live progress, parallel downloads,
and a local library manager.

## Features

**Core**

- Configurable maximum resolution (for example `720`, `1080`, `1440`, `2160`, or `best`)
- Subtitle download, automatic (generated) subtitles, and optional embedding when `ffmpeg` is available
- Per-video output folders (`<title> [<id>]`) containing media and subtitle files
- Parallel playlist downloads with a configurable worker count (CLI and GUI)
- Per-video concurrent fragment downloads for DASH/HLS streams
- Resilient extraction that uses YouTube's **Android player client** by default to avoid `HTTP 429` blocks (see [Troubleshooting](#troubleshooting))

**Desktop GUI**

- Fetch available resolutions for a URL and pick from a dropdown
- Queue multiple URLs (one per line) and download them in parallel with configurable workers
- Live per-download progress (percentage, speed, ETA) with a progress bar per video
- **Pause**, **Resume All**, and **Retry** controls for the active queue
- Expand a playlist URL into all of its videos before downloading
- Resizable side-by-side **Active Downloads** and **Downloaded Videos** panes, with a collapsible **Activity** log docked at the bottom
- Browse nested playlist folders in the library, open a file/folder (single- or double-click), reveal the downloads root, and delete downloaded items
- Modern dark theme with a matching app icon and Windows taskbar integration

## Requirements

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** for dependency management
- **`ffmpeg`** (recommended) for merging separate video/audio streams and embedding subtitles
- A network connection (the download engine is `yt-dlp`)

## Setup

```powershell
Set-Location "C:\Users\ngantla\PycharmProjects\YoutubeVideoDownloader"
uv sync --dev
```

This creates a local virtual environment at `.venv\` and installs the project
with its `youtube-video-downloader` and `youtube-video-downloader-gui` entry points.

## Quick start — launch the GUI

Any of the following launch the desktop app. The first two are the simplest:

```powershell
# 1. Dedicated GUI entry point
uv run youtube-video-downloader-gui

# 2. GUI subcommand of the CLI (accepts --output-dir)
uv run youtube-video-downloader gui --output-dir "downloads"
```

For daily use on Windows, launch **without a console window** using `pythonw`:

```powershell
# No console window (recommended for daily use)
.\.venv\Scripts\pythonw.exe -m youtube_video_downloader.gui_main
```

To see console output while debugging, use `python` instead of `pythonw`:

```powershell
.\.venv\Scripts\python.exe -m youtube_video_downloader.gui_main
```

Prefer a native, double-click app? Build one with PyInstaller — see
[Build a desktop app](#build-a-desktop-app).

## Command-line usage

Download a single video at up to 1080p with English subtitles:

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --resolution 1080 --subtitle-lang en
```

Download with multiple subtitle languages (repeat `--subtitle-lang`):

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --resolution 720 --subtitle-lang en --subtitle-lang hi
```

Download all available subtitles as sidecar files (no embedding):

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --all-subtitles --sidecar-subtitles
```

Download every video in a playlist in parallel:

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/playlist?list=PLAYLIST_ID" --playlist --playlist-workers 4 --resolution 1080 --subtitle-lang en
```

Use parallel fragments to speed up a single DASH/HLS video:

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --resolution 2160 --concurrent-fragments 4
```

Inspect available formats before downloading:

```powershell
uv run youtube-video-downloader formats "https://www.youtube.com/watch?v=VIDEO_ID"
```

Run with the local interpreter directly (equivalent to `uv run`):

```powershell
.\.venv\Scripts\python.exe -m youtube_video_downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --resolution 1080
```

### Key options (`download`)

| Option | Default | Description |
| --- | --- | --- |
| `--resolution`, `-r` | `best` | Max height (`720`, `1080`, `1080p`, …) or `best` for no cap |
| `--output-dir`, `-o` | `downloads` | Destination directory |
| `--subtitle-lang`, `-s` | `en` | Subtitle language; repeat for multiple |
| `--all-subtitles` | off | Download every available subtitle language |
| `--subtitles / --no-subtitles` | on | Toggle subtitle downloading |
| `--auto-subtitles / --no-auto-subtitles` | on | Allow generated subtitles when uploaded ones are missing |
| `--embed-subtitles / --sidecar-subtitles` | embed | Embed subtitles into media (needs `ffmpeg`) or keep sidecar files |
| `--playlist / --single` | single | Treat the URL as a playlist and download all videos |
| `--playlist-workers` | `3` | Parallel workers for playlist downloads |
| `--concurrent-fragments` | `1` | Concurrent fragment downloads per video |
| `--restrict-filenames / --allow-unicode-filenames` | unicode | Use ASCII-safe filenames |

## Output structure

Each download is stored in its own folder under `downloads`:

- `downloads/<video title> [<video id>]/<video title> [<video id>].mp4`
- `downloads/<video title> [<video id>]/<video title> [<video id>].en.srt`

Playlist items are grouped under a folder named after the playlist.

## Notes on subtitles

- `--subtitle-lang` can be repeated for multiple languages.
- `--all-subtitles` overrides specific language selection.
- `--auto-subtitles` enables generated subtitles when manually uploaded subtitles are unavailable.
- `--embed-subtitles` embeds subtitles into the media and typically needs `ffmpeg`; otherwise sidecar `.srt` files are kept.

## Configuration

A few defaults live in `src/youtube_video_downloader/config.py`:

- `DEFAULT_PLAYER_CLIENTS` — the ordered list of yt-dlp YouTube *player clients*
  to try. It defaults to `("android", "web")` because YouTube rate-limits and
  bot-blocks the default `web` client (`HTTP 429`), which otherwise makes every
  download fail. The Android endpoint is not blocked and also avoids the new
  JavaScript-runtime requirement.
- `DEFAULT_EXTRACTOR_RETRIES` — extra extraction attempts to ride out transient errors.
- `DEFAULT_FILENAME_TEMPLATE` / `PLAYLIST_ITEM_FILENAME_TEMPLATE` — output naming.
- `DEFAULT_SUBTITLE_LANGUAGES` / `DEFAULT_SUBTITLE_FORMAT` — subtitle defaults.

## Troubleshooting

**"This video is not available" / `HTTP Error 429: Too Many Requests`**

YouTube is rate-limiting or bot-blocking the default `web` client. The app already
defaults to the Android player client to avoid this. If it still happens:

- Wait a few minutes for the rate limit to clear, then retry (use the GUI **Retry** button).
- Lower the worker count (GUI `Workers` spinner or `--playlist-workers`) so fewer requests hit YouTube at once.
- Confirm `DEFAULT_PLAYER_CLIENTS` in `config.py` still lists `android` first.

**Only low resolutions are offered for some videos**

YouTube occasionally runs a "SABR-only" streaming experiment that hides higher
formats from the Android client. This is a temporary server-side change; retrying
later, or once impersonation support is installed, usually restores more formats.

**`WARNING: No supported JavaScript runtime could be found`**

The `web` client increasingly needs a JS runtime (Deno). Using the Android client
(the default here) sidesteps this, so the warning is harmless. Installing
[Deno](https://deno.com/) removes it entirely.

**Merged video/audio or embedded subtitles are missing**

Install `ffmpeg` and ensure it is on your `PATH`.

**`ModuleNotFoundError` / GUI won't import `tkinter`**

Make sure you ran `uv sync --dev` and are launching with the project's `.venv`
interpreter. `tkinter` ships with standard CPython on Windows and macOS.

## Testing

```powershell
uv run pytest
```

## Build a desktop app

This project includes a PyInstaller build script for creating a native GUI app.

Install build dependencies:

```powershell
uv sync --group build
```

Build the app bundle for your current OS:

```powershell
uv run --group build python scripts/build_desktop_app.py
```

Artifacts (built with PyInstaller `--onedir` for reliable DLL loading):

- Windows: `dist/windows/YouTubeVideoDownloader/` (run `YouTubeVideoDownloader.exe` inside it)
- macOS: `dist/macos/YouTubeVideoDownloader.app`

Notes:

- PyInstaller does not cross-compile; build on Windows for the `.exe` folder and on macOS for the `.app`.
- Install `ffmpeg` separately for best-quality downloads that require stream merging.
- You can also trigger `.github/workflows/build-desktop.yml` (GitHub Actions) to produce all
  release artifacts in one run: a **Windows** zip, a **macOS Intel** (x86_64) zip, and a
  **macOS Apple Silicon** (arm64) zip. Both macOS builds run on Apple Silicon runners — the Intel
  one is produced as a native x86_64 app via Rosetta 2, so it runs natively on Intel Macs. Pushing a
  `vX.Y.Z` tag also publishes a GitHub Release with those three assets attached.

### Download a prebuilt release

Grab the archive for your platform from the
[Releases page](https://github.com/NuthanReddy/YoutubeVideoDownloader/releases):

- `YouTubeVideoDownloader-windows.zip` — extract and run `YouTubeVideoDownloader.exe`.
- `YouTubeVideoDownloader-macos-intel.zip` — Intel Macs.
- `YouTubeVideoDownloader-macos-apple-silicon.zip` — Apple Silicon (M1/M2/M3) Macs.

The macOS apps are unsigned, so Gatekeeper will block the first launch. Either right-click the app and
choose **Open**, or clear the quarantine flag:

```bash
xattr -dr com.apple.quarantine /path/to/YouTubeVideoDownloader.app
```

## Regenerate the app icon

The icon assets (`assets/app_icon.ico`, `assets/app_icon.png`, and `assets/app_icon.icns`) are
generated by a dependency-free script:

```powershell
.\.venv\Scripts\python.exe scripts/generate_app_icon.py
```

## Project layout

- `src/youtube_video_downloader/` — application package (CLI, GUI, services, config)
- `scripts/` — desktop build and icon generation helpers
- `assets/` — app icon files
- `tests/` — unit tests
- `docs/project-plan.md` — phase-wise implementation plan
