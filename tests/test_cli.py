from pathlib import Path

from typer.testing import CliRunner

from youtube_video_downloader.cli import app
from youtube_video_downloader.models import DownloadResult

runner = CliRunner()


def test_download_command_passes_normalized_request(monkeypatch, tmp_path):
    captured = {}

    def fake_download(self, request, **kwargs):
        captured["request"] = request
        return DownloadResult(
            video_id="abc123",
            title="Example",
            output_path=tmp_path / "Example.mp4",
            requested_resolution=request.resolution,
            subtitle_languages=request.subtitle_languages,
        )

    monkeypatch.setattr(
        "youtube_video_downloader.cli.DownloadService.download",
        fake_download,
    )

    result = runner.invoke(
        app,
        [
            "download",
            "https://example.com/watch?v=abc123",
            "--resolution",
            "1080p",
            "--output-dir",
            str(tmp_path),
            "--subtitle-lang",
            "EN",
            "--subtitle-lang",
            "hi",
            "--concurrent-fragments",
            "4",
        ],
    )

    assert result.exit_code == 0
    request = captured["request"]
    assert request.resolution == 1080
    assert request.output_dir == Path(tmp_path)
    assert request.subtitle_languages == ("en", "hi")
    assert request.concurrent_fragments == 4
    assert "Download completed." in result.stdout


def test_download_command_rejects_bad_resolution():
    result = runner.invoke(
        app,
        [
            "download",
            "https://example.com/watch?v=abc123",
            "--resolution",
            "bad-value",
        ],
    )

    assert result.exit_code == 1
    assert "Configuration error" in (result.stdout + result.stderr)


def test_formats_command_prints_table(monkeypatch):
    from youtube_video_downloader.models import FormatInfo

    def fake_list_formats(self, url, **kwargs):
        return [
            FormatInfo(
                format_id="137",
                ext="mp4",
                resolution="1920x1080",
                height=1080,
                fps=30,
                note="1080p",
                vcodec="avc1",
                acodec="none",
            )
        ]

    monkeypatch.setattr(
        "youtube_video_downloader.cli.DownloadService.list_formats",
        fake_list_formats,
    )

    result = runner.invoke(app, ["formats", "https://example.com/watch?v=abc123"])

    assert result.exit_code == 0
    assert "format_id | ext | resolution" in result.stdout
    assert "137 | mp4 | 1920x1080" in result.stdout


def test_gui_command_invokes_launcher(monkeypatch, tmp_path):
    captured = {}

    def fake_launch_gui(output_dir, **kwargs):
        captured["output_dir"] = output_dir

    monkeypatch.setattr("youtube_video_downloader.gui.launch_gui", fake_launch_gui)

    result = runner.invoke(app, ["gui", "--output-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert captured["output_dir"] == Path(tmp_path)


def test_download_playlist_mode_expands_urls(monkeypatch, tmp_path):
    captured_urls = []

    def fake_playlist_urls(self, url, **kwargs):
        return [
            "https://example.com/watch?v=one",
            "https://example.com/watch?v=two",
        ]

    def fake_download(self, request, **kwargs):
        captured_urls.append(request.url)
        return DownloadResult(
            video_id=request.url.rsplit("=", 1)[-1],
            title="Example",
            output_path=tmp_path / "Example.mp4",
            requested_resolution=request.resolution,
            subtitle_languages=request.subtitle_languages,
        )

    monkeypatch.setattr(
        "youtube_video_downloader.cli.DownloadService.list_playlist_video_urls",
        fake_playlist_urls,
    )
    monkeypatch.setattr(
        "youtube_video_downloader.cli.DownloadService.download",
        fake_download,
    )

    result = runner.invoke(
        app,
        [
            "download",
            "https://example.com/playlist?list=test",
            "--playlist",
            "--playlist-workers",
            "2",
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert "Playlist download completed" in result.stdout
    assert set(captured_urls) == {
        "https://example.com/watch?v=one",
        "https://example.com/watch?v=two",
    }
