"""Integration layer around yt-dlp."""

from __future__ import annotations

import os
import sys
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
    MAX_AUTO_PROXY_ATTEMPTS,
    PROXY_SOCKET_TIMEOUT,
)
from ..models import DownloadRequest, DownloadResult, FormatInfo
from . import proxy_provider

# --- Disable yt-dlp's optional plugin discovery -----------------------------
# The first time a YoutubeDL is constructed, yt-dlp scans sys.path, the current
# working directory and the executable directory for an optional
# ``yt_dlp_plugins`` namespace package. If the app is launched from a sandbox
# that redirects any of those locations through an *untrusted* junction / reparse
# point (e.g. under Windows' "RedirectionTrust" process mitigation), that scan
# raises ``OSError: [WinError 448] ... untrusted mount point`` and the download
# aborts before it even starts. This app neither ships nor supports plugins, so
# we turn the scan off for a self-contained, predictable runtime.
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


class DownloadError(RuntimeError):
    """Raised when yt-dlp cannot complete the request."""


# Substrings that identify a YouTube uploader/geo region block. Matched
# case-insensitively against the yt-dlp error text to decide whether the
# "bypass region block" proxy fallback should kick in.
_GEO_BLOCK_MARKERS = (
    "available in your country",
    "not available in your country",
    "blocked it in your country",
    "geo restricted",
    "geo-restricted",
    "georestrictederror",
    "who has blocked it on copyright grounds",
)


def _is_geo_restricted_error(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _GEO_BLOCK_MARKERS)


def _emit(status_callback: Callable[[str], None] | None, message: str) -> None:
    if status_callback is not None:
        try:
            status_callback(message)
        except Exception:  # pragma: no cover - logging must never break a download
            pass


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


