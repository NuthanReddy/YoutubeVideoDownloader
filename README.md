# YouTube Video Downloader

A small Python CLI for downloading YouTube videos with:

- configurable maximum resolution (for example `720`, `1080`, `1440`)
- subtitle download support
- optional automatic subtitle support
- optional subtitle embedding when `ffmpeg` is available
- package management via `uv`
- per-video output folders (`<title> [<id>]`) containing media and subtitles
- desktop GUI for format discovery, parallel downloads, and local download management
- parallel playlist downloads (CLI and GUI)
- per-video concurrent fragment downloads (`--concurrent-fragments`) for compatible streams

## Assumptions

- Python is available from the local virtual environment at `.venv\Scripts\python.exe`.
- Dependencies are managed with `uv`.
- `yt-dlp` is used as the download engine.
- `ffmpeg` is recommended if you want the best video+audio merge and embedded subtitles.

## Project layout

- `docs/project-plan.md` — phase-wise implementation plan
- `src/youtube_video_downloader/` — application package
- `tests/` — unit tests

## Setup

```powershell
Set-Location "C:\Users\ngantla\PycharmProjects\YoutubeVideoDownloader"
uv sync --dev
```

## Basic usage

Download a video at up to 1080p with English subtitles:

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --resolution 1080 --subtitle-lang en
```

Download with multiple subtitle languages:

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --resolution 720 --subtitle-lang en --subtitle-lang hi
```

Download all available subtitles as sidecar files:

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --all-subtitles --sidecar-subtitles
```

Inspect available formats before downloading:

```powershell
uv run youtube-video-downloader formats "https://www.youtube.com/watch?v=VIDEO_ID"
```

Run with the local interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m youtube_video_downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --resolution 1080
```

## Output structure

Each download is stored in its own folder under `downloads`:

- `downloads/<video title> [<video id>]/<video title> [<video id>].mp4`
- `downloads/<video title> [<video id>]/<video title> [<video id>].en.srt`

## Notes on subtitles

- `--subtitle-lang` can be repeated.
- `--all-subtitles` overrides specific language selection.
- `--auto-subtitles` enables generated subtitles when manually uploaded subtitles are unavailable.
- `--embed-subtitles` attempts to embed subtitles into the downloaded media and typically needs `ffmpeg`.

## Testing

```powershell
uv run pytest
```

## GUI usage

Launch the desktop app:

```powershell
uv run youtube-video-downloader gui
```

What the GUI supports:

- Fetch available resolutions for a URL and choose from a dropdown (`best`, `2160`, `1440`, etc.)
- Queue multiple URLs (one per line) and download in parallel with configurable workers
- Tune per-video fragment concurrency with the `Fragments` spinner
- Expand playlist URLs into all videos and download them in parallel
- Configure subtitle options (`Enable`, `All`, `Auto`, `Embed`) and subtitle languages
- Open the downloads root folder directly, open selected downloaded items, and delete downloaded video folders

## Build desktop app (Windows/macOS)

This project includes a PyInstaller build script for creating a native GUI app.

Install build dependencies:

```powershell
uv sync --group build
```

Build the app bundle for your current OS:

```powershell
uv run --group build python scripts/build_desktop_app.py
```

Artifacts:

- Windows: `dist/windows/YouTubeVideoDownloader.exe`
- macOS: `dist/macos/YouTubeVideoDownloader.app`

Notes:

- PyInstaller does not cross-compile; build on Windows for `.exe` and on macOS for `.app`.
- Install `ffmpeg` separately for best quality downloads that require stream merging.
- You can also trigger `.github/workflows/build-desktop.yml` (GitHub Actions) to produce both Windows and macOS artifacts in one run.

Download all videos from a playlist in parallel:

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/playlist?list=PLAYLIST_ID" --playlist --playlist-workers 4 --resolution 1080 --subtitle-lang en
```

Download using parallel fragments for one video (helps DASH/HLS streams):

```powershell
uv run youtube-video-downloader download "https://www.youtube.com/watch?v=VIDEO_ID" --resolution 2160 --concurrent-fragments 4
```
