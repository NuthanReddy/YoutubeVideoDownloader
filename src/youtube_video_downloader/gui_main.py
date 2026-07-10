"""Standalone GUI entrypoint for desktop app packaging."""

from __future__ import annotations

from youtube_video_downloader.gui import launch_gui


def main() -> None:
    launch_gui()


if __name__ == "__main__":
    main()

