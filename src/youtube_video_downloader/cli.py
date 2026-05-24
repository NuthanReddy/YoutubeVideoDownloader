"""Command-line interface for the YouTube downloader."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

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
        result = DownloadService().download(request)
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
        format_entries = DownloadService().list_formats(url)
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


def main() -> None:
    app()

