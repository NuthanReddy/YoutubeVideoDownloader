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

# yt-dlp YouTube "player clients" to try, in order. YouTube heavily rate-limits
# and bot-blocks the default ``web`` client (HTTP 429 -> "This video is not
# available"), which makes every download fail. The ``android`` client talks to
# a different API endpoint that is not blocked and also sidesteps the new
# JavaScript-runtime requirement, so we prefer it and keep ``web`` as a fallback.
DEFAULT_PLAYER_CLIENTS = ("android", "web")
# Extra extraction attempts before giving up (helps ride out transient 429s).
DEFAULT_EXTRACTOR_RETRIES = 3
