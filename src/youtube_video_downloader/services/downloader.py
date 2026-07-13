"""Integration layer around yt-dlp."""

from __future__ import annotations

import functools
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import yt_dlp

try:  # yt-dlp raises this to abort an in-flight download (used for pause/stop).
    from yt_dlp.utils import DownloadCancelled
except Exception:  # pragma: no cover - very old yt-dlp
    class DownloadCancelled(Exception):
        """Fallback when yt-dlp does not expose DownloadCancelled."""

from ..config import (
    DEFAULT_EXTRACTOR_RETRIES,
    DEFAULT_PLAYER_CLIENTS,
    DEFAULT_SOCKET_TIMEOUT,
    DOWNLOAD_RETRIES,
    FRAGMENT_RETRIES,
    MAX_SLEEP_INTERVAL,
    MIN_SLEEP_INTERVAL,
    RETRY_BACKOFF_BASE_SECONDS,
    RETRY_BACKOFF_MAX_SECONDS,
    SLEEP_INTERVAL_REQUESTS,
)
from ..models import DownloadRequest, DownloadResult, FormatInfo

# --- Disable yt-dlp's optional plugin discovery -----------------------------
# The first time a YoutubeDL is constructed, yt-dlp scans sys.path, the current
# working directory and the executable directory for an optional
# ``yt_dlp_plugins`` namespace package. This app neither ships nor supports
# plugins, so we turn the scan off for a self-contained, predictable runtime --
# it avoids touching arbitrary filesystem locations during startup and is a
# small robustness / security win. (Note: this is *not* the fix for the
# ``[WinError 448] untrusted mount point`` crash -- that comes from the JS-runtime
# PATH lookup handled by ``_harden_runtime_paths`` below -- but keeping plugin
# discovery off removes one more filesystem scan from the hot path.)
# ``YTDLP_NO_PLUGINS`` is honoured at the very top of yt-dlp's ``load_plugins``
# and short-circuits every scan; setting it here (before any YoutubeDL is built)
# is sufficient. We also clear the plugin dirs directly as a version-proof backup
# so plugins stay disabled even if the environment variable is somehow cleared.
os.environ.setdefault("YTDLP_NO_PLUGINS", "1")
try:  # pragma: no cover - internal yt-dlp API, guarded against version drift
    from yt_dlp.globals import plugin_dirs as _ytdlp_plugin_dirs

    _ytdlp_plugin_dirs.value = []
except Exception:  # pragma: no cover - older/newer yt-dlp without this global
    pass


# --- Harden runtime path lookup against untrusted junctions -----------------
# yt-dlp locates its JS runtime (Deno, needed for YouTube's ``n``-signature on
# every extraction) via ``utils/_jsruntime._find_exe``, which maps
# ``os.path.realpath`` over the current working directory and *every* ``PATH``
# entry. Unlike ``os.path.exists``, ``os.path.realpath`` does not swallow
# ``OSError`` -- so if any of those locations is an *untrusted* junction / reparse
# point (e.g. the ``...\\agency\\CurrentVersion`` directory some sandboxes place
# on ``PATH``) and the process runs under Windows' *RedirectionTrust* mitigation,
# the realpath raises ``OSError: [WinError 448] ... untrusted mount point`` and
# the exception propagates out of extraction, aborting the download before it
# starts. We cannot traverse those entries anyway, so drop the ones that fault
# from ``PATH`` (and step out of an untraversable cwd). This is a no-op on normal
# launches where every location resolves cleanly.
def _harden_runtime_paths() -> None:
    if os.name != "nt":
        return

    raw = os.environ.get("PATH")
    if raw:
        separator = os.pathsep
        kept: list[str] = []
        dropped = False
        for entry in raw.split(separator):
            if not entry:
                continue
            try:
                os.path.realpath(entry)
            except OSError:
                dropped = True
                continue
            kept.append(entry)
        if dropped:
            os.environ["PATH"] = separator.join(kept)

    # If the working directory itself sits behind an untrusted junction, the same
    # realpath fault occurs; relocate to a directory we can traverse.
    try:
        cwd = os.getcwd()
        os.path.realpath(cwd)
    except OSError:
        for candidate in (os.environ.get("USERPROFILE"), tempfile.gettempdir()):
            if candidate and os.path.isdir(candidate):
                try:
                    os.chdir(candidate)
                except OSError:
                    continue
                break


