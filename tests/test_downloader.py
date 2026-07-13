from pathlib import Path

import pytest

from youtube_video_downloader.models import DownloadRequest
from youtube_video_downloader.services import downloader as downloader_module
from youtube_video_downloader.services.downloader import DownloadError, DownloadService


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
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    assert options["format"] == "bestvideo*[height<=1080]+bestaudio/best[height<=1080]/best"
    assert options["writesubtitles"] is True
    assert options["writeautomaticsub"] is True
    assert options["subtitleslangs"] == ["en", "hi"]
    assert options["postprocessors"][0]["key"] == "FFmpegSubtitlesConvertor"
    assert options["postprocessors"][1]["key"] == "FFmpegEmbedSubtitle"


def test_build_options_uses_resilient_player_clients(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        download_subtitles=False,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    clients = options["extractor_args"]["youtube"]["player_client"]
    # ``default`` provides the HD ladder; ``android`` is the fallback that keeps
    # downloads working when the web-family clients are bot-blocked.
    assert "default" in clients
    assert "android" in clients
    assert clients.index("default") < clients.index("android")


def test_build_options_includes_rate_limit_safety(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        download_subtitles=False,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    # Throttling + backoff that keeps request rate under YouTube's 429 limit.
    assert options["sleep_interval_requests"] == downloader_module.SLEEP_INTERVAL_REQUESTS
    assert options["sleep_interval"] == downloader_module.MIN_SLEEP_INTERVAL
    assert options["max_sleep_interval"] == downloader_module.MAX_SLEEP_INTERVAL
    assert options["retries"] == downloader_module.DOWNLOAD_RETRIES
    assert options["fragment_retries"] == downloader_module.FRAGMENT_RETRIES
    assert options["extractor_retries"] == downloader_module.DEFAULT_EXTRACTOR_RETRIES
    assert options["socket_timeout"] == downloader_module.DEFAULT_SOCKET_TIMEOUT
    for key in ("http", "fragment", "extractor"):
        assert options["retry_sleep_functions"][key] is downloader_module._retry_sleep


def test_build_options_drops_concurrent_fragment_downloads(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        download_subtitles=False,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    # Concurrent fragments multiply the request rate (429 risk) and were removed.
    assert "concurrent_fragment_downloads" not in options


def test_build_options_wires_js_runtime_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(
        downloader_module, "_resolve_js_runtimes", lambda: {"deno": {"path": "/opt/deno"}}
    )
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        download_subtitles=False,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    # A JS runtime lets yt-dlp solve YouTube's ``n`` challenge -> HD formats.
    assert options["js_runtimes"] == {"deno": {"path": "/opt/deno"}}


def test_build_options_omits_js_runtime_when_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module, "_resolve_js_runtimes", lambda: {})
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        download_subtitles=False,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    # Nothing resolved -> leave yt-dlp's own default untouched.
    assert "js_runtimes" not in options


def test_retry_sleep_is_bounded_exponential_backoff():
    base = downloader_module.RETRY_BACKOFF_BASE_SECONDS
    cap = downloader_module.RETRY_BACKOFF_MAX_SECONDS

    assert downloader_module._retry_sleep(1) == base
    assert downloader_module._retry_sleep(2) == base * 2
    assert downloader_module._retry_sleep(3) == base * 4
    # Grows without bound in theory, but is capped so retries never sleep forever.
    assert downloader_module._retry_sleep(1000) == cap


def test_deno_location_resolves_bundled_binary(tmp_path, monkeypatch):
    deno_dir = tmp_path / "deno_bin"
    deno_dir.mkdir()
    binary = "deno.exe" if downloader_module.os.name == "nt" else "deno"
    (deno_dir / binary).write_text("deno", encoding="utf-8")
    monkeypatch.setattr(downloader_module.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert downloader_module._deno_location() == str(deno_dir / binary)


def test_build_options_sets_ffmpeg_location_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(
        downloader_module, "_ffmpeg_location", lambda: "/opt/ffmpeg_bin"
    )
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        download_subtitles=False,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    assert options["ffmpeg_location"] == "/opt/ffmpeg_bin"


def test_build_options_omits_ffmpeg_location_when_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader_module, "_ffmpeg_location", lambda: None)
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        download_subtitles=False,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    assert "ffmpeg_location" not in options


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


def test_ytdlp_plugin_discovery_is_disabled(monkeypatch):
    """Importing the downloader must switch off yt-dlp's plugin scan.

    yt-dlp otherwise walks sys.path / CWD / the executable dir looking for a
    ``yt_dlp_plugins`` package. When one of those locations is redirected through
    an untrusted junction (Windows RedirectionTrust mitigation), the scan raises
    ``OSError [WinError 448]`` and aborts the download. With the scan disabled,
    ``load_plugins`` returns early and never touches the filesystem.
    """

    import yt_dlp.plugins as pl

    # The downloader import (already loaded above) sets this guard.
    assert downloader_module.os.environ.get("YTDLP_NO_PLUGINS")

    def _explode(*_args, **_kwargs):  # pragma: no cover - must never run
        raise OSError(
            448, "The path cannot be traversed ... untrusted mount point"
        )

    # If the guard failed, load_plugins would reach the scanner and blow up.
    monkeypatch.setattr(pl, "iter_modules", _explode)
    spec = next(iter(pl.plugin_specs.value.values()))

    assert pl.load_plugins(spec) == {}


def test_harden_runtime_paths_drops_untraversable_entries(monkeypatch):
    """PATH entries that fault on ``realpath`` must be scrubbed on Windows.

    yt-dlp locates its JS runtime (Deno) by mapping ``os.path.realpath`` over
    every ``PATH`` entry. ``realpath`` -- unlike ``os.path.exists`` -- does not
    swallow ``OSError``, so an *untrusted* junction on ``PATH`` (e.g. the
    ``...\\agency\\CurrentVersion`` directory some sandboxes inject, under the
    Windows RedirectionTrust mitigation) raises ``[WinError 448]`` and aborts
    every extraction. ``_harden_runtime_paths`` drops the faulting entries.
    """

    import os

    if os.name != "nt":
        pytest.skip("PATH hardening only runs on Windows")

    bad = r"C:\Users\x\AppData\Roaming\agency\CurrentVersion"
    good_first = r"C:\Windows\System32"
    good_last = r"C:\Tools\bin"
    monkeypatch.setenv("PATH", os.pathsep.join([good_first, bad, good_last]))

    real_realpath = os.path.realpath

    def fake_realpath(path, *args, **kwargs):
        if path == bad:
            raise OSError(448, "untrusted mount point")
        return real_realpath(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", fake_realpath)

    downloader_module._harden_runtime_paths()

    entries = os.environ["PATH"].split(os.pathsep)
    assert bad not in entries
    assert good_first in entries
    assert good_last in entries


def test_humanize_youtube_error_adds_hints():
    drm = downloader_module.humanize_youtube_error("This video is DRM protected")
    assert "DRM-protected" in drm

    signin = downloader_module.humanize_youtube_error(
        "Sign in to confirm you're not a bot"
    )
    assert "anonymously" in signin.lower()

    sabr = downloader_module.humanize_youtube_error(
        "ERROR: requested format is not available"
    )
    assert "sabr" in sabr.lower()

    plain = downloader_module.humanize_youtube_error("Some unrelated error")
    assert plain == "Some unrelated error"
