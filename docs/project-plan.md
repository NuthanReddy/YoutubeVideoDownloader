# Phase-wise Project Plan

## Goal

Build a Python CLI that downloads YouTube videos with configurable resolution and subtitle support, using `uv` for package management.

## Confirmed assumptions

- The project-local Python interpreter is `.venv\Scripts\python.exe`.
- The workspace started as a greenfield project.
- `yt-dlp` is the practical download engine for YouTube content.
- `ffmpeg` is an external prerequisite for best stream merging and subtitle embedding.

## Phase 1 — Project structure and module setup

- Create a `src`-layout Python package.
- Add a `pyproject.toml` configured for `uv`.
- Add the package root, service module, test module, and documentation folder.
- Define a CLI entry point and package execution path.

## Phase 2 — Architecture and design

- Use a CLI-first design with `Typer`.
- Keep input validation and normalization inside model helpers.
- Encapsulate `yt-dlp` integration inside a dedicated `DownloadService`.
- Separate request models from service logic to keep tests easy.
- Support two main workflows:
  - inspect available formats
  - download video with optional subtitles

## Phase 3 — Implementation

- Implement typed download request models.
- Implement resolution parsing with support for values like `720` and `1080p`.
- Implement subtitle language normalization and `all subtitles` behavior.
- Build `yt-dlp` options dynamically based on CLI inputs.
- Support subtitle download, automatic subtitles, and subtitle embedding.
- Add clear terminal output for success and configuration errors.

## Phase 4 — Testing and validation

- Add unit tests for request normalization.
- Add unit tests for downloader option generation.
- Add CLI tests with mocked service behavior.
- Install dependencies with `uv sync --dev`.
- Run the test suite using the local `.venv` interpreter.

## Risks and mitigations

- **YouTube format variability**: use resolution cap fallback rules instead of exact format IDs.
- **Subtitle availability varies by video**: allow automatic subtitles and all-language selection.
- **Embedding subtitles may fail without ffmpeg**: document the requirement clearly.
- **Network-dependent behavior is hard to test**: keep tests focused on option generation and CLI flow.

