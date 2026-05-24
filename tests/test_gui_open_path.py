from pathlib import Path

from youtube_video_downloader import gui


def test_open_path_uses_startfile_on_windows(monkeypatch, tmp_path):
    called = {}

    monkeypatch.setattr(gui.sys, "platform", "win32")

    def fake_startfile(value):
        called["value"] = value

    monkeypatch.setattr(gui.os, "startfile", fake_startfile, raising=False)

    gui._open_path_in_file_manager(tmp_path)

    assert called["value"] == str(tmp_path.resolve())


def test_open_path_uses_open_on_macos(monkeypatch, tmp_path):
    called = {}

    monkeypatch.setattr(gui.sys, "platform", "darwin")

    def fake_run(cmd, check):
        called["cmd"] = cmd
        called["check"] = check

    monkeypatch.setattr(gui.subprocess, "run", fake_run)

    gui._open_path_in_file_manager(tmp_path)

    assert called["cmd"] == ["open", str(tmp_path.resolve())]
    assert called["check"] is True
