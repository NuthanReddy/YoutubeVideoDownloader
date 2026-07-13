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

# --- "Bypass region block" (geo-unblock) settings ---------------------------
# Some videos are geo-restricted by the uploader ("not made available in your
# country"). YouTube enforces this by the real connecting IP and ignores the
# X-Forwarded-For header, so yt-dlp's built-in --geo-bypass does NOT help; the
# only reliable workaround is to route the request through a proxy that exits in
# an allowed country. When the toggle is on and no user proxy is pinned, the app
# fetches free public proxies and retries the blocked video through them.
#
# Free public proxy list (proxyscrape v4, JSON). Fetched on demand, best effort.
FREE_PROXY_API_URL = (
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=display_proxies&proxy_format=protocolipport&format=json"
    "&protocol=http&timeout=8000"
)
# Countries commonly present in "available" lists with a healthy supply of free
# proxies. These are tried first; other allowed countries are still used as
# fallbacks. (The retry loop self-corrects if a chosen country is also blocked.)
PREFERRED_PROXY_COUNTRIES = (
    "US", "GB", "DE", "NL", "FR", "CA", "JP", "SG", "AU", "BR", "SE", "ES",
    "IT", "PL", "FI", "CH", "IE", "NO", "DK",
)
# Max proxies to actually attempt a download through before giving up.
MAX_AUTO_PROXY_ATTEMPTS = 8
# Number of ranked candidates to pull from the list before liveness-filtering.
AUTO_PROXY_CANDIDATE_POOL = 40
# Per-attempt socket timeout (seconds) when downloading through a free proxy;
# free proxies are slow/flaky, so keep it short so dead ones fail fast.
PROXY_SOCKET_TIMEOUT = 20
# Quick liveness pre-check timeout (seconds) used to weed out dead proxies
# before paying for a full yt-dlp attempt.
PROXY_LIVENESS_TIMEOUT = 6
# How long a fetched proxy list stays cached (seconds) so a queue of videos
# reuses one fetch instead of hammering the API per item.
PROXY_CACHE_TTL = 600

# --- Sign-in cookies --------------------------------------------------------
# Some videos require a signed-in session (age-restricted, members-only,
# private) or expose extra format tiers only to authenticated users. yt-dlp can
# reuse a browser's cookies to act as that signed-in user. We accept either a
# cookies.txt file (Netscape format, exported from a browser extension) or the
# name of a browser to import cookies from directly.
#
# Browsers yt-dlp can import cookies from (mirrors yt_dlp.cookies.SUPPORTED_
# BROWSERS). Kept as our own tuple so a yt-dlp refactor can't break import.
# NOTE: a browser import reads that browser's cookie database; on Windows the
# database is often locked while the browser is running (and current Chrome/Edge
# add "App-Bound Encryption"), so the cookies.txt file route is the reliable one.
SUPPORTED_COOKIE_BROWSERS = (
    "brave",
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "opera",
    "safari",
    "vivaldi",
    "whale",
)
