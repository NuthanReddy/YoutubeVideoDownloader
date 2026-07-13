"""Application defaults and constants."""

from pathlib import Path

# Default download location: the current user's Downloads folder. This resolves
# to /Users/<username>/Downloads on macOS, C:\Users\<username>\Downloads on
# Windows, and /home/<username>/Downloads on Linux. Using an absolute,
# home-relative path (instead of a relative "downloads" folder) matters for the
# packaged desktop app: launched from Finder/Explorer its working directory is
# unpredictable (often "/", which isn't writable), so a relative default could
# fail or scatter files. Users can still override this in the GUI/CLI.
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads"
# Group each download under its own folder: <title> [<id>]/<title> [<id>].<ext>
DEFAULT_FILENAME_TEMPLATE = "%(title)s [%(id)s]/%(title)s [%(id)s].%(ext)s"
# Playlist items live directly inside the playlist folder (no per-video subfolder).
PLAYLIST_ITEM_FILENAME_TEMPLATE = "%(title)s [%(id)s].%(ext)s"
DEFAULT_SUBTITLE_LANGUAGES = ("en",)
DEFAULT_SUBTITLE_FORMAT = "srt/best"
APP_NAME = "youtube-video-downloader"

# yt-dlp YouTube "player clients" to try, in order. This list is deliberately
# resilient: yt-dlp queries each client, aggregates the formats they return, and
# only fails if *every* client fails.
#
# - ``default`` lets yt-dlp use its maintained client set, which exposes the full
#   HD/4K (DASH) ladder. This is what restores 1080p/1440p/2160p downloads.
# - ``android`` is kept as a fallback. In some networks/sessions YouTube
#   bot-blocks the web-family clients that ``default`` leads with (HTTP 429 ->
#   "This video is not available"), which would make every download fail. The
#   android endpoint uses a different API that is usually still reachable, so it
#   keeps downloads working (at up to 360p, since android is SABR-restricted)
#   instead of erroring out entirely. Where ``default`` succeeds, its HD formats
#   win the format selection and android's lower formats are simply ignored.
DEFAULT_PLAYER_CLIENTS = ("default", "android")
# --- Rate-limit safety (avoid HTTP 429 "Too Many Requests") -----------------
# YouTube rate-limits by IP; bursts of parallel requests (playlists, many
# parallel fragments) trip a 429 that yt-dlp surfaces as "video not available".
# There is no published quota -- it is an adaptive per-IP heuristic on request
# *rate and pattern* -- so the only reliable fix is to stay UNDER it: throttle
# the requests, pause between downloads, cap connection time, and retry with
# exponential backoff instead of hammering. These defaults are always on; for a
# single video the sleeps are negligible, but across a playlist they keep
# downloads reliable. (This is also why the app no longer exposes a "concurrent
# fragments" knob -- parallel fragments multiply the request rate and are a
# primary 429 trigger; downloads now fetch fragments sequentially.)
#
# Seconds to sleep between HTTP requests during metadata extraction. This is the
# single most effective knob against playlist 429s: it spaces out the API calls
# yt-dlp makes while resolving each video.
SLEEP_INTERVAL_REQUESTS = 0.75
# Randomized pause before each video download, drawn from
# [MIN_SLEEP_INTERVAL, MAX_SLEEP_INTERVAL] seconds, so a queue of videos is not
# fetched back-to-back in a detectable burst.
MIN_SLEEP_INTERVAL = 1.0
MAX_SLEEP_INTERVAL = 5.0
# Download and fragment retry budgets. Combined with the exponential backoff
# below, a transient 429/5xx is ridden out rather than failing the download.
DOWNLOAD_RETRIES = 10
FRAGMENT_RETRIES = 10
# Extra extraction attempts before giving up (helps ride out transient 429s
# during metadata resolution).
DEFAULT_EXTRACTOR_RETRIES = 5
# Exponential backoff for retried requests: on attempt n (1-based) the wait is
# min(RETRY_BACKOFF_BASE_SECONDS * 2**(n-1), RETRY_BACKOFF_MAX_SECONDS) seconds.
# Applied to http, fragment and extractor retries so repeated 429s wait
# progressively longer (2s, 4s, 8s, ... capped) instead of retrying instantly.
RETRY_BACKOFF_BASE_SECONDS = 2.0
RETRY_BACKOFF_MAX_SECONDS = 120.0
# Per-request socket timeout (seconds). Bounds a stalled/blocked connection so it
# fails and is retried (with backoff) instead of hanging a worker indefinitely.
DEFAULT_SOCKET_TIMEOUT = 30
