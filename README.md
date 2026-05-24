# YouTube Video Downloader

A small Python CLI for downloading YouTube videos with:

- configurable maximum resolution (for example `720`, `1080`, `1440`)
- subtitle download support
- optional automatic subtitle support
- optional subtitle embedding when `ffmpeg` is available
- package management via `uv`
- per-video output folders (`<title> [<id>]`) containing media and subtitles

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
