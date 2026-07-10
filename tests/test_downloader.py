from pathlib import Path

from youtube_video_downloader.models import DownloadRequest
from youtube_video_downloader.services.downloader import DownloadService


class FakeYoutubeDL:
    last_options = None
    last_url = None

    def __init__(self, options):
        self.options = options
        self.home = Path(options.get("paths", {}).get("home", "."))
        FakeYoutubeDL.last_options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download):
        FakeYoutubeDL.last_url = url
        if self.options.get("extract_flat"):
            return {
                "id": "pl123",
                "title": "Playlist",
                "entries": [
                    {"id": "abc123"},
                    {"webpage_url": "https://www.youtube.com/watch?v=def456"},
                ],
            }

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
        concurrent_fragments=4,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    assert options["format"] == "bestvideo*[height<=1080]+bestaudio/best[height<=1080]/best"
    assert options["writesubtitles"] is True
    assert options["writeautomaticsub"] is True
    assert options["concurrent_fragment_downloads"] == 4
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


def test_download_wires_progress_hook(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        resolution=720,
    )

    def hook(_status):
        return None

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    service.download(request, progress_hook=hook)

    assert FakeYoutubeDL.last_options["progress_hooks"] == [hook]


def test_download_without_hook_has_no_progress_hooks(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        resolution=720,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    service.download(request)

    assert "progress_hooks" not in FakeYoutubeDL.last_options


def test_list_formats_returns_sorted_entries():
    service = DownloadService(ydl_factory=FakeYoutubeDL)
    formats = service.list_formats("https://example.com/watch?v=abc123")

    assert formats[0].format_id == "137"
    assert formats[0].resolution == "1080p"
    assert formats[-1].resolution == "audio only"


def test_list_playlist_video_urls_expands_entries():
    service = DownloadService(ydl_factory=FakeYoutubeDL)
    urls = service.list_playlist_video_urls("https://www.youtube.com/playlist?list=pl123")

    assert urls == [
        "https://www.youtube.com/watch?v=abc123",
        "https://www.youtube.com/watch?v=def456",
    ]


def test_list_playlist_video_urls_normalizes_watch_list_url():
    service = DownloadService(ydl_factory=FakeYoutubeDL)
    urls = service.list_playlist_video_urls(
        "https://www.youtube.com/watch?v=NLycrsJ1jI8&list=PLabc123"
    )

    assert FakeYoutubeDL.last_url == "https://www.youtube.com/playlist?list=PLabc123"
    assert urls == [
        "https://www.youtube.com/watch?v=abc123",
        "https://www.youtube.com/watch?v=def456",
    ]


def test_playlist_url_from_variants():
    normalize = DownloadService._playlist_url_from

    assert (
        normalize("https://www.youtube.com/watch?v=x&list=PLabc")
        == "https://www.youtube.com/playlist?list=PLabc"
    )
    assert (
        normalize("https://youtu.be/x?list=PLabc")
        == "https://www.youtube.com/playlist?list=PLabc"
    )
    # Already a playlist URL, a plain video, an auto-mix, and non-YouTube: unchanged.
    assert (
        normalize("https://www.youtube.com/playlist?list=PLabc")
        == "https://www.youtube.com/playlist?list=PLabc"
    )
    assert normalize("https://www.youtube.com/watch?v=x") == "https://www.youtube.com/watch?v=x"
    assert (
        normalize("https://www.youtube.com/watch?v=x&list=RDxyz")
        == "https://www.youtube.com/watch?v=x&list=RDxyz"
    )
    assert (
        normalize("https://example.com/watch?v=x&list=PLabc")
        == "https://example.com/watch?v=x&list=PLabc"
    )