def _youtube_extractor_options(proxy: str | None = None) -> dict[str, Any]:
    """Shared yt-dlp options that pick resilient YouTube player clients.

    We pass a list of player clients (see ``DEFAULT_PLAYER_CLIENTS``): yt-dlp
    tries each, merges the formats they return, and only fails if all of them
    fail. This gives the full HD ladder from the ``default`` clients while
    keeping ``android`` as a fallback for networks where YouTube bot-blocks the
    web-family clients. Applied to every ``extract_info`` call so metadata
    listing, playlist expansion and downloads all use the same clients.

    When ``proxy`` is provided (e.g. ``socks5://127.0.0.1:1080`` or
    ``http://user:pass@host:port``) every request is routed through it, which is
    the reliable way to reach videos the uploader has geo-restricted.
    """

    options: dict[str, Any] = {
        "extractor_args": {
            "youtube": {"player_client": list(DEFAULT_PLAYER_CLIENTS)}
        },
        "extractor_retries": DEFAULT_EXTRACTOR_RETRIES,
    }
    if proxy:
        options["proxy"] = proxy
    return options


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
            "concurrent_fragment_downloads": request.concurrent_fragments,
            **_youtube_extractor_options(request.proxy),
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
        """Download ``request``, transparently routing around region blocks.

        Normal flow: attempt the download directly (using a pinned proxy if the
        request carries one). If that fails with a *geo-restriction* error and
        the request opted into ``geo_unblock`` without a pinned proxy, retry the
        same video through free proxies located in allowed countries until one
        works. ``status_callback`` receives human-readable progress lines and
        ``is_cancelled`` lets the caller abort the proxy hunt between attempts.
        """

        request.output_dir.mkdir(parents=True, exist_ok=True)

        try:
            return self._download_once(request, progress_hook=progress_hook)
        except DownloadCancelled:
            raise
        except DownloadError as exc:
            geo_blocked = _is_geo_restricted_error(str(exc))
            can_auto = request.geo_unblock and not request.proxy and geo_blocked
            if not can_auto:
                raise
            first_error = exc

        return self._download_via_auto_proxy(
            request,
            progress_hook=progress_hook,
            status_callback=status_callback,
            is_cancelled=is_cancelled,
            first_error=first_error,
        )

    def _download_once(
        self,
        request: DownloadRequest,
        *,
        proxy: str | None = None,
        socket_timeout: int | None = None,
        progress_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> DownloadResult:
        options = self.build_options(request)
        if proxy:
            options["proxy"] = proxy
        if socket_timeout:
            options["socket_timeout"] = socket_timeout
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

    def _download_via_auto_proxy(
        self,
        request: DownloadRequest,
        *,
        progress_hook: Callable[[dict[str, Any]], None] | None,
        status_callback: Callable[[str], None] | None,
        is_cancelled: Callable[[], bool] | None,
        first_error: DownloadError,
    ) -> DownloadResult:
        """Retry a geo-blocked video through free proxies in allowed countries."""

        _emit(
            status_callback,
            "Region-blocked - searching for a proxy in an allowed country...",
        )

        def cancelled() -> bool:
            return bool(is_cancelled and is_cancelled())

        attempts = 0
        last_error: DownloadError = first_error
        tried: set[str] = set()

        # A proxy that already worked (e.g. for a sibling playlist item) is very
        # likely to work again, so try it first to avoid re-scanning every time.
        remembered = proxy_provider.get_remembered_proxy()
        if remembered and not cancelled():
            tried.add(remembered)
            attempts += 1
            _emit(status_callback, f"Trying last working proxy ({remembered})...")
            try:
                result = self._download_once(
                    request,
                    proxy=remembered,
                    socket_timeout=PROXY_SOCKET_TIMEOUT,
                    progress_hook=progress_hook,
                )
                proxy_provider.remember_good_proxy(remembered)
                return result
            except DownloadCancelled:
                raise
            except DownloadError as exc:
                last_error = exc
                proxy_provider.forget_proxy(remembered)

        candidates = proxy_provider.fetch_proxy_candidates()
        if not candidates and attempts == 0:
            raise DownloadError(
                "Region-blocked, and no free proxy could be fetched. Connect a "
                "VPN, or paste your own proxy (http/https/socks5) in the Proxy "
                f"field for a reliable route. Original error: {first_error}"
            )

        probes = 0
        for candidate in candidates:
            if cancelled():
                raise DownloadCancelled()
            if attempts >= MAX_AUTO_PROXY_ATTEMPTS:
                break
            if candidate.url in tried:
                continue
            # Bound how many dead proxies we probe so the hunt can't run forever.
            if probes >= proxy_provider.AUTO_PROXY_CANDIDATE_POOL:
                break
            probes += 1
            if not proxy_provider.proxy_is_live(candidate.url):
                continue

            tried.add(candidate.url)
            attempts += 1
            _emit(
                status_callback,
                f"Trying proxy {attempts}/{MAX_AUTO_PROXY_ATTEMPTS} via "
                f"{candidate.country} ({candidate.url})...",
            )
            try:
                result = self._download_once(
                    request,
                    proxy=candidate.url,
                    socket_timeout=PROXY_SOCKET_TIMEOUT,
                    progress_hook=progress_hook,
                )
                proxy_provider.remember_good_proxy(candidate.url)
                _emit(status_callback, f"Proxy via {candidate.country} succeeded.")
                return result
            except DownloadCancelled:
                raise
            except DownloadError as exc:
                last_error = exc
                continue

        raise DownloadError(
            f"Region-blocked; tried {attempts} proxy/proxies in allowed "
            "countries but none worked. Free proxies are unreliable - connect a "
            "VPN or paste your own proxy in the Proxy field for a reliable "
            f"route. Last error: {last_error}"
        )

    def list_formats(self, url: str, *, proxy: str | None = None) -> list[FormatInfo]:
        options = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
            **_youtube_extractor_options(proxy),
        }

        try:
            with self._ydl_factory(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # pragma: no cover - library/network dependent
            raise DownloadError(str(exc)) from exc

        formats = info.get("formats") or []
        entries = [self._to_format_info(item) for item in formats]
        return sorted(entries, key=lambda item: (item.height or 0, item.format_id), reverse=True)

    def list_playlist_video_urls(self, url: str, *, proxy: str | None = None) -> list[str]:
        """Return individual video URLs when the input is a playlist URL."""

        return self.expand_playlist(url, proxy=proxy)[1]

    def expand_playlist(
        self, url: str, *, proxy: str | None = None
    ) -> tuple[str | None, list[str]]:
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
            **_youtube_extractor_options(proxy),
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
