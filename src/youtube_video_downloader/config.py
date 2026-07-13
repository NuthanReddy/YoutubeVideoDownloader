"""Application defaults and constants."""

from pathlib import Path

DEFAULT_OUTPUT_DIR = Path("downloads")
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