_harden_runtime_paths()


class DownloadError(RuntimeError):
    """Raised when yt-dlp cannot complete the request."""


def _ffmpeg_location() -> str | None:
    """Locate an ffmpeg binary for yt-dlp's merge/embed post-processing.

    yt-dlp needs ffmpeg to merge the separate best-quality video and audio
    streams YouTube serves (and to embed subtitles). We deliberately do **not**
    rely on the system ``PATH``: desktop apps launched from Finder/Explorer do
    not inherit the shell ``PATH``, so a user-installed ffmpeg is invisible and
    yt-dlp silently falls back to a low-resolution pre-muxed stream (e.g. 360p).

    Resolution order:

    1. A binary bundled beside the frozen app (``sys._MEIPASS/ffmpeg_bin``).
    2. The arch-matched binary shipped by ``imageio-ffmpeg`` when it is
       importable (covers source/dev runs and the build environment).

    Returns ``None`` when neither is available, letting yt-dlp fall back to its
    default ``PATH`` lookup.
    """

    base = getattr(sys, "_MEIPASS", None)
    if base:
        binary = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        candidate = Path(base) / "ffmpeg_bin" / binary
        if candidate.exists():
            return str(candidate.parent)

    try:
        import imageio_ffmpeg  # noqa: PLC0415 - optional, only present with build deps

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:  # pragma: no cover - depends on optional dependency
        pass

    return None


# --- JavaScript runtime for YouTube's ``n`` challenge -----------------------
# Modern YouTube requires solving a JavaScript ``n``-signature challenge to hand
# out the HD/DASH format URLs. yt-dlp needs a JS runtime for this, but only
# *enables* Deno by default -- and end users rarely have Deno (or any runtime)
# enabled, so extractions silently cap at 360p or fail with "video not
# available". We ship the ``yt-dlp-ejs`` solver scripts (a dependency) and
# resolve a runtime ourselves, enabling it explicitly via the ``js_runtimes``
# option so the full ladder (up to 1080p+) works out of the box.

# Preference order. Deno first: it is yt-dlp's default-trusted, *sandboxed*
# runtime and the one we bundle with the packaged app. node/bun/quickjs are
# supported but run JS unsandboxed, so they are only used when already present on
# a developer's PATH (source/dev runs). Each entry maps the yt-dlp provider name
# to the executable name(s) to probe on PATH.
_JS_RUNTIME_EXECUTABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("deno", ("deno",)),
    ("node", ("node", "nodejs")),
    ("bun", ("bun",)),
    ("quickjs", ("qjs", "quickjs")),
)


def _deno_location() -> str | None:
    """Return the path to a Deno binary bundled beside the frozen app, or None.

    Mirrors :func:`_ffmpeg_location`: a Deno binary shipped in
    ``sys._MEIPASS/deno_bin`` lets packaged-app users get the JS runtime
    YouTube's challenge needs without installing anything. Deno is used because
    it is sandboxed and, with the bundled ``yt-dlp-ejs`` scripts, runs fully
    offline.
    """

    base = getattr(sys, "_MEIPASS", None)
    if base:
        binary = "deno.exe" if os.name == "nt" else "deno"
        candidate = Path(base) / "deno_bin" / binary
        if candidate.exists():
            return str(candidate)
    return None


@functools.lru_cache(maxsize=1)
def _resolve_js_runtimes() -> dict[str, dict[str, Any]]:
    """Pick a JS runtime for yt-dlp to solve YouTube's ``n`` challenge.

    Resolution order:

    1. A Deno binary bundled with the frozen app -> ``{"deno": {"path": ...}}``.
    2. Otherwise the first supported runtime found on ``PATH``
       (deno/node/bun/quickjs) -> ``{"<name>": {}}`` (covers source/dev runs).
    3. Nothing available -> ``{}`` (leave yt-dlp's default untouched).

    Cached: neither the frozen bundle nor ``PATH`` changes during a run, and the
    lookup runs on every extraction.
    """

    bundled = _deno_location()
    if bundled:
        return {"deno": {"path": bundled}}

    for name, executables in _JS_RUNTIME_EXECUTABLES:
        if any(shutil.which(exe) for exe in executables):
            return {name: {}}

    return {}


