from pathlib import Path

from youtube_video_downloader.models import DownloadRequest
from youtube_video_downloader.services.downloader import DownloadService


class FakeYoutubeDL:
    last_options = None

    def __init__(self, options):
        self.options = options
        self.home = Path(options.get("paths", {}).get("home", "."))
        FakeYoutubeDL.last_options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download):
        if download:
            video_path = self.home / "Sample [abc123]" / "Sample [abc123].mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_text("video", encoding="utf-8")
        return {
            "id": "abc123",
            "title": "Sample",
            "formats": [
                {
                    "format_id": "137",
                    "ext": "mp4",
                    "height": 1080,
                    "fps": 30,
                    "format_note": "1080p",
                    "vcodec": "avc1",
                    "acodec": "none",
                },
                {
                    "format_id": "140",
                    "ext": "m4a",
                    "height": None,
                    "fps": None,
                    "format_note": "audio",
                    "vcodec": "none",
                    "acodec": "mp4a.40.2",
                },
            ],
        }

    def prepare_filename(self, info, outtmpl=None):
        return str(self.home / "Sample [abc123]" / "Sample [abc123].webm")


def test_build_options_include_resolution_and_subtitles(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        resolution=1080,
        subtitle_languages=("en", "hi"),
        download_subtitles=True,
        embed_subtitles=True,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    assert options["format"] == "bestvideo*[height<=1080]+bestaudio/best[height<=1080]/best"
    assert options["writesubtitles"] is True
    assert options["writeautomaticsub"] is True
    assert options["subtitleslangs"] == ["en", "hi"]
    assert options["postprocessors"][0]["key"] == "FFmpegSubtitlesConvertor"
    assert options["postprocessors"][1]["key"] == "FFmpegEmbedSubtitle"


def test_download_returns_detected_output_path(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        resolution=720,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    result = service.download(request)

    assert result.title == "Sample"
    assert result.video_id == "abc123"
    assert result.output_path == tmp_path / "Sample [abc123]" / "Sample [abc123].mp4"


def test_list_formats_returns_sorted_entries():
    service = DownloadService(ydl_factory=FakeYoutubeDL)
    formats = service.list_formats("https://example.com/watch?v=abc123")

    assert formats[0].format_id == "137"
    assert formats[0].resolution == "1080p"
    assert formats[-1].resolution == "audio only"
