from youtube_video_downloader.gui import _resolution_choice_from_format
from youtube_video_downloader.models import FormatInfo


def test_resolution_choice_prefers_note_value():
    item = FormatInfo(
        format_id="571",
        ext="mp4",
        resolution="7680x3840",
        height=3840,
        fps=24,
        note="4320p",
        vcodec="av01",
        acodec="none",
    )

    assert _resolution_choice_from_format(item) == 4320


def test_resolution_choice_falls_back_to_height():
    item = FormatInfo(
        format_id="399",
        ext="mp4",
        resolution="1920x1080",
        height=1080,
        fps=30,
        note=None,
        vcodec="avc1",
        acodec="none",
    )

    assert _resolution_choice_from_format(item) == 1080

