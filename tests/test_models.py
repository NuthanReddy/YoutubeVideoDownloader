from pathlib import Path

import pytest

from youtube_video_downloader.models import (
    DownloadRequest,
    ResolutionParseError,
    SubtitleLanguageError,
    normalize_resolution,
    normalize_subtitle_languages,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("best", None),
        ("1080p", 1080),
        ("720", 720),
        (1440, 1440),
    ],
)
def test_normalize_resolution_accepts_supported_values(value, expected):
    assert normalize_resolution(value) == expected


@pytest.mark.parametrize("value", ["abc", "0", -1])
def test_normalize_resolution_rejects_invalid_values(value):
    with pytest.raises(ResolutionParseError):
        normalize_resolution(value)


def test_normalize_subtitle_languages_deduplicates_and_normalizes_case():
    assert normalize_subtitle_languages(["EN", "en", "Hi"]) == ("en", "hi")


def test_normalize_subtitle_languages_supports_all_subtitles_flag():
    assert normalize_subtitle_languages(["en"], all_languages=True) == ("all",)


def test_normalize_subtitle_languages_requires_at_least_one_value():
    with pytest.raises(SubtitleLanguageError):
        normalize_subtitle_languages(["  ", ""])


def test_download_request_disables_embed_when_subtitles_are_disabled():
    request = DownloadRequest(
        url="https://example.com/watch?v=123",
        output_dir=Path("downloads"),
        download_subtitles=False,
        embed_subtitles=True,
    )

    assert request.subtitle_languages == ()
    assert request.embed_subtitles is False


def test_download_request_normalizes_concurrent_fragments_to_int():
    request = DownloadRequest(
        url="https://example.com/watch?v=123",
        concurrent_fragments="4",
    )

    assert request.concurrent_fragments == 4


def test_download_request_rejects_invalid_concurrent_fragments():
    with pytest.raises(ValueError):
        DownloadRequest(
            url="https://example.com/watch?v=123",
            concurrent_fragments=0,
        )
