"""Command-line interface for the YouTube downloader."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import DEFAULT_OUTPUT_DIR, DEFAULT_SUBTITLE_LANGUAGES
from .models import (
    DownloadRequest,
    ResolutionParseError,
    SubtitleLanguageError,
    normalize_resolution,
    normalize_subtitle_languages,
)
from .services.downloader import DownloadError, DownloadService

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Download YouTube videos with configurable resolution and subtitles.",
)


@app.command()
def download(
    url: Annotated[str, typer.Argument(help="The YouTube video URL to download.")],
    resolution: Annotated[
        str | None,
        typer.Option(
            "--resolution",
            "-r",
            help="Maximum video height such as 720, 1080, or 1080p. Use 'best' for no limit.",
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory where downloaded files will be stored.",
        ),
    ] = DEFAULT_OUTPUT_DIR,
    subtitle_lang: Annotated[
        list[str] | None,
        typer.Option(
            "--subtitle-lang",
            "-s",
            help="Subtitle language to download. Repeat the flag for multiple languages.",
        ),
    ] = None,
    all_subtitles: Annotated[
        bool,
        typer.Option(
            "--all-subtitles",
            help="Download all available subtitle languages.",
        ),
    ] = False,
    subtitles: Annotated[
        bool,
        typer.Option(
            "--subtitles/--no-subtitles",
            help="Enable or disable subtitle downloading.",
        ),
    ] = True,
    auto_subtitles: Annotated[
        bool,
        typer.Option(
            "--auto-subtitles/--no-auto-subtitles",
            help="Allow automatic subtitles when uploaded subtitles are missing.",
        ),
    ] = True,
    embed_subtitles: Annotated[
        bool,
        typer.Option(
            "--embed-subtitles/--sidecar-subtitles",
            help="Embed subtitles in the media when possible, otherwise keep sidecar subtitle files.",
        ),
    ] = True,
    restrict_filenames: Annotated[
        bool,
        typer.Option(
            "--restrict-filenames/--allow-unicode-filenames",
            help="Use yt-dlp restricted filenames for cross-platform safety.",
        ),
    ] = False,
    playlist: Annotated[
        bool,
        typer.Option(
            "--playlist/--single",
            help="Treat URL as playlist and download all videos.",
        ),
    ] = False,
    playlist_workers: Annotated[
        int,
        typer.Option(
            "--playlist-workers",
            min=1,
            help="Number of parallel workers used when downloading playlist videos.",
        ),
    ] = 3,
 ) -> None:
    """Download a single YouTube video."""

    try:
        normalized_resolution = normalize_resolution(resolution)
        raw_languages = subtitle_lang or list(DEFAULT_SUBTITLE_LANGUAGES)
        normalized_languages = normalize_subtitle_languages(
            raw_languages,
            all_languages=all_subtitles,
        )
        request = DownloadRequest(
            url=url,
            output_dir=output_dir,
            resolution=normalized_resolution,
            subtitle_languages=normalized_languages,
            download_subtitles=subtitles,
            auto_subtitles=auto_subtitles,
            embed_subtitles=embed_subtitles,
            restrict_filenames=restrict_filenames,
        )
        service = DownloadService()

        if playlist:
            video_urls = service.list_playlist_video_urls(url)
            if not video_urls:
                raise DownloadError("No playlist videos were found.")

            typer.echo(f"Found {len(video_urls)} videos in playlist. Starting parallel download...")
            failures: list[tuple[str, str]] = []
            completed = 0
            with ThreadPoolExecutor(max_workers=playlist_workers) as executor:
                futures = {
                    executor.submit(
                        service.download,
                        DownloadRequest(
                            url=video_url,
                            output_dir=output_dir,
                            resolution=normalized_resolution,
                            subtitle_languages=normalized_languages,
                            download_subtitles=subtitles,
                            auto_subtitles=auto_subtitles,
                            embed_subtitles=embed_subtitles,
                            restrict_filenames=restrict_filenames,
                        ),
                    ): video_url
                    for video_url in video_urls
                }

                for future in as_completed(futures):
                    video_url = futures[future]
                    try:
                        item_result = future.result()
                        completed += 1
                        title = item_result.title or item_result.video_id or video_url
                        typer.secho(
                            f"[{completed}/{len(video_urls)}] Downloaded: {title}",
                            fg=typer.colors.GREEN,
                        )
                    except Exception as exc:
                        failures.append((video_url, str(exc)))

            if failures:
                typer.secho(
                    f"Playlist download finished with {len(failures)} failure(s).",
                    fg=typer.colors.YELLOW,
                )
                for failed_url, reason in failures:
                    typer.secho(f"- {failed_url}: {reason}", fg=typer.colors.RED)
                raise typer.Exit(code=1)

            typer.secho(
                f"Playlist download completed ({completed}/{len(video_urls)}).",
                fg=typer.colors.GREEN,
            )
            return

        result = service.download(
            request,
            status_callback=lambda message: typer.echo(message),
        )
    except (ResolutionParseError, SubtitleLanguageError, ValueError) as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except DownloadError as exc:
        typer.secho(f"Download failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.secho("Download completed.", fg=typer.colors.GREEN)
    if result.title:
        typer.echo(f"Title: {result.title}")
    if result.video_id:
        typer.echo(f"Video ID: {result.video_id}")
    if result.output_path:
        typer.echo(f"Saved to: {result.output_path}")
    if request.download_subtitles:
        typer.echo(f"Subtitle languages: {', '.join(result.subtitle_languages)}")


@app.command("formats")
def formats(
    url: Annotated[str, typer.Argument(help="The YouTube video URL to inspect.")],
) -> None:
    """List the formats that yt-dlp reports for a YouTube video."""

    try:
        service = DownloadService()
        format_entries = service.list_formats(url)
    except ValueError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except DownloadError as exc:
        typer.secho(f"Could not fetch formats: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if not format_entries:
        typer.echo("No formats were returned.")
        return

    typer.echo("format_id | ext | resolution | fps | note | codecs")
    typer.echo("-" * 72)
    for entry in format_entries:
        codecs = f"v={entry.vcodec or 'n/a'}, a={entry.acodec or 'n/a'}"
        typer.echo(
            f"{entry.format_id} | {entry.ext or 'n/a'} | {entry.resolution or 'n/a'} | "
            f"{entry.fps or 'n/a'} | {entry.note or 'n/a'} | {codecs}"
        )


@app.command("gui")
def gui(
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory where downloaded files will be stored and managed.",
        ),
    ] = DEFAULT_OUTPUT_DIR,
) -> None:
    """Launch the desktop GUI."""

    # Import lazily so environments without Tk still allow CLI-only usage.
    from .gui import launch_gui

    launch_gui(output_dir=output_dir)


def main() -> None:
    app()
