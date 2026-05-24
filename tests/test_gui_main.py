def test_gui_main_invokes_launcher(monkeypatch):
    called = {"ok": False}

    def fake_launch_gui():
        called["ok"] = True

    monkeypatch.setattr("youtube_video_downloader.gui_main.launch_gui", fake_launch_gui)

    from youtube_video_downloader.gui_main import main

    main()

    assert called["ok"] is True

