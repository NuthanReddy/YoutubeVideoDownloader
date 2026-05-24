"""Tkinter GUI for browsing formats and downloading videos in parallel."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .config import DEFAULT_OUTPUT_DIR, DEFAULT_SUBTITLE_LANGUAGES
from .models import (
    DownloadRequest,
    DownloadResult,
    FormatInfo,
    ResolutionParseError,
    SubtitleLanguageError,
    normalize_resolution,
    normalize_subtitle_languages,
)
from .services.downloader import DownloadError, DownloadService


def _resolution_choice_from_format(item: FormatInfo) -> int | None:
    """Return a user-facing quality value for the resolution dropdown."""

    if item.note:
        match = re.search(r"(\d{3,5})p", str(item.note).lower())
        if match:
            return int(match.group(1))

    if item.height:
        return int(item.height)

    return None


def _open_path_in_file_manager(path: Path) -> None:
    """Open a file or folder in the OS file manager."""

    resolved = path.resolve()
    if sys.platform.startswith("win"):
        os.startfile(str(resolved))
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(resolved)], check=True)
        return
    subprocess.run(["xdg-open", str(resolved)], check=True)


class DownloaderGUI:
    """Desktop UI for managing YouTube downloads."""

    def __init__(self, root: tk.Tk, output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
        self.root = root
        self.root.title("YouTube Video Downloader")
        self.root.geometry("1120x760")

        self.service = DownloadService()
        self.output_dir_var = tk.StringVar(value=str(output_dir))
        self.url_var = tk.StringVar()
        self.resolution_var = tk.StringVar(value="best")
        self.subtitle_var = tk.StringVar(value=",".join(DEFAULT_SUBTITLE_LANGUAGES))
        self.workers_var = tk.IntVar(value=3)
        self.fragments_var = tk.IntVar(value=1)
        self.enable_subtitles_var = tk.BooleanVar(value=True)
        self.all_subtitles_var = tk.BooleanVar(value=False)
        self.auto_subtitles_var = tk.BooleanVar(value=True)
        self.embed_subtitles_var = tk.BooleanVar(value=True)
        self.expand_playlists_var = tk.BooleanVar(value=True)

        self._queue: Queue[tuple[str, Any]] = Queue()
        self._executor: ThreadPoolExecutor | None = None
        self._active_jobs = 0

        self._build_layout()
        self._set_controls_enabled(True)
        self.refresh_downloads_tree()
        self._schedule_queue_poll()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_layout(self) -> None:
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        controls = ttk.LabelFrame(main, text="Download", padding=10)
        controls.pack(fill=tk.X)

        ttk.Label(controls, text="Video URL").grid(row=0, column=0, sticky=tk.W)
        url_entry = ttk.Entry(controls, textvariable=self.url_var)
        url_entry.grid(row=0, column=1, columnspan=3, sticky=tk.EW, padx=(8, 8))
        ttk.Button(controls, text="Fetch Resolutions", command=self.fetch_resolutions).grid(
            row=0, column=4, sticky=tk.EW
        )

        ttk.Label(controls, text="Resolution").grid(row=1, column=0, sticky=tk.W, pady=(8, 0))
        self.resolution_box = ttk.Combobox(
            controls,
            textvariable=self.resolution_var,
            state="readonly",
            values=("best", "2160", "1440", "1080", "720", "480", "360"),
            width=12,
        )
        self.resolution_box.grid(row=1, column=1, sticky=tk.W, padx=(8, 0), pady=(8, 0))

        ttk.Label(controls, text="Workers").grid(row=1, column=2, sticky=tk.E, pady=(8, 0))
        self.worker_spin = ttk.Spinbox(
            controls,
            from_=1,
            to=10,
            textvariable=self.workers_var,
            width=6,
        )
        self.worker_spin.grid(row=1, column=3, sticky=tk.W, padx=(8, 8), pady=(8, 0))

        ttk.Label(controls, text="Fragments").grid(row=1, column=4, sticky=tk.E, pady=(8, 0))
        self.fragments_spin = ttk.Spinbox(
            controls,
            from_=1,
            to=16,
            textvariable=self.fragments_var,
            width=6,
        )
        self.fragments_spin.grid(row=1, column=5, sticky=tk.W, pady=(8, 0))

        ttk.Label(controls, text="Output Dir").grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        out_entry = ttk.Entry(controls, textvariable=self.output_dir_var)
        out_entry.grid(row=2, column=1, columnspan=3, sticky=tk.EW, padx=(8, 8), pady=(8, 0))
        ttk.Button(controls, text="Browse", command=self._choose_output_dir).grid(
            row=2,
            column=4,
            sticky=tk.EW,
            pady=(8, 0),
        )

        ttk.Label(controls, text="Subtitle Langs (comma-separated)").grid(
            row=3,
            column=0,
            sticky=tk.W,
            pady=(8, 0),
        )
        ttk.Entry(controls, textvariable=self.subtitle_var).grid(
            row=3,
            column=1,
            columnspan=5,
            sticky=tk.EW,
            padx=(8, 8),
            pady=(8, 0),
        )

        flags = ttk.Frame(controls)
        flags.grid(row=4, column=0, columnspan=6, sticky=tk.W, pady=(8, 0))
        ttk.Checkbutton(flags, text="Enable subtitles", variable=self.enable_subtitles_var).pack(side=tk.LEFT)
        ttk.Checkbutton(flags, text="All subtitles", variable=self.all_subtitles_var).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(flags, text="Auto subtitles", variable=self.auto_subtitles_var).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(flags, text="Embed subtitles", variable=self.embed_subtitles_var).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(flags, text="Expand playlists", variable=self.expand_playlists_var).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(controls, text="One URL per line for parallel queue").grid(
            row=5,
            column=0,
            sticky=tk.NW,
            pady=(8, 0),
        )
        self.urls_text = scrolledtext.ScrolledText(controls, height=5)
        self.urls_text.grid(row=5, column=1, columnspan=5, sticky=tk.EW, pady=(8, 0))

        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(2, weight=0)
        controls.columnconfigure(3, weight=0)
        controls.columnconfigure(4, weight=0)
        controls.columnconfigure(5, weight=0)

        actions = ttk.Frame(main)
        actions.pack(fill=tk.X, pady=(10, 0))
        self.download_button = ttk.Button(actions, text="Start Download", command=self.start_downloads)
        self.download_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(actions, text="Stop Queue", command=self.stop_queue, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        self.status_label = ttk.Label(actions, text="Idle")
        self.status_label.pack(side=tk.LEFT, padx=(12, 0))

        split = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        split.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        library_frame = ttk.LabelFrame(split, text="Downloaded Videos", padding=8)
        split.add(library_frame, weight=1)

        self.downloads_tree = ttk.Treeview(library_frame, columns=("kind",), show="tree headings")
        self.downloads_tree.heading("#0", text="Name")
        self.downloads_tree.heading("kind", text="Type")
        self.downloads_tree.column("#0", width=360, stretch=True)
        self.downloads_tree.column("kind", width=120, stretch=False)
        self.downloads_tree.pack(fill=tk.BOTH, expand=True)

        library_actions = ttk.Frame(library_frame)
        library_actions.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(library_actions, text="Refresh", command=self.refresh_downloads_tree).pack(side=tk.LEFT)
        ttk.Button(
            library_actions,
            text="Open Downloads Folder",
            command=self.open_downloads_folder,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(library_actions, text="Open Selected", command=self.open_selected).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(library_actions, text="Delete Selected", command=self.delete_selected).pack(side=tk.LEFT, padx=(8, 0))

        logs_frame = ttk.LabelFrame(split, text="Activity", padding=8)
        split.add(logs_frame, weight=1)

        self.log_text = scrolledtext.ScrolledText(logs_frame, state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(DEFAULT_OUTPUT_DIR))
        if selected:
            self.output_dir_var.set(selected)
            self.refresh_downloads_tree()

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self.download_button.configure(state=state)
        self.stop_button.configure(state=(tk.NORMAL if not enabled else tk.DISABLED))

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _schedule_queue_poll(self) -> None:
        self.root.after(100, self._process_queue)

    def _process_queue(self) -> None:
        while True:
            try:
                message_type, payload = self._queue.get_nowait()
            except Empty:
                break

            if message_type == "log":
                self._append_log(str(payload))
            elif message_type == "resolutions":
                self._apply_resolutions(payload)
            elif message_type == "task_done":
                self._active_jobs = max(0, self._active_jobs - 1)
                success, label = payload
                self._append_log(label)
                self.status_label.configure(text=f"Running: {self._active_jobs}")
                if success:
                    self.refresh_downloads_tree()
                if self._active_jobs == 0:
                    self._set_controls_enabled(True)
                    self.status_label.configure(text="Idle")
            elif message_type == "task_failed":
                self._active_jobs = max(0, self._active_jobs - 1)
                self._append_log(payload)
                self.status_label.configure(text=f"Running: {self._active_jobs}")
                if self._active_jobs == 0:
                    self._set_controls_enabled(True)
                    self.status_label.configure(text="Idle")

        self._schedule_queue_poll()

    def _apply_resolutions(self, values: list[str]) -> None:
        if not values:
            messagebox.showinfo("Resolutions", "No video resolutions found.")
            return
        ordered = ["best", *values]
        self.resolution_box.configure(values=ordered)
        self.resolution_var.set(ordered[0])
        self._append_log(f"Loaded resolutions: {', '.join(ordered)}")

    def fetch_resolutions(self) -> None:
        url = self.url_var.get().strip() or self._first_url_from_queue()
        if not url:
            messagebox.showerror("Missing URL", "Provide a URL or paste URLs in the queue box.")
            return

        self._append_log(f"Fetching available resolutions for: {url}")

        def worker() -> None:
            try:
                formats = self.service.list_formats(url)
                heights = sorted(
                    {
                        str(value)
                        for item in formats
                        for value in [_resolution_choice_from_format(item)]
                        if value is not None and item.vcodec and item.vcodec != "none"
                    },
                    key=int,
                    reverse=True,
                )
                self._queue.put(("resolutions", heights))
            except Exception as exc:
                self._queue.put(("log", f"Could not load resolutions: {exc}"))

        ThreadPoolExecutor(max_workers=1).submit(worker)

    def _first_url_from_queue(self) -> str:
        for line in self.urls_text.get("1.0", tk.END).splitlines():
            value = line.strip()
            if value:
                return value
        return ""

    def _collect_urls(self) -> list[str]:
        values = [self.url_var.get().strip()]
        values.extend(line.strip() for line in self.urls_text.get("1.0", tk.END).splitlines())
        unique: list[str] = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique

    def _expand_playlist_urls(self, urls: list[str]) -> list[str]:
        if not self.expand_playlists_var.get():
            return urls

        expanded: list[str] = []
        for candidate in urls:
            try:
                playlist_urls = self.service.list_playlist_video_urls(candidate)
            except DownloadError as exc:
                self._append_log(f"Playlist expansion failed for {candidate}: {exc}")
                expanded.append(candidate)
                continue

            if len(playlist_urls) > 1:
                self._append_log(
                    f"Expanded playlist URL into {len(playlist_urls)} videos: {candidate}"
                )
            expanded.extend(playlist_urls)

        return list(dict.fromkeys(expanded))

    def _build_request(self, url: str) -> DownloadRequest:
        resolution = normalize_resolution(self.resolution_var.get().strip())
        concurrent_fragments = max(1, int(self.fragments_var.get()))
        language_input = [self.subtitle_var.get()]
        languages = normalize_subtitle_languages(
            language_input,
            all_languages=self.all_subtitles_var.get(),
        )
        return DownloadRequest(
            url=url,
            output_dir=Path(self.output_dir_var.get()),
            resolution=resolution,
            subtitle_languages=languages,
            download_subtitles=self.enable_subtitles_var.get(),
            auto_subtitles=self.auto_subtitles_var.get(),
            embed_subtitles=self.embed_subtitles_var.get(),
            concurrent_fragments=concurrent_fragments,
        )

    def start_downloads(self) -> None:
        urls = self._collect_urls()
        if not urls:
            messagebox.showerror("Missing URLs", "Provide at least one URL to download.")
            return

        urls = self._expand_playlist_urls(urls)

        try:
            workers = max(1, int(self.workers_var.get()))
            for url in urls:
                self._build_request(url)
        except (ValueError, ResolutionParseError, SubtitleLanguageError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self.stop_queue()
        self._executor = ThreadPoolExecutor(max_workers=workers)
        self._active_jobs = len(urls)
        self._set_controls_enabled(False)
        self.status_label.configure(text=f"Running: {self._active_jobs}")

        for url in urls:
            request = self._build_request(url)
            self._executor.submit(self._download_job, request)

        self._append_log(f"Queued {len(urls)} download(s) with {workers} worker(s).")

    def _download_job(self, request: DownloadRequest) -> None:
        try:
            result = self.service.download(request)
            label = self._format_result_label(result)
            self._queue.put(("task_done", (True, label)))
        except DownloadError as exc:
            self._queue.put(("task_failed", f"Download failed for {request.url}: {exc}"))
        except Exception as exc:
            self._queue.put(("task_failed", f"Unexpected error for {request.url}: {exc}"))

    @staticmethod
    def _format_result_label(result: DownloadResult) -> str:
        title = result.title or result.video_id or "video"
        saved = str(result.output_path) if result.output_path else "(unknown path)"
        return f"Downloaded: {title} -> {saved}"

    def stop_queue(self) -> None:
        if self._executor is None:
            return
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._executor = None
        self._active_jobs = 0
        self.status_label.configure(text="Idle")
        self._set_controls_enabled(True)
        self._append_log("Stopped active queue.")

    def refresh_downloads_tree(self) -> None:
        self.downloads_tree.delete(*self.downloads_tree.get_children())
        root = Path(self.output_dir_var.get())
        if not root.exists():
            return

        for folder in sorted(path for path in root.iterdir() if path.is_dir()):
            folder_id = str(folder)
            self.downloads_tree.insert("", tk.END, iid=folder_id, text=folder.name, values=("folder",))
            files = sorted(path for path in folder.iterdir() if path.is_file())
            for child in files:
                self.downloads_tree.insert(
                    folder_id,
                    tk.END,
                    iid=str(child),
                    text=child.name,
                    values=(child.suffix.lstrip(".") or "file",),
                )

    def _selected_path(self) -> Path | None:
        selected = self.downloads_tree.selection()
        if not selected:
            return None
        return Path(selected[0])

    def open_selected(self) -> None:
        selected = self._selected_path()
        if not selected or not selected.exists():
            messagebox.showinfo("Open", "Select an existing downloaded item.")
            return
        _open_path_in_file_manager(selected)

    def open_downloads_folder(self) -> None:
        root = Path(self.output_dir_var.get())
        root.mkdir(parents=True, exist_ok=True)
        _open_path_in_file_manager(root)

    def delete_selected(self) -> None:
        selected = self._selected_path()
        if not selected or not selected.exists():
            messagebox.showinfo("Delete", "Select an existing downloaded item.")
            return

        target = selected if selected.is_dir() else selected.parent
        if not messagebox.askyesno("Delete", f"Delete '{target.name}'?"):
            return

        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
        self.refresh_downloads_tree()
        self._append_log(f"Deleted: {target}")

    def _on_close(self) -> None:
        self.stop_queue()
        self.root.destroy()


def launch_gui(output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    root = tk.Tk()
    DownloaderGUI(root, output_dir=output_dir)
    root.mainloop()
