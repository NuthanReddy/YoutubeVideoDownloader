"""Integration layer around yt-dlp."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yt_dlp

from ..config import DEFAULT_FILENAME_TEMPLATE
from ..models import DownloadRequest, DownloadResult, FormatInfo


class DownloadError(RuntimeError):
    """Raised when yt-dlp cannot complete the request."""


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

        return options

    def download(self, request: DownloadRequest) -> DownloadResult:
        request.output_dir.mkdir(parents=True, exist_ok=True)
        options = self.build_options(request)

        try:
            with self._ydl_factory(options) as ydl:
                info = ydl.extract_info(request.url, download=True)
                if info is None:
                    raise DownloadError("No video metadata was returned by yt-dlp.")

                prepared_filename = self._safe_prepare_filename(ydl, info)
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
        except Exception as exc:  # pragma: no cover - library/network dependent
            raise DownloadError(str(exc)) from exc

    def list_formats(self, url: str) -> list[FormatInfo]:
        options = {
            "quiet": True,
            "skip_download": True,
            "noplaylist": True,
        }

        try:
            with self._ydl_factory(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # pragma: no cover - library/network dependent
            raise DownloadError(str(exc)) from exc

        formats = info.get("formats") or []
        entries = [self._to_format_info(item) for item in formats]
        return sorted(entries, key=lambda item: (item.height or 0, item.format_id), reverse=True)

    def list_playlist_video_urls(self, url: str) -> list[str]:
        """Return individual video URLs when the input is a playlist URL."""

        options = {
            "quiet": True,
            "skip_download": True,
            "extract_flat": True,
            "noplaylist": False,
        }

        try:
            with self._ydl_factory(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # pragma: no cover - library/network dependent
            raise DownloadError(str(exc)) from exc

        if not info:
            raise DownloadError("No playlist metadata was returned by yt-dlp.")

        entries = info.get("entries") or []
        if not entries:
            return [url]

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
        return unique_urls or [url]

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
    def _safe_prepare_filename(ydl: Any, info: dict[str, Any]) -> Path | None:
        try:
            filename = ydl.prepare_filename(info, outtmpl=DEFAULT_FILENAME_TEMPLATE)
        except TypeError:
            try:
                filename = ydl.prepare_filename(info)
            except Exception:
                return None
        except Exception:
            return None

        return Path(filename) if filename else None

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