def _js_runtime_options() -> dict[str, Any]:
    """yt-dlp ``js_runtimes`` option enabling a resolved runtime (or empty)."""

    runtimes = _resolve_js_runtimes()
    return {"js_runtimes": runtimes} if runtimes else {}


def _retry_sleep(attempts: int) -> float:
    """Exponential backoff (seconds) for retry ``attempts`` (1-based).

    ``min(base * 2**(n-1), max)`` -> 2s, 4s, 8s, ... capped, so repeated 429s
    wait progressively longer instead of retrying instantly.
    """

    delay = RETRY_BACKOFF_BASE_SECONDS * (2 ** (max(int(attempts), 1) - 1))
    return min(delay, RETRY_BACKOFF_MAX_SECONDS)


def _rate_limit_options() -> dict[str, Any]:
    """yt-dlp options that keep request rate under YouTube's per-IP 429 limit.

    YouTube throttles by IP and returns HTTP 429 ("Too Many Requests") for
    bursty traffic, which yt-dlp then surfaces as "video not available". We
    cannot raise the limit, so we stay under it: sleep briefly between the
    extraction requests that resolve each video, pause a randomized interval
    before each download, cap connection time, and retry transient failures with
    exponential backoff. Always applied; negligible for a single video but it
    prevents 429s across a playlist.
    """

    return {
        "sleep_interval_requests": SLEEP_INTERVAL_REQUESTS,
        "sleep_interval": MIN_SLEEP_INTERVAL,
        "max_sleep_interval": MAX_SLEEP_INTERVAL,
        "retries": DOWNLOAD_RETRIES,
        "fragment_retries": FRAGMENT_RETRIES,
        "extractor_retries": DEFAULT_EXTRACTOR_RETRIES,
        "socket_timeout": DEFAULT_SOCKET_TIMEOUT,
        "retry_sleep_functions": {
            "http": _retry_sleep,
            "fragment": _retry_sleep,
            "extractor": _retry_sleep,
        },
    }


def humanize_youtube_error(message: str) -> str:
    """Append a short, actionable hint to common opaque YouTube errors."""

    lowered = message.lower()
    hint: str | None = None
    if "drm" in lowered:
        hint = (
            "This video's high-resolution streams are DRM-protected and cannot "
            "be downloaded by any tool; only non-DRM copies (often up to 360p) "
            "are available."
        )
    elif any(
        signal in lowered
        for signal in (
            "sign in",
            "log in",
            "not a bot",
            "confirm your age",
            "age-restricted",
            "private video",
            "members-only",
            "join this channel",
        )
    ):
        hint = (
            "YouTube requires a signed-in session for this video "
            "(age-restricted, private, or members-only), so it can't be "
            "downloaded anonymously."
        )
    elif "requested format is not available" in lowered:
        hint = (
            "YouTube returned no downloadable formats right now (its SABR "
            "streaming experiment). Try again in a moment."
        )
    if hint:
        return f"{message}\n\nHint: {hint}"
    return message


def _youtube_extractor_options() -> dict[str, Any]:
    """Shared yt-dlp options for every ``extract_info`` call.

    Bundles the three concerns that keep metadata listing, playlist expansion
    and downloads consistent: resilient player clients (``DEFAULT_PLAYER_CLIENTS``
    -- ``default`` gives the full HD ladder, ``android`` is a bot-block
    fallback), rate-limit safety (:func:`_rate_limit_options`) and a JavaScript
    runtime (:func:`_js_runtime_options`) to solve YouTube's ``n`` challenge so
    HD/DASH formats are exposed instead of capping at 360p.
    """

    return {
        "extractor_args": {
            "youtube": {"player_client": list(DEFAULT_PLAYER_CLIENTS)}
        },
        **_rate_limit_options(),
        **_js_runtime_options(),
    }


