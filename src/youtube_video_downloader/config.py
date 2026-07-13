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
# Extra extraction attempts before giving up (helps ride out transient 429s).
DEFAULT_EXTRACTOR_RETRIES = 3

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
