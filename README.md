# YouTube Video Downloader

A `uv`-managed Python app for downloading YouTube videos and playlists, built on
[`yt-dlp`](https://github.com/yt-dlp/yt-dlp). It ships both a **Typer command-line
interface** and a **tkinter desktop GUI** with live progress, parallel downloads,
and a local library manager.

## Features

**Core**

- Configurable maximum resolution (for example `720`, `1080`, `1440`, `2160`, or `best`)
- Subtitle download, automatic (generated) subtitles, and optional embedding (uses the bundled `ffmpeg` in the desktop apps)
- Per-video output folders (`<title> [<id>]`) containing media and subtitle files
- Parallel playlist downloads with a configurable worker count (CLI and GUI)
- Automatic **HD/4K unlock** — a JavaScript runtime (Deno) is bundled in the desktop apps so YouTube's signature challenge is solved and the full HD/4K format ladder is returned instead of a 360p cap (see [Troubleshooting](#troubleshooting))
- Built-in **rate-limit safety** — request throttling, randomized sleeps and exponential-backoff retries keep traffic under YouTube's per-IP limit to avoid `HTTP 429` failures (see [Troubleshooting](#troubleshooting))
- Resilient extraction that defers to yt-dlp's maintained **default player clients** so the full HD/4K format ladder stays available (see [Troubleshooting](#troubleshooting))
- **`ffmpeg` bundled** in the packaged desktop apps, so HD merges and subtitle embedding work with no separate install
- **Region-block bypass** — an optional toggle that, when a video is blocked in your country, automatically retries through a free proxy in an allowed country (or your own pinned proxy/VPN endpoint) — see [Region-restricted videos](#region-restricted-videos-uploader-country-blocks)

**Desktop GUI**

- Fetch available resolutions for a URL and pick from a dropdown
- Queue multiple URLs (one per line) and download them in parallel with configurable workers
- Live per-download progress (percentage, speed, ETA) with a progress bar per video
- **Pause**, **Resume All**, and **Retry** controls for the active queue
- Expand a playlist URL into all of its videos before downloading
- Resizable side-by-side **Active Downloads** and **Downloaded Videos** panes, with a collapsible **Activity** log docked at the bottom
- Browse nested playlist folders in the library, open a file/folder (single- or double-click), reveal the downloads root, and delete downloaded items
- Modern dark theme with a matching app icon and Windows taskbar integration
- **Bypass region block** toggle plus an optional **Proxy** field for routing geo-restricted downloads through an allowed country

## Requirements

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** for dependency management
- **`ffmpeg`** on your `PATH` when running from source, for merging separate video/audio streams and embedding subtitles. **The packaged desktop apps bundle `ffmpeg`**, so end users don't need to install it.
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
| `--output-dir`, `-o` | `~/Downloads` | Destination directory (defaults to your user Downloads folder) |
| `--subtitle-lang`, `-s` | `en` | Subtitle language; repeat for multiple |
| `--all-subtitles` | off | Download every available subtitle language |
| `--subtitles / --no-subtitles` | on | Toggle subtitle downloading |
| `--auto-subtitles / --no-auto-subtitles` | on | Allow generated subtitles when uploaded ones are missing |
| `--embed-subtitles / --sidecar-subtitles` | embed | Embed subtitles into media (needs `ffmpeg`) or keep sidecar files |
| `--playlist / --single` | single | Treat the URL as a playlist and download all videos |
| `--playlist-workers` | `3` | Parallel workers for playlist downloads |
| `--proxy` | none | Route downloads through a proxy, e.g. `http://host:port` or `socks5://host:port` |
| `--geo-unblock / --no-geo-unblock` | off | If a video is region-blocked, retry through free proxies in allowed countries |
| `--restrict-filenames / --allow-unicode-filenames` | unicode | Use ASCII-safe filenames |

## Output structure

Downloads go to your user **Downloads** folder by default
(`/Users/<username>/Downloads` on macOS, `C:\Users\<username>\Downloads` on
Windows), overridable with `--output-dir` or the GUI **Browse** button. Each
download is stored in its own folder under that destination:

- `<destination>/<video title> [<video id>]/<video title> [<video id>].mp4`
- `<destination>/<video title> [<video id>]/<video title> [<video id>].en.srt`

Playlist items are grouped under a folder named after the playlist.

## Notes on subtitles

- `--subtitle-lang` can be repeated for multiple languages.
- `--all-subtitles` overrides specific language selection.
- `--auto-subtitles` enables generated subtitles when manually uploaded subtitles are unavailable.
- `--embed-subtitles` embeds subtitles into the media and typically needs `ffmpeg`; otherwise sidecar `.srt` files are kept.

## Configuration

A few defaults live in `src/youtube_video_downloader/config.py`:

- `DEFAULT_PLAYER_CLIENTS` — the ordered list of yt-dlp YouTube *player clients*
  to try. It defaults to `("default", "android")`. yt-dlp queries each client,
  merges the formats they return, and only fails if **all** of them fail:
  - `default` lets yt-dlp use its maintained client set, which exposes the full
    HD/4K (DASH) ladder.
  - `android` is a fallback for networks/sessions where YouTube bot-blocks the
    web-family clients that `default` leads with (`HTTP 429` → "This video is not
    available"). The android endpoint usually stays reachable, so downloads keep
    working (capped at ~360p, since android is caught by YouTube's "SABR-only"
    experiment) instead of failing outright. Where `default` succeeds, its HD
    formats win and android's lower formats are ignored.
- **Rate-limit safety** (always on) — to stay under YouTube's per-IP limit and
  avoid `HTTP 429`, the app spaces out requests and retries transient failures
  with exponential backoff. Tunables: `SLEEP_INTERVAL_REQUESTS` (pause between
  the extraction calls that resolve each video), `MIN_SLEEP_INTERVAL` /
  `MAX_SLEEP_INTERVAL` (randomized pause before each download),
  `DOWNLOAD_RETRIES` / `FRAGMENT_RETRIES` / `DEFAULT_EXTRACTOR_RETRIES` (retry
  budgets), `RETRY_BACKOFF_BASE_SECONDS` / `RETRY_BACKOFF_MAX_SECONDS`
  (backoff curve) and `DEFAULT_SOCKET_TIMEOUT` (bounds a stalled connection).
  *(The old per-video "concurrent fragments" option was removed — parallel
  fragments multiply the request rate and are a primary 429 trigger, and the
  worker count already parallelizes across videos.)*
- **JavaScript runtime** — modern YouTube requires a JS runtime to solve its
  signature (`n`) challenge before it returns HD/DASH URLs; without one, formats
  cap at ~360p or the video looks "not available". The desktop apps **bundle
  Deno** plus the [`yt-dlp-ejs`](https://pypi.org/project/yt-dlp-ejs/) solver
  scripts, so HD works offline out of the box. When running from source, the app
  auto-detects a runtime on your `PATH` (`deno`, `node`, `bun`, or `quickjs`) —
  installing [Deno](https://deno.com/) or Node.js is enough.
- `DEFAULT_FILENAME_TEMPLATE` / `PLAYLIST_ITEM_FILENAME_TEMPLATE` — output naming.
- `DEFAULT_SUBTITLE_LANGUAGES` / `DEFAULT_SUBTITLE_FORMAT` — subtitle defaults.
- Region-block bypass tunables — `FREE_PROXY_API_URL`, `PREFERRED_PROXY_COUNTRIES`,
  `MAX_AUTO_PROXY_ATTEMPTS`, `AUTO_PROXY_CANDIDATE_POOL`, and the proxy timeouts
  control the free-proxy auto mode (see [Region-restricted videos](#region-restricted-videos-uploader-country-blocks)).

## Troubleshooting

**"This video is not available" / `HTTP Error 429: Too Many Requests`**

YouTube is rate-limiting or bot-blocking extraction. The app already throttles
requests and retries with exponential backoff to stay under the limit (see
[Rate-limit safety](#configuration)), but a shared IP or a very large batch can
still trip it. If it happens:

- Wait a few minutes for the rate limit to clear, then retry (use the GUI **Retry** button).
- Lower the worker count (GUI `Workers` spinner or `--playlist-workers`) so fewer requests hit YouTube at once.
- The app uses `("default", "android")` player clients, so if the `default`
  (web-family) clients are blocked it falls back to `android` (at up to 360p)
  rather than failing. Keep yt-dlp up to date (`uv lock --upgrade-package yt-dlp`)
  since YouTube's anti-bot behavior changes often.

**Downloads only ever reach 360p (never HD/4K)**

Modern YouTube only returns HD/DASH URLs after a JavaScript runtime solves its
signature (`n`) challenge. The desktop apps bundle **Deno** + the `yt-dlp-ejs`
solver scripts, so this is handled automatically. If you see a 360p cap:

- **Running from source without a runtime** — install [Deno](https://deno.com/)
  (or Node.js) so the app can solve the challenge; it auto-detects `deno`,
  `node`, `bun`, or `quickjs` on your `PATH`.
- **The `default` clients are blocked** in your network, so every download falls
  back to the SABR-restricted `android` client. Try a different network/VPN, wait
  for the rate limit to clear, or update yt-dlp.

**4K reverts to 360p on the packaged app**

Older releases capped at 360p for three reasons, all fixed in current builds:

- **No JavaScript runtime** — YouTube's `n`-challenge went unsolved, so HD/DASH
  URLs were never returned. The apps now bundle Deno + `yt-dlp-ejs`.
- **`ffmpeg` missing** — without it, yt-dlp can't merge separate video/audio
  streams and falls back to the best *pre-muxed* progressive stream (360p). The
  desktop apps now bundle `ffmpeg`; when running from source, install it and put
  it on your `PATH`.
- **A pinned player client hitting SABR** — the default client list now leads
  with `default` (full HD) and only falls back to `android` (360p) when blocked.

**`WARNING: No supported JavaScript runtime could be found`**

yt-dlp needs a JS runtime to solve YouTube's `n`-challenge for HD formats. The
desktop apps bundle Deno, so you should not see this. When running from source,
install [Deno](https://deno.com/) (or Node.js) and it will be picked up
automatically.

**Merged video/audio or embedded subtitles are missing**

The desktop apps bundle `ffmpeg`, so this should "just work". When running from
source, install `ffmpeg` and ensure it is on your `PATH`.

**`ModuleNotFoundError` / GUI won't import `tkinter`**

Make sure you ran `uv sync --dev` and are launching with the project's `.venv`
interpreter. `tkinter` ships with standard CPython on Windows and macOS.

### Region-restricted videos (uploader country blocks)

Some uploads are restricted to a set of countries — yt-dlp reports:

```
ERROR: [youtube] <id>: The uploader has not made this video available in your country
```

YouTube decides your region from the **IP address that connects to it**, so
yt-dlp's built-in `--geo-bypass` (an `X-Forwarded-For` header) does **not** work
for these blocks. The only reliable fix is to route the request through a proxy
or VPN that *exits* in an allowed country. This app gives you two ways to do that:

- **Bypass region block toggle** (GUI) / **`--geo-unblock`** (CLI) — leave the
  proxy field blank and, only when a download actually fails with a region-block
  error, the app fetches a list of free public proxies in allowed countries,
  liveness-checks them, and retries the download through a working one. A proxy
  that succeeds is remembered and reused for sibling playlist items. Normal
  (non-blocked) downloads are never slowed down by this.
- **Proxy field** (GUI) / **`--proxy`** (CLI) — pin your own proxy or VPN
  endpoint, e.g. `http://host:port`, `https://host:port`, or
  `socks5://host:port`. A pinned proxy is used for *every* request, so it's the
  reliable path.

> **Note:** Free public proxies are slow, flaky, and short-lived, so auto mode is
> best-effort — it may take several tries or fail entirely. For dependable
> geo-unblocking, connect a VPN or paste a proxy you trust into the Proxy field.

**`[WinError 448] ... untrusted mount point` when a download starts**

This only happens when the app is launched from inside a sandboxed runtime that
puts an *untrusted* junction/reparse point on `PATH` (for example a
`...\agency\CurrentVersion` directory) while Windows' *RedirectionTrust*
mitigation is enforced. To locate its JS runtime (Deno), yt-dlp runs
`os.path.realpath` over every `PATH` entry — and `realpath` (unlike
`os.path.exists`) does **not** swallow the resulting `OSError`, so the traversal
of that one untrusted entry raised `[WinError 448]` and aborted every extraction.
The app now scrubs any un-traversable entries from `PATH` at startup (and steps
out of an un-traversable working directory), so this no longer occurs — update to
the latest build. A normal double-click / installer launch was never affected.

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
- `ffmpeg` is bundled automatically (via `imageio-ffmpeg` in the `build` dependency group), so the packaged app needs no separate `ffmpeg` install.
- **Deno** (the JavaScript runtime that unlocks HD/4K) is downloaded per-architecture and bundled during the build, together with the `yt-dlp-ejs` solver scripts — the packaged app solves YouTube's signature challenge offline, no runtime install needed. The build script fetches Deno from GitHub, so it needs network access.
- You can also trigger `.github/workflows/build-desktop.yml` (GitHub Actions) to produce all
  release artifacts in one run: a **Windows** installer (`YouTubeVideoDownloader-Setup.exe`, built
  with Inno Setup from `installer/windows_installer.iss`), a **Windows** portable zip, a
  **macOS Intel** (x86_64) zip, and a **macOS Apple Silicon** (arm64) zip. Both macOS builds run on
  Apple Silicon runners — the Intel one is produced as a native x86_64 app via Rosetta 2, so it runs
  natively on Intel Macs. Pushing a `vX.Y.Z` tag also publishes a GitHub Release with those assets
  attached.

### Download a prebuilt release

Grab the asset for your platform from the
[Releases page](https://github.com/NuthanReddy/YoutubeVideoDownloader/releases):

**Windows**

- **`YouTubeVideoDownloader-Setup.exe` — recommended.** A one-click installer
  (per-user, no admin prompt). It installs the app into a real folder, adds
  **Start Menu** and optional **Desktop** shortcuts, and provides a clean
  uninstaller. Launch it from the shortcut afterwards.
- `YouTubeVideoDownloader-windows.zip` — portable alternative. **Extract the
  whole zip to a folder first** (right-click → *Extract All…*), then run
  `YouTubeVideoDownloader.exe` from the extracted folder — keep it next to the
  `_internal` folder. Do **not** run the exe from inside the zip preview:
  Windows unpacks a partial copy to `%TEMP%` and the app fails with
  *"Failed to load Python DLL … python312.dll"*.

**macOS**

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