class DownloadService:
    def __init__(self, ydl_factory: Callable[..., Any] | None = None) -> None:
        self._ydl_factory = ydl_factory or yt_dlp.YoutubeDL

    def build_options(self, request: DownloadRequest) -> dict[str, Any]:
        options: dict[str, Any] = {
            "format": self._build_format_selector(request.resolution),
            "outtmpl": request.output_template,
            "paths": {"home": str(request.output_dir)},
            "noplaylist": True,
            "restrictfilenames": request.restrict_filenames,
            "merge_output_format": "mp4",
            **_youtube_extractor_options(),
        }

        if request.download_subtitles:
            options.update(
                {
                    "writesubtitles": True,
                    "writeautomaticsub": request.auto_subtitles,
                    "subtitleslangs": list(request.subtitle_languages),
                    "subtitlesformat": request.subtitle_format,
                }
            )

        postprocessors = self._build_postprocessors(request)
        if postprocessors:
            options["postprocessors"] = postprocessors

        ffmpeg_location = _ffmpeg_location()
        if ffmpeg_location:
            options["ffmpeg_location"] = ffmpeg_location

        return options

    def download(
        self,
        request: DownloadRequest,
        *,
        progress_hook: Callable[[dict[str, Any]], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> DownloadResult:
        """Download ``request`` and return its :class:`DownloadResult`.

        ``status_callback``/``is_cancelled`` are accepted for caller
        compatibility; cancellation is driven through ``progress_hook`` (which
        raises :class:`DownloadCancelled`).
        """

        request.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            return self._download_once(request, progress_hook=progress_hook)
        except DownloadCancelled:
            raise
        except DownloadError as exc:
            raise DownloadError(humanize_youtube_error(str(exc))) from exc

    def _download_once(
        self,
        request: DownloadRequest,
        *,
        progress_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> DownloadResult:
        options = self.build_options(request)
        if progress_hook is not None:
            options["progress_hooks"] = [progress_hook]

        try:
            with self._ydl_factory(options) as ydl:
                info = ydl.extract_info(request.url, download=True)
                if info is None:
                    raise DownloadError("No video metadata was returned by yt-dlp.")

                prepared_filename = self._safe_prepare_filename(ydl, info, request)
                output_path = self._resolve_output_path(prepared_filename)

                return DownloadResult(
                    video_id=info.get("id"),
                    title=info.get("title"),
                    output_path=output_path,
                    requested_resolution=request.resolution,
                    subtitle_languages=request.subtitle_languages,
                )
        except DownloadError:
            raise
        except DownloadCancelled:
            raise
        except Exception as exc:  # pragma: no cover - library/network dependent
            raise DownloadError(str(exc)) from exc

    def list_formats(self, url: str) -> list[FormatInfo]:
        options = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            **_youtube_extractor_options(),
        }

        try:
            with self._ydl_factory(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # pragma: no cover - library/network dependent
            raise DownloadError(humanize_youtube_error(str(exc))) from exc

        formats = info.get("formats") or []
        entries = [self._to_format_info(item) for item in formats]
        return sorted(entries, key=lambda item: (item.height or 0, item.format_id), reverse=True)

    def list_playlist_video_urls(self, url: str) -> list[str]:
        """Return individual video URLs when the input is a playlist URL."""

        return self.expand_playlist(url)[1]

    def expand_playlist(self, url: str) -> tuple[str | None, list[str]]:
        """Return ``(playlist_title, video_urls)`` for a URL.

        ``playlist_title`` is the playlist's name when ``url`` resolves to a
        multi-video playlist, otherwise ``None`` (single video). A
        ``watch?v=...&list=...`` URL is normalized to its playlist form first so
        the whole playlist is enumerated rather than just the single video.
        """

        target = self._playlist_url_from(url)
        options = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": True,
            "noplaylist": False,
            **_youtube_extractor_options(),
        }

        try:
            with self._ydl_factory(options) as ydl:
                info = ydl.extract_info(target, download=False)
        except Exception as exc:  # pragma: no cover - library/network dependent
            raise DownloadError(str(exc)) from exc

        if not info:
            raise DownloadError("No playlist metadata was returned by yt-dlp.")

        entries = info.get("entries") or []
        if not entries:
            return None, [url]

        urls: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue

            webpage_url = entry.get("webpage_url")
            if isinstance(webpage_url, str) and webpage_url:
                urls.append(webpage_url)
                continue

            entry_url = entry.get("url")
            if isinstance(entry_url, str) and entry_url:
                if entry_url.startswith("http://") or entry_url.startswith("https://"):
                    urls.append(entry_url)
                else:
                    urls.append(f"https://www.youtube.com/watch?v={entry_url}")
                continue

            video_id = entry.get("id")
            if isinstance(video_id, str) and video_id:
                urls.append(f"https://www.youtube.com/watch?v={video_id}")

        unique_urls = list(dict.fromkeys(urls))
        if not unique_urls:
            return None, [url]

        playlist_title = info.get("title") if len(unique_urls) > 1 else None
        if isinstance(playlist_title, str):
            playlist_title = playlist_title.strip() or None
        else:
            playlist_title = None
        return playlist_title, unique_urls

    @staticmethod
    def _playlist_url_from(url: str) -> str:
        """Normalize a ``watch?v=...&list=...`` URL to its canonical playlist URL.

        YouTube "watch" links that also carry a ``list=`` query parameter resolve
        to a single video during flat extraction, so the playlist is never
        expanded. Rewriting them to ``playlist?list=<id>`` lets yt-dlp enumerate
        every entry. Auto-generated mixes/radios (``RD*`` ids) and URLs that are
        already playlist URLs are returned unchanged.
        """

        try:
            parsed = urlparse(url)
        except ValueError:
            return url

        netloc = (parsed.netloc or "").lower()
        if "youtube" not in netloc and "youtu.be" not in netloc:
            return url

        if parsed.path.rstrip("/").endswith("/playlist"):
            return url

        list_values = parse_qs(parsed.query).get("list")
        if not list_values:
            return url

        list_id = list_values[0].strip()
        if not list_id or list_id.upper().startswith("RD"):
            return url

        return f"https://www.youtube.com/playlist?list={list_id}"

    @staticmethod
    def _build_format_selector(resolution: int | None) -> str:
        if resolution is None:
            return "bestvideo*+bestaudio/best"
        return (
            f"bestvideo*[height<={resolution}]+bestaudio/"
            f"best[height<={resolution}]/best"
        )

    @staticmethod
    def _build_postprocessors(request: DownloadRequest) -> list[dict[str, Any]]:
        postprocessors: list[dict[str, Any]] = []

        if request.download_subtitles:
            postprocessors.append(
                {
                    "key": "FFmpegSubtitlesConvertor",
                    "format": "srt",
                }
            )

            if request.embed_subtitles:
                postprocessors.append({"key": "FFmpegEmbedSubtitle"})

        return postprocessors

    @staticmethod
    def _safe_prepare_filename(
        ydl: Any, info: dict[str, Any], request: DownloadRequest
    ) -> Path | None:
        try:
            filename = ydl.prepare_filename(info, outtmpl=request.output_template)
        except TypeError:
            try:
                filename = ydl.prepare_filename(info)
            except Exception:
                return None
        except Exception:
            return None

        if not filename:
            return None

        prepared = Path(filename)
        if not prepared.is_absolute():
            prepared = Path(request.output_dir) / prepared
        return prepared

    @staticmethod
    def _resolve_output_path(prepared_filename: Path | None) -> Path | None:
        if prepared_filename is None:
            return None

        candidates = [
            prepared_filename,
            prepared_filename.with_suffix(".mp4"),
            prepared_filename.with_suffix(".mkv"),
            prepared_filename.with_suffix(".webm"),
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        return prepared_filename

    @staticmethod
    def _to_format_info(item: dict[str, Any]) -> FormatInfo:
        width = item.get("width")
        height = item.get("height")
        resolution = item.get("resolution")
        if resolution is None and width and height:
            resolution = f"{width}x{height}"
        if resolution is None and height:
            resolution = f"{height}p"
        if resolution is None and item.get("vcodec") == "none":
            resolution = "audio only"

        return FormatInfo(
            format_id=str(item.get("format_id", "unknown")),
            ext=item.get("ext"),
            resolution=resolution,
            height=height,
            fps=item.get("fps"),
            note=item.get("format_note"),
            vcodec=item.get("vcodec"),
            acodec=item.get("acodec"),
        )
