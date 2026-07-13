from pathlib import Path

import pytest

from youtube_video_downloader.models import DownloadRequest
from youtube_video_downloader.services import downloader as downloader_module
from youtube_video_downloader.services import proxy_provider
from youtube_video_downloader.services.downloader import DownloadError, DownloadService
from youtube_video_downloader.services.proxy_provider import ProxyCandidate


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


# ---------------------------------------------------------------------------
# Region-block bypass (proxy) support
# ---------------------------------------------------------------------------


def test_build_options_injects_pinned_proxy(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        download_subtitles=False,
        proxy="socks5://127.0.0.1:9050",
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    assert options["proxy"] == "socks5://127.0.0.1:9050"


def test_build_options_omits_proxy_when_absent(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        download_subtitles=False,
    )

    service = DownloadService(ydl_factory=FakeYoutubeDL)
    options = service.build_options(request)

    assert "proxy" not in options


def test_download_request_normalizes_blank_proxy(tmp_path):
    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        proxy="   ",
    )
    assert request.proxy is None

    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        proxy="  http://host:8080  ",
    )
    assert request.proxy == "http://host:8080"


def test_is_geo_restricted_error_detects_uploader_block():
    detect = downloader_module._is_geo_restricted_error
    assert detect("ERROR: The uploader has not made this video available in your country")
    assert detect("This video is geo restricted")
    assert not detect("HTTP Error 429: Too Many Requests")
    assert not detect("Video unavailable")


class _GeoBlockingYoutubeDL(FakeYoutubeDL):
    """Fails with a geo-block error unless a proxy is configured."""

    proxies_seen: list = []

    def extract_info(self, url, download):
        _GeoBlockingYoutubeDL.proxies_seen.append(self.options.get("proxy"))
        if download and not self.options.get("proxy"):
            raise RuntimeError(
                "ERROR: [youtube] abc123: The uploader has not made this "
                "video available in your country"
            )
        return super().extract_info(url, download)


@pytest.fixture(autouse=True)
def _reset_remembered_proxy():
    proxy_provider.forget_proxy(proxy_provider.get_remembered_proxy() or "")
    yield
    proxy_provider.forget_proxy(proxy_provider.get_remembered_proxy() or "")


def test_auto_proxy_fallback_retries_via_free_proxy(tmp_path, monkeypatch):
    _GeoBlockingYoutubeDL.proxies_seen = []
    remembered: list[str] = []

    monkeypatch.setattr(proxy_provider, "get_remembered_proxy", lambda: None)
    monkeypatch.setattr(
        proxy_provider,
        "fetch_proxy_candidates",
        lambda: [ProxyCandidate("http://1.2.3.4:8080", "US")],
    )
    monkeypatch.setattr(proxy_provider, "proxy_is_live", lambda url: True)
    monkeypatch.setattr(
        proxy_provider, "remember_good_proxy", lambda url: remembered.append(url)
    )

    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        resolution=720,
        geo_unblock=True,
    )
    service = DownloadService(ydl_factory=_GeoBlockingYoutubeDL)
    messages: list[str] = []
    result = service.download(request, status_callback=messages.append)

    assert result.video_id == "abc123"
    # First attempt has no proxy (fails), the retry carries the free proxy.
    assert _GeoBlockingYoutubeDL.proxies_seen[0] is None
    assert "http://1.2.3.4:8080" in _GeoBlockingYoutubeDL.proxies_seen
    assert remembered == ["http://1.2.3.4:8080"]
    assert any("proxy" in m.lower() for m in messages)


def test_auto_proxy_not_used_without_geo_unblock(tmp_path, monkeypatch):
    _GeoBlockingYoutubeDL.proxies_seen = []

    def _boom():  # pragma: no cover - must never be called
        raise AssertionError("proxy hunt should not start without geo_unblock")

    monkeypatch.setattr(proxy_provider, "fetch_proxy_candidates", _boom)

    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        resolution=720,
        geo_unblock=False,
    )
    service = DownloadService(ydl_factory=_GeoBlockingYoutubeDL)

    with pytest.raises(DownloadError):
        service.download(request)


def test_pinned_proxy_skips_auto_hunt(tmp_path, monkeypatch):
    _GeoBlockingYoutubeDL.proxies_seen = []

    def _boom():  # pragma: no cover - must never be called
        raise AssertionError("auto hunt should not run when a proxy is pinned")

    monkeypatch.setattr(proxy_provider, "fetch_proxy_candidates", _boom)

    request = DownloadRequest(
        url="https://example.com/watch?v=abc123",
        output_dir=tmp_path,
        resolution=720,
        geo_unblock=True,
        proxy="http://9.9.9.9:3128",
    )
    service = DownloadService(ydl_factory=_GeoBlockingYoutubeDL)
    result = service.download(request)

    # The pinned proxy is applied on the very first attempt, so it succeeds
    # immediately without ever fetching free proxy candidates.
    assert result.video_id == "abc123"
    assert _GeoBlockingYoutubeDL.proxies_seen == ["http://9.9.9.9:3128"]


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
