"""Typed models and normalization helpers for the downloader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import (
    DEFAULT_FILENAME_TEMPLATE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SUBTITLE_FORMAT,
    DEFAULT_SUBTITLE_LANGUAGES,
)


class ResolutionParseError(ValueError):
    """Raised when a resolution value cannot be understood."""


class SubtitleLanguageError(ValueError):
    """Raised when subtitle language input is invalid."""


@dataclass(slots=True, frozen=True)
class FormatInfo:
    format_id: str
    ext: str | None
    resolution: str | None
    height: int | None
    fps: float | int | None
    note: str | None
    vcodec: str | None
    acodec: str | None


@dataclass(slots=True, frozen=True)
class DownloadRequest:
    url: str
    output_dir: Path = DEFAULT_OUTPUT_DIR
    resolution: int | None = None
    subtitle_languages: tuple[str, ...] = DEFAULT_SUBTITLE_LANGUAGES
    download_subtitles: bool = True
    auto_subtitles: bool = True
    embed_subtitles: bool = True
    subtitle_format: str = DEFAULT_SUBTITLE_FORMAT
    output_template: str = DEFAULT_FILENAME_TEMPLATE
    restrict_filenames: bool = False
    concurrent_fragments: int = 1
    proxy: str | None = None
    geo_unblock: bool = False

    def __post_init__(self) -> None:
        normalized_url = self.url.strip()
        if not normalized_url:
            raise ValueError("A video URL is required.")

        normalized_output_dir = Path(self.output_dir)
        normalized_resolution = normalize_resolution(self.resolution)

        if self.download_subtitles:
            normalized_languages = normalize_subtitle_languages(self.subtitle_languages)
        else:
            normalized_languages = ()

        object.__setattr__(self, "url", normalized_url)
        object.__setattr__(self, "output_dir", normalized_output_dir)
        object.__setattr__(self, "resolution", normalized_resolution)
        object.__setattr__(self, "subtitle_languages", normalized_languages)

        if int(self.concurrent_fragments) <= 0:
            raise ValueError("Concurrent fragments must be greater than zero.")
        object.__setattr__(self, "concurrent_fragments", int(self.concurrent_fragments))

        if not self.download_subtitles and self.embed_subtitles:
            object.__setattr__(self, "embed_subtitles", False)

        # Normalize the optional proxy: treat blank/whitespace as "no proxy".
        normalized_proxy = (self.proxy or "").strip() or None
        object.__setattr__(self, "proxy", normalized_proxy)


@dataclass(slots=True, frozen=True)
class DownloadResult:
    video_id: str | None
    title: str | None
    output_path: Path | None
    requested_resolution: int | None
    subtitle_languages: tuple[str, ...]


def normalize_resolution(value: int | str | None) -> int | None:
    if value is None:
        return None

    if isinstance(value, int):
        if value <= 0:
            raise ResolutionParseError("Resolution must be a positive integer.")
        return value

    candidate = value.strip().lower()
    if not candidate or candidate in {"best", "max", "highest", "source"}:
        return None

    if candidate.endswith("p"):
        candidate = candidate[:-1]

    if not candidate.isdigit():
        raise ResolutionParseError(
            "Resolution must look like 720, 1080, or 1080p."
        )

    resolution = int(candidate)
    if resolution <= 0:
        raise ResolutionParseError("Resolution must be a positive integer.")
    return resolution


def normalize_subtitle_languages(
    values: Iterable[str] | None,
    *,
    all_languages: bool = False,
) -> tuple[str, ...]:
    if all_languages:
        return ("all",)

    if values is None:
        return DEFAULT_SUBTITLE_LANGUAGES

    normalized: list[str] = []
    for raw_value in values:
        parts = [part.strip() for part in str(raw_value).split(",")]
        for part in parts:
            if not part:
                continue
            language = part.lower()
            if language == "all":
                return ("all",)
            normalized.append(language)

    if not normalized:
        raise SubtitleLanguageError(
            "Provide at least one subtitle language or use --all-subtitles."
        )

    unique_languages = tuple(dict.fromkeys(normalized))
    return unique_languages
