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

# yt-dlp YouTube "player clients" to try. Historically we pinned the ``android``
# client because YouTube bot-blocked the ``web`` client (HTTP 429). YouTube has
# since rolled out a "SABR-only" streaming experiment that strips the HD/DASH
# formats from the ``android`` client for many videos/sessions, which silently
# capped downloads at 360p. yt-dlp's maintained ``default`` client set now
# negotiates the working endpoints and restores the full 2160p/1440p/1080p
# ladder, so we defer to it rather than pinning a single client.
DEFAULT_PLAYER_CLIENTS = ("default",)
# Extra extraction attempts before giving up (helps ride out transient 429s).
DEFAULT_EXTRACTOR_RETRIES = 3
