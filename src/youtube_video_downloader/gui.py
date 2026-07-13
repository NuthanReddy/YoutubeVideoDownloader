"""Tkinter GUI for browsing formats and downloading videos in parallel."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .config import (
    DEFAULT_FILENAME_TEMPLATE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SUBTITLE_LANGUAGES,
    PLAYLIST_ITEM_FILENAME_TEMPLATE,
)
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

try:  # Used to abort in-flight yt-dlp downloads when the queue is stopped.
    from yt_dlp.utils import DownloadCancelled as _DownloadCancelled
except Exception:  # pragma: no cover - fallback if yt-dlp internals change
    class _DownloadCancelled(Exception):
        """Fallback cancellation error when yt-dlp's is unavailable."""


APP_USER_MODEL_ID = "NuthanReddy.YoutubeVideoDownloader"
_INVALID_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _set_windows_app_id() -> None:
    """Register a distinct AppUserModelID so Windows' taskbar shows our icon.

    Without this, apps launched through ``pythonw.exe`` are grouped under the
    Python host and display the generic Python icon on the taskbar.
    """

    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
            APP_USER_MODEL_ID
        )
    except Exception:  # pragma: no cover - best effort, non-fatal
        pass


def _safe_folder_name(name: str) -> str:
    """Sanitize a playlist name into a filesystem-safe folder name."""

    cleaned = _INVALID_FS_CHARS.sub("_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(". ")
    return cleaned[:120].strip() or "Playlist"


def _resolution_choice_from_format(item: FormatInfo) -> int | None:
    """Return a user-facing quality value for the resolution dropdown."""

    if item.note:
        match = re.search(r"(\d{3,5})p", str(item.note).lower())
        if match:
            return int(match.group(1))

    if item.height:
        return int(item.height)

    return None


def _windows_short_path(target: str) -> str | None:
    """Return the 8.3 short path (ASCII, well under MAX_PATH) for a Windows path.

    Long (>260 char) or Unicode-heavy paths break some default players such as
    VLC, whose ``file://`` MRL handling isn't long-path aware. The short path is
    plain ASCII and short, so handing it to the shell opens reliably. Requires
    the path to exist and 8.3 name creation to be enabled on the volume.
    """

    try:
        import ctypes
        from ctypes import wintypes

        get_short = ctypes.windll.kernel32.GetShortPathNameW
        get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(len(target) + 260)
        if get_short(target, buffer, len(buffer)) and buffer.value:
            if os.path.exists(buffer.value):
                return buffer.value
    except Exception:
        return None
    return None


def _open_path_in_file_manager(path: Path) -> None:
    """Open a file (default app) or folder (file manager) via the OS shell."""

    resolved = path.resolve()
    target = str(resolved)
    if sys.platform.startswith("win"):
        # Prefer the 8.3 short path for long / non-ASCII paths so players like
        # VLC (which choke on >260-char or percent-encoded Unicode MRLs) open.
        if len(target) >= 240 or not target.isascii():
            short = _windows_short_path(target)
            if short:
                target = short
        os.startfile(target)  # noqa: S606 - trusted, locally-derived path
        return
    if sys.platform == "darwin":
        subprocess.run(["open", target], check=True)
        return
    subprocess.run(["xdg-open", target], check=True)


def _resource_path(relative_path: str) -> Path:
    """Resolve resource path for source and PyInstaller onefile modes."""

    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2] / relative_path


def _format_bytes(num_bytes: float | None) -> str:
    """Human-readable byte size."""

    if not num_bytes or num_bytes <= 0:
        return "0 B"
    value = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TiB"


def _format_eta(seconds: float | None) -> str:
    """Format an ETA in seconds as M:SS or H:MM:SS."""

    if seconds is None or seconds < 0:
        return "--:--"
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _format_progress_detail(
    percent: float | None,
    downloaded: float | None,
    total: float | None,
    speed: float | None,
    eta: float | None,
) -> str:
    """Build the per-download status detail string."""

    parts: list[str] = []
    if percent is not None:
        parts.append(f"{percent:.0f}%")
    if total:
        parts.append(f"{_format_bytes(downloaded)} / {_format_bytes(total)}")
    elif downloaded:
        parts.append(_format_bytes(downloaded))
    if speed:
        parts.append(f"{_format_bytes(speed)}/s")
    if eta is not None:
        parts.append(f"ETA {_format_eta(eta)}")
    return "  •  ".join(parts)


class DownloaderGUI:
    """Desktop UI for managing YouTube downloads."""

    _PALETTE = {
        "bg": "#141414",          # window background (near-black)
        "surface": "#1e1e1e",     # frames / buttons
        "surface_hi": "#2c2c2c",  # hover
        "field": "#242424",       # entry / text field background
        "border": "#333333",
        "fg": "#ececec",          # primary text
        "muted": "#8a8f98",       # secondary text
        "accent": "#ff3b30",      # primary action / progress (YouTube-ish red)
        "accent_hi": "#ff5b52",
        "ok": "#3ddc84",
        "warn": "#f5b544",
        "danger": "#ff5c5c",
    }

    _URLS_HINT = "One URL per line for parallel queue"

    def __init__(
        self,
        root: tk.Tk,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
    ) -> None:
        _set_windows_app_id()
        self.root = root
        # Title text intentionally blank: the in-app header already shows the name,
        # so an empty caption avoids a duplicate title while keeping the native bar
        # (icon, min/max/close, dragging, snap, taskbar button) intact.
        self.root.title("")
        self.root.geometry("1120x780")
        self.root.minsize(940, 660)

        self.service = DownloadService()
        self.output_dir_var = tk.StringVar(value=str(Path(output_dir).resolve()))
        self.url_var = tk.StringVar()
        self.resolution_var = tk.StringVar(value="best")
        self.subtitle_var = tk.StringVar(value=",".join(DEFAULT_SUBTITLE_LANGUAGES))
        self.workers_var = tk.IntVar(value=3)
        self.enable_subtitles_var = tk.BooleanVar(value=True)
        self.all_subtitles_var = tk.BooleanVar(value=False)
        self.auto_subtitles_var = tk.BooleanVar(value=True)
        self.embed_subtitles_var = tk.BooleanVar(value=True)
        self.expand_playlists_var = tk.BooleanVar(value=True)
        self.url_mode_var = tk.StringVar(value="single")
        self._urls_hint_active = False

        self._queue: Queue[tuple[str, Any]] = Queue()
        self._executor: ThreadPoolExecutor | None = None
        self._inflight: set[str] = set()
        self._paused_jobs: dict[str, DownloadRequest] = {}
        self._download_rows: dict[str, dict[str, Any]] = {}
        self._job_counter = 0
        self._stop_event = threading.Event()
        self._progress_throttle: dict[str, tuple[int, float]] = {}

        self._apply_theme()
        self._build_layout()
        self._apply_app_icon()
        self._apply_dark_titlebar()
        self._refresh_controls()
        self.refresh_downloads_tree()
        self._schedule_queue_poll()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_theme(self) -> None:
        """Apply a modern dark theme across ttk and classic Tk widgets."""

        p = self._PALETTE
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:  # pragma: no cover - platform dependent
            pass

        self.root.configure(bg=p["bg"])
        self.root.option_add("*TCombobox*Listbox.background", p["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        style.configure(
            ".",
            background=p["bg"],
            foreground=p["fg"],
            fieldbackground=p["field"],
            bordercolor=p["border"],
            lightcolor=p["border"],
            darkcolor=p["border"],
            troughcolor=p["surface"],
            focuscolor=p["accent"],
            insertcolor=p["fg"],
        )
        style.configure("TFrame", background=p["bg"])
        style.configure("Card.TFrame", background=p["surface"])
        style.configure("TLabel", background=p["bg"], foreground=p["fg"])
        style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
        style.configure(
            "Header.TLabel",
            background=p["bg"],
            foreground=p["fg"],
            font=("Segoe UI Semibold", 17),
        )
        style.configure(
            "SubHeader.TLabel", background=p["bg"], foreground=p["muted"], font=("Segoe UI", 10)
        )
        style.configure("Detail.TLabel", background=p["bg"], foreground=p["muted"])
        style.configure("RowState.TLabel", background=p["bg"], foreground=p["muted"])

        style.configure(
            "TLabelframe",
            background=p["bg"],
            bordercolor=p["border"],
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=p["bg"],
            foreground=p["muted"],
            font=("Segoe UI Semibold", 10),
        )
        style.configure(
            "Toggle.TLabel",
            background=p["bg"],
            foreground=p["muted"],
            font=("Segoe UI Semibold", 10),
        )

        style.configure(
            "TButton",
            background=p["surface"],
            foreground=p["fg"],
            bordercolor=p["border"],
            focusthickness=0,
            relief="flat",
            padding=(12, 6),
        )
        style.map(
            "TButton",
            background=[("active", p["surface_hi"]), ("disabled", p["surface"])],
            foreground=[("disabled", p["muted"])],
        )
        style.configure(
            "Accent.TButton",
            background=p["accent"],
            foreground="#ffffff",
            padding=(16, 7),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Accent.TButton",
            background=[("active", p["accent_hi"]), ("disabled", p["surface"])],
            foreground=[("disabled", p["muted"]), ("!disabled", "#ffffff")],
        )

        # Segmented Single/Batch toggle.
        style.configure(
            "Toolbutton",
            background=p["surface"],
            foreground=p["muted"],
            bordercolor=p["border"],
            relief="flat",
            padding=(14, 5),
            font=("Segoe UI", 9),
        )
        style.map(
            "Toolbutton",
            background=[("selected", p["accent"]), ("active", p["surface_hi"])],
            foreground=[("selected", "#ffffff"), ("active", p["fg"])],
        )

        for widget in ("TEntry", "TCombobox", "TSpinbox"):
            style.configure(
                widget,
                fieldbackground=p["field"],
                foreground=p["fg"],
                bordercolor=p["border"],
                arrowcolor=p["fg"],
                insertcolor=p["fg"],
                padding=5,
            )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", p["field"])],
            foreground=[("readonly", p["fg"])],
            arrowcolor=[("active", p["accent"])],
        )
        style.map("TSpinbox", arrowcolor=[("active", p["accent"])])

        style.configure(
            "TCheckbutton",
            background=p["bg"],
            foreground=p["fg"],
            focuscolor=p["bg"],
            indicatorcolor=p["field"],
        )
        style.map(
            "TCheckbutton",
            background=[("active", p["bg"])],
            foreground=[("disabled", p["muted"])],
            indicatorcolor=[("selected", p["accent"]), ("!selected", p["field"])],
        )

        style.configure(
            "TProgressbar",
            background=p["accent"],
            troughcolor=p["surface"],
            bordercolor=p["surface"],
            lightcolor=p["accent"],
            darkcolor=p["accent"],
            thickness=10,
        )

        style.configure(
            "Treeview",
            background=p["field"],
            fieldbackground=p["field"],
            foreground=p["fg"],
            bordercolor=p["border"],
            rowheight=24,
        )
        style.map(
            "Treeview",
            background=[("selected", p["accent"])],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Treeview.Heading",
            background=p["surface"],
            foreground=p["muted"],
            relief="flat",
            padding=6,
        )
        style.map("Treeview.Heading", background=[("active", p["surface_hi"])])

        style.configure(
            "Vertical.TScrollbar",
            background=p["surface"],
            troughcolor=p["bg"],
            bordercolor=p["bg"],
            arrowcolor=p["muted"],
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=p["surface"],
            troughcolor=p["bg"],
            bordercolor=p["bg"],
            arrowcolor=p["muted"],
        )
        for orient in ("Vertical.TScrollbar", "Horizontal.TScrollbar"):
            style.map(orient, background=[("active", p["surface_hi"])])
        style.configure("TPanedwindow", background=p["bg"])
        style.configure("Sash", background=p["border"])

    def _apply_dark_titlebar(self) -> None:
        """Darken the native Windows title bar to match the app background.

        Uses DWM window attributes so the caption bar renders dark (Win10 2004+)
        and, where supported (Win11 22000+), is tinted to the exact background
        colour for a seamless look. Window controls and dragging are preserved.
        """

        if not sys.platform.startswith("win"):
            return
        try:
            from ctypes import byref, c_int, sizeof, windll
        except Exception:  # pragma: no cover - non-Windows / restricted env
            return

        try:
            self.root.update_idletasks()
            hwnd = windll.user32.GetParent(self.root.winfo_id())
        except Exception:  # pragma: no cover - platform dependent
            return

        def _set(attr: int, value: int) -> None:
            try:
                windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, byref(c_int(value)), sizeof(c_int)
                )
            except Exception:  # pragma: no cover - unsupported attribute
                pass

        def _colorref(hex_color: str) -> int:
            r = int(hex_color[1:3], 16)
            g = int(hex_color[3:5], 16)
            b = int(hex_color[5:7], 16)
            return (b << 16) | (g << 8) | r  # COLORREF = 0x00BBGGRR

        # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 on current builds, 19 on older ones.
        _set(20, 1)
        _set(19, 1)

        # Exact caption / text / border colours (Win11 22000+; no-ops elsewhere).
        p = self._PALETTE
        _set(35, _colorref(p["bg"]))     # DWMWA_CAPTION_COLOR
        _set(36, _colorref(p["fg"]))     # DWMWA_TEXT_COLOR
        _set(34, _colorref(p["bg"]))     # DWMWA_BORDER_COLOR

        # Nudge DWM to repaint the frame if the window is already mapped.
        try:
            if self.root.winfo_viewable():
                self.root.withdraw()
                self.root.deiconify()
        except Exception:  # pragma: no cover - platform dependent
            pass

    def _apply_app_icon(self) -> None:
        """Apply the app icon, preferring the .ico on Windows for the taskbar."""

        icon_ico = _resource_path("assets/app_icon.ico")
        icon_png = _resource_path("assets/app_icon.png")

        if sys.platform.startswith("win") and icon_ico.exists():
            try:
                self.root.iconbitmap(default=str(icon_ico))
                return
            except tk.TclError:
                pass

        if icon_png.exists():
            try:
                self._icon_image = tk.PhotoImage(file=str(icon_png))
                self.root.iconphoto(True, self._icon_image)
                return
            except tk.TclError:
                pass

        if icon_ico.exists():
            try:
                self.root.iconbitmap(default=str(icon_ico))
            except tk.TclError:
                pass

    def _style_text_widget(self, widget: tk.Text) -> None:
        """Recolor a classic Tk text widget to match the dark theme."""

        p = self._PALETTE
        widget.configure(
            background=p["field"],
            foreground=p["fg"],
            insertbackground=p["fg"],
            selectbackground=p["accent"],
            selectforeground="#ffffff",
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=p["border"],
            highlightcolor=p["border"],
            padx=8,
            pady=6,
            font=("Segoe UI", 10),
        )

    def _build_layout(self) -> None:
        p = self._PALETTE
        # padding = (left, top, right, bottom): drop the top gap so the header sits
        # flush under the (blank) title bar with no wasted space above it.
        main = ttk.Frame(self.root, padding=(14, 0, 14, 14))
        main.pack(fill=tk.BOTH, expand=True)

        # --- Header -----------------------------------------------------
        header = ttk.Frame(main)
        header.pack(fill=tk.X)
        ttk.Label(header, text="YouTube Video Downloader", style="Header.TLabel").pack(
            side=tk.LEFT
        )
        ttk.Label(
            header,
            text="Parallel downloads · playlists · subtitles",
            style="SubHeader.TLabel",
        ).pack(side=tk.LEFT, padx=(12, 0), pady=(6, 0))

        # --- Download card ---------------------------------------------
        controls = ttk.LabelFrame(main, text="Download", padding=12)
        controls.pack(fill=tk.X, pady=(12, 0))

        # URL row: label + input inline; Expand playlists + Single/Batch on the right.
        url_row = ttk.Frame(controls)
        url_row.pack(fill=tk.X)
        url_row.columnconfigure(1, weight=1)
        ttk.Label(url_row, text="URL", style="TLabel").grid(
            row=0, column=0, sticky=tk.NW, padx=(0, 8), pady=(4, 0)
        )

        # URL input container: single entry and batch box occupy the same cell.
        url_container = ttk.Frame(url_row)
        url_container.grid(row=0, column=1, sticky=tk.EW)
        url_container.columnconfigure(0, weight=1)

        self._url_single_frame = ttk.Frame(url_container)
        self._url_single_frame.grid(row=0, column=0, sticky=tk.EW)
        self.url_entry = ttk.Entry(self._url_single_frame, textvariable=self.url_var)
        self.url_entry.pack(fill=tk.X, expand=True)

        self._url_batch_frame = ttk.Frame(url_container)
        self._url_batch_frame.grid(row=0, column=0, sticky=tk.NSEW)
        self.urls_text = scrolledtext.ScrolledText(self._url_batch_frame, height=4)
        self._style_text_widget(self.urls_text)
        self.urls_text.pack(fill=tk.BOTH, expand=True)
        self.urls_text.bind("<FocusIn>", self._on_urls_focus_in)
        self.urls_text.bind("<FocusOut>", self._on_urls_focus_out)

        ttk.Checkbutton(
            url_row, text="Expand playlists", variable=self.expand_playlists_var
        ).grid(row=0, column=2, sticky=tk.NE, padx=(12, 0), pady=(3, 0))

        toggle = ttk.Frame(url_row)
        toggle.grid(row=0, column=3, sticky=tk.NE, padx=(12, 0))
        ttk.Radiobutton(
            toggle,
            text="Single",
            style="Toolbutton",
            value="single",
            variable=self.url_mode_var,
            command=self._on_url_mode_change,
        ).pack(side=tk.LEFT)
        ttk.Radiobutton(
            toggle,
            text="Batch",
            style="Toolbutton",
            value="batch",
            variable=self.url_mode_var,
            command=self._on_url_mode_change,
        ).pack(side=tk.LEFT)

        # Options row: resolution (+ its fetcher), concurrency, and subtitles.
        opts = ttk.Frame(controls)
        opts.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(opts, text="Resolution").pack(side=tk.LEFT)
        self.resolution_box = ttk.Combobox(
            opts,
            textvariable=self.resolution_var,
            state="readonly",
            values=("best", "2160", "1440", "1080", "720", "480", "360"),
            width=9,
        )
        self.resolution_box.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            opts, text="Fetch Resolutions", command=self.fetch_resolutions
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(opts, text="Workers").pack(side=tk.LEFT, padx=(16, 0))
        self.worker_spin = ttk.Spinbox(
            opts, from_=1, to=10, textvariable=self.workers_var, width=4
        )
        self.worker_spin.pack(side=tk.LEFT, padx=(8, 0))
        # Subtitles: short language box + toggles, inline on the same options row.
        ttk.Label(opts, text="Subtitles").pack(side=tk.LEFT, padx=(16, 0))
        ttk.Entry(opts, textvariable=self.subtitle_var, width=14).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Checkbutton(opts, text="Enable", variable=self.enable_subtitles_var).pack(
            side=tk.LEFT, padx=(10, 0)
        )
        ttk.Checkbutton(opts, text="All", variable=self.all_subtitles_var).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Checkbutton(opts, text="Auto", variable=self.auto_subtitles_var).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Checkbutton(opts, text="Embed", variable=self.embed_subtitles_var).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        # Output directory row.
        out_row = ttk.Frame(controls)
        out_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(out_row, text="Output Dir", width=11, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Entry(out_row, textvariable=self.output_dir_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8)
        )
        ttk.Button(out_row, text="Browse", command=self._choose_output_dir).pack(
            side=tk.LEFT
        )

        # --- Actions ----------------------------------------------------
        actions = ttk.Frame(main)
        actions.pack(fill=tk.X, pady=(12, 0))
        self.download_button = ttk.Button(
            actions,
            text="Start Download",
            style="Accent.TButton",
            command=self.start_downloads,
        )
        self.download_button.pack(side=tk.LEFT)
        self.pause_button = ttk.Button(
            actions, text="Pause", command=self.pause_queue, state=tk.DISABLED
        )
        self.pause_button.pack(side=tk.LEFT, padx=(8, 0))
        self.resume_button = ttk.Button(
            actions, text="Resume All", command=self.resume_queue, state=tk.DISABLED
        )
        self.resume_button.pack(side=tk.LEFT, padx=(8, 0))
        self.status_label = ttk.Label(actions, text="Idle", style="Muted.TLabel")
        self.status_label.pack(side=tk.LEFT, padx=(14, 0))

        # --- Active Downloads | Downloaded Videos (resizable) ----------
        # Active Downloads sits on the LEFT and takes the majority of the
        # width plus all remaining vertical height; Downloaded Videos is a
        # narrower pane on the RIGHT. The sash between them is draggable.
        split = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        self._split = split

        progress_frame = ttk.LabelFrame(split, text="Active Downloads", padding=8)
        split.add(progress_frame, weight=3)

        progress_canvas = tk.Canvas(
            progress_frame,
            height=220,
            highlightthickness=0,
            borderwidth=0,
            background=p["bg"],
        )
        progress_scroll = ttk.Scrollbar(
            progress_frame, orient=tk.VERTICAL, command=progress_canvas.yview
        )
        self._progress_inner = ttk.Frame(progress_canvas)
        self._progress_window = progress_canvas.create_window(
            (0, 0), window=self._progress_inner, anchor="nw"
        )
        progress_canvas.configure(yscrollcommand=progress_scroll.set)
        progress_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        progress_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._progress_canvas = progress_canvas

        self._progress_inner.bind(
            "<Configure>",
            lambda _event: progress_canvas.configure(
                scrollregion=progress_canvas.bbox("all")
            ),
        )
        progress_canvas.bind(
            "<Configure>",
            lambda event: progress_canvas.itemconfigure(
                self._progress_window, width=event.width
            ),
        )
        self._progress_placeholder = ttk.Label(
            self._progress_inner, text="No active downloads.", style="Muted.TLabel"
        )
        self._progress_placeholder.pack(anchor=tk.W, padx=4, pady=4)

        for widget in (progress_canvas, self._progress_inner, self._progress_placeholder):
            self._bind_mousewheel(widget)

        library_frame = ttk.LabelFrame(split, text="Downloaded Videos", padding=8)
        split.add(library_frame, weight=2)

        # Pack the action bar at the bottom FIRST so it always reserves its
        # space; the tree then fills whatever height is left. Without this the
        # expanding tree pushes the buttons off-screen unless maximized.
        library_actions = ttk.Frame(library_frame)
        library_actions.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        ttk.Button(library_actions, text="Refresh", command=self.refresh_downloads_tree).pack(side=tk.LEFT)
        ttk.Button(
            library_actions,
            text="Open Folder",
            command=self.open_downloads_folder,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(library_actions, text="Open", command=self.open_selected).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(library_actions, text="Delete", command=self.delete_selected).pack(side=tk.LEFT, padx=(6, 0))

        self.downloads_tree = ttk.Treeview(library_frame, columns=("kind",), show="tree headings")
        self.downloads_tree.heading("#0", text="Name")
        self.downloads_tree.heading("kind", text="Type")
        self.downloads_tree.column("#0", width=240, stretch=True)
        self.downloads_tree.column("kind", width=70, stretch=False, anchor=tk.CENTER)
        self.downloads_tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # Double-click opens the item (file -> default player, folder -> Explorer).
        self.downloads_tree.bind("<Double-1>", self._on_downloads_double_click)

        # --- Activity (collapsible, docked at the very bottom) ---------
        # Collapsed by default: only a clickable header shows; the log body is
        # packed in on demand so it never steals vertical space from the two
        # panes above until the user actually wants to read it.
        activity = ttk.Frame(main)
        activity.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        self._activity_expanded = False
        self._activity_toggle = ttk.Label(
            activity, text="\u25b8  Activity", style="Toggle.TLabel", cursor="hand2"
        )
        self._activity_toggle.pack(anchor=tk.W)
        self._activity_toggle.bind("<Button-1>", lambda _event: self._toggle_activity())
        self._activity_body = ttk.Frame(activity)
        self.log_text = scrolledtext.ScrolledText(
            self._activity_body, height=8, state=tk.DISABLED
        )
        self._style_text_widget(self.log_text)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        # Pack the split LAST so it fills the space between the action bar
        # above and the collapsible Activity strip docked at the bottom.
        split.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        # Bias the initial sash so Active Downloads gets the majority of the
        # width; the user can still drag it. Deferred until the pane is mapped
        # so winfo_width reports the real geometry.
        split.bind("<Map>", self._init_sash_once)

        # Initialise URL mode + batch placeholder hint.
        self._show_urls_hint()
        self._on_url_mode_change()

    def _toggle_activity(self) -> None:
        """Expand/collapse the docked Activity log strip."""
        self._activity_expanded = not self._activity_expanded
        if self._activity_expanded:
            self._activity_body.pack(fill=tk.BOTH, expand=True)
            self._activity_toggle.configure(text="\u25be  Activity")
        else:
            self._activity_body.pack_forget()
            self._activity_toggle.configure(text="\u25b8  Activity")

    def _init_sash_once(self, _event: object = None) -> None:
        """One-shot: place the sash so Active Downloads takes ~62% of width."""
        self._split.unbind("<Map>")

        def _apply() -> None:
            try:
                width = self._split.winfo_width()
                if width > 1:
                    self._split.sashpos(0, int(width * 0.62))
            except tk.TclError:  # pragma: no cover - teardown races
                pass

        self._split.after(60, _apply)

    # --- URL mode + batch placeholder ----------------------------------
    def _on_url_mode_change(self) -> None:
        if self.url_mode_var.get() == "batch":
            self._url_single_frame.grid_remove()
            self._url_batch_frame.grid()
        else:
            self._url_batch_frame.grid_remove()
            self._url_single_frame.grid()

    def _show_urls_hint(self) -> None:
        """Show the greyed placeholder hint when the batch box is empty."""

        if self.urls_text.get("1.0", tk.END).strip():
            return
        self.urls_text.tag_configure("hint", foreground=self._PALETTE["muted"])
        self.urls_text.delete("1.0", tk.END)
        self.urls_text.insert("1.0", self._URLS_HINT, "hint")
        self._urls_hint_active = True

    def _clear_urls_hint(self) -> None:
        if self._urls_hint_active:
            self.urls_text.delete("1.0", tk.END)
            self._urls_hint_active = False

    def _on_urls_focus_in(self, _event: "tk.Event[Any]") -> None:
        self._clear_urls_hint()

    def _on_urls_focus_out(self, _event: "tk.Event[Any]") -> None:
        self._show_urls_hint()

    def _choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(DEFAULT_OUTPUT_DIR))
        if selected:
            self.output_dir_var.set(selected)
            self.refresh_downloads_tree()

    def _refresh_controls(self) -> None:
        """Sync the Start / Pause / Resume-All buttons and the status label to the
        live counts. Pause is active whenever something is running and Resume All
        whenever something is paused, so a mixed state lights up both. Start is
        only disabled while downloads are actually in flight."""

        running = len(self._inflight)
        paused = len(self._paused_jobs)
        self.download_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.pause_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        self.resume_button.configure(state=tk.NORMAL if paused else tk.DISABLED)
        if running and paused:
            self.status_label.configure(
                text=f"Running: {running} \u00b7 Paused: {paused}"
            )
        elif running:
            self.status_label.configure(text=f"Running: {running}")
        elif paused:
            self.status_label.configure(text=f"Paused: {paused}")
        else:
            self.status_label.configure(text="Idle")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _next_job_id(self) -> str:
        self._job_counter += 1
        return f"job-{self._job_counter}"

    def _update_progress_placeholder(self) -> None:
        if self._download_rows:
            self._progress_placeholder.pack_forget()
        else:
            self._progress_placeholder.pack(anchor=tk.W, padx=4, pady=4)

    def _clear_download_rows(self) -> None:
        for row in self._download_rows.values():
            row["frame"].destroy()
        self._download_rows.clear()
        self._progress_throttle.clear()
        self._update_progress_placeholder()

    def _on_progress_mousewheel(self, event: "tk.Event[Any]") -> str | None:
        canvas = getattr(self, "_progress_canvas", None)
        if canvas is None:
            return None
        first, last = canvas.yview()
        if first <= 0.0 and last >= 1.0:
            return None  # content fits; nothing to scroll
        num = getattr(event, "num", None)
        if num == 4:  # Linux wheel up
            canvas.yview_scroll(-1, "units")
        elif num == 5:  # Linux wheel down
            canvas.yview_scroll(1, "units")
        elif event.delta:  # Windows / macOS
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _bind_mousewheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_progress_mousewheel)
        widget.bind("<Button-4>", self._on_progress_mousewheel)
        widget.bind("<Button-5>", self._on_progress_mousewheel)

    def _create_download_row(
        self, job_id: str, label: str, request: DownloadRequest | None = None
    ) -> None:
        row_frame = ttk.Frame(self._progress_inner, padding=(4, 4))
        row_frame.pack(fill=tk.X, expand=True)

        header = ttk.Frame(row_frame)
        header.pack(fill=tk.X)
        title_label = ttk.Label(header, text="Preparing\u2026", anchor=tk.W)
        title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        state_label = ttk.Label(
            header, text="Queued", anchor=tk.E, width=12, style="RowState.TLabel"
        )
        state_label.pack(side=tk.RIGHT)

        bar = ttk.Progressbar(
            row_frame, orient=tk.HORIZONTAL, mode="determinate", maximum=100
        )
        bar.pack(fill=tk.X, pady=(2, 0))

        detail_label = ttk.Label(row_frame, text="", anchor=tk.W, style="Detail.TLabel")
        detail_label.pack(fill=tk.X)

        for widget in (row_frame, header, title_label, state_label, bar, detail_label):
            self._bind_mousewheel(widget)

        self._download_rows[job_id] = {
            "frame": row_frame,
            "header": header,
            "title": title_label,
            "state": state_label,
            "detail": detail_label,
            "bar": bar,
            "done": False,
            "url": label,
            "has_title": False,
            "request": request,
            "retry": None,
            "attempt": 0,
        }
        self._update_progress_placeholder()

    def _update_download_row(self, job_id: str, info: dict[str, Any]) -> None:
        row = self._download_rows.get(job_id)
        if row is None or row["done"]:
            return

        title = info.get("title")
        if title:
            row["has_title"] = True
            if row["title"].cget("text") != title:
                row["title"].configure(text=title)

        percent = info.get("percent")
        if percent is not None:
            row["bar"]["value"] = max(0.0, min(100.0, float(percent)))

        state = info.get("status", "downloading")
        state_text = {"downloading": "Downloading", "processing": "Finishing"}.get(
            state, state.title()
        )
        row["state"].configure(text=state_text)
        row["detail"].configure(text=info.get("detail") or "")

    def _finalize_download_row(
        self, job_id: str, state: str, title: str | None = None
    ) -> None:
        row = self._download_rows.get(job_id)
        if row is None or row["done"]:
            return
        row["done"] = True
        # Prefer the title resolved from the download result. Already-downloaded
        # items fire no progress hook, so finalize is the only place the real
        # name arrives — without this the row stays stuck on "Preparing…".
        if title:
            row["has_title"] = True
            if row["title"].cget("text") != title:
                row["title"].configure(text=title)
        # Never revert a resolved title back to the raw URL. Only surface the URL
        # when we never learned a title (e.g. a failure before any metadata).
        if not row["has_title"] and state != "done":
            row["title"].configure(text=row["url"])
        if state == "done":
            row["bar"]["value"] = 100
            row["state"].configure(text="\u2713 Done")
            row["detail"].configure(text="Completed")
        elif state == "stopped":
            row["state"].configure(text="\u25a0 Stopped")
        else:
            row["state"].configure(text="\u2717 Failed")
            self._add_retry_button(job_id)

    def _add_retry_button(self, job_id: str) -> None:
        """Add a Retry button to a failed row so it can be re-queued."""

        row = self._download_rows.get(job_id)
        if row is None or row.get("request") is None:
            return
        existing = row.get("retry")
        if existing is not None:
            existing.destroy()
        retry_btn = ttk.Button(
            row["header"],
            text="Retry",
            width=7,
            command=lambda: self._retry_job(job_id),
        )
        retry_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self._bind_mousewheel(retry_btn)
        row["retry"] = retry_btn

    def _requeue_row(self, job_id: str, verb: str) -> None:
        """Shared Retry/Resume logic: re-submit a row's request. yt-dlp continues
        from the existing .part file, so it resumes rather than restarting."""

        row = self._download_rows.get(job_id)
        if row is None or row.get("request") is None:
            return

        # Requeuing this row removes it from the paused set; any other paused
        # rows stay paused and keep the Resume-All button live.
        self._paused_jobs.pop(job_id, None)
        self._stop_event.clear()

        button = row.get("retry")
        if button is not None:
            button.destroy()
            row["retry"] = None

        row["done"] = False
        row["bar"]["value"] = 0
        row["state"].configure(text="Queued")
        row["detail"].configure(text="")

        self._submit_job(job_id, row["request"])
        self._refresh_controls()
        self._append_log(f"{verb}: {row['request'].url}")

    def _retry_job(self, job_id: str) -> None:
        """Re-queue a previously failed download."""

        self._requeue_row(job_id, "Retrying")

    def _resume_job(self, job_id: str) -> None:
        """Resume a single paused download from its .part file."""

        self._requeue_row(job_id, "Resuming")

    def _make_progress_hook(
        self, job_id: str, attempt: int
    ) -> Callable[[dict[str, Any]], None]:
        def hook(status_dict: dict[str, Any]) -> None:
            if self._stop_event.is_set():
                raise _DownloadCancelled()

            status = status_dict.get("status")
            info_dict = status_dict.get("info_dict") or {}
            title = info_dict.get("title")

            if status == "downloading":
                total = status_dict.get("total_bytes") or status_dict.get(
                    "total_bytes_estimate"
                )
                downloaded = status_dict.get("downloaded_bytes") or 0
                percent = (downloaded / total * 100) if total else None
                speed = status_dict.get("speed")
                eta = status_dict.get("eta")

                percent_key = int(percent) if percent is not None else -1
                now = time.monotonic()
                last = self._progress_throttle.get(job_id)
                if last is not None and last[0] == percent_key and now - last[1] < 0.2:
                    return
                self._progress_throttle[job_id] = (percent_key, now)

                detail = _format_progress_detail(percent, downloaded, total, speed, eta)
                self._queue.put(
                    (
                        "progress",
                        (
                            job_id,
                            attempt,
                            {
                                "percent": percent,
                                "status": "downloading",
                                "title": title,
                                "detail": detail,
                            },
                        ),
                    )
                )
            elif status == "finished":
                self._queue.put(
                    (
                        "progress",
                        (
                            job_id,
                            attempt,
                            {
                                "percent": 100.0,
                                "status": "processing",
                                "title": title,
                                "detail": "merging / post-processing",
                            },
                        ),
                    )
                )

        return hook

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
            elif message_type == "progress":
                job_id, attempt, info = payload
                if self._is_current_attempt(job_id, attempt):
                    self._update_download_row(job_id, info)
            elif message_type == "task_done":
                job_id, attempt, success, label, title = payload
                if not self._is_current_attempt(job_id, attempt):
                    continue
                self._finalize_download_row(
                    job_id, "done" if success else "failed", title
                )
                self._append_log(label)
                if success:
                    self.refresh_downloads_tree()
                self._settle_job(job_id)
            elif message_type in ("task_failed", "task_stopped"):
                job_id, attempt, message = payload
                if not self._is_current_attempt(job_id, attempt):
                    continue
                self._finalize_download_row(
                    job_id, "stopped" if message_type == "task_stopped" else "failed"
                )
                self._append_log(message)
                self._settle_job(job_id)

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
        if self._urls_hint_active:
            return ""
        for line in self.urls_text.get("1.0", tk.END).splitlines():
            value = line.strip()
            if value:
                return value
        return ""

    def _collect_urls(self) -> list[str]:
        values: list[str] = []
        if self.url_mode_var.get() == "single":
            single = self.url_var.get().strip()
            if single:
                values.append(single)
        elif not self._urls_hint_active:
            values.extend(
                line.strip() for line in self.urls_text.get("1.0", tk.END).splitlines()
            )
        unique: list[str] = []
        for value in values:
            if value and value not in unique:
                unique.append(value)
        return unique

    def _expand_playlist_urls(self, urls: list[str]) -> list[tuple[str, str | None]]:
        """Expand playlist URLs into ``(video_url, playlist_name)`` pairs.

        ``playlist_name`` is set only for genuine multi-video playlists so the
        downloader can group those videos under a folder.
        """

        if not self.expand_playlists_var.get():
            return [(url, None) for url in urls]

        expanded: list[tuple[str, str | None]] = []
        for candidate in urls:
            try:
                playlist_name, playlist_urls = self.service.expand_playlist(
                    candidate
                )
            except DownloadError as exc:
                self._append_log(f"Playlist expansion failed for {candidate}: {exc}")
                expanded.append((candidate, None))
                continue

            if len(playlist_urls) > 1:
                self._append_log(
                    f"Expanded playlist into {len(playlist_urls)} videos: {candidate}"
                )
                for video_url in playlist_urls:
                    expanded.append((video_url, playlist_name))
            elif playlist_urls:
                expanded.append((playlist_urls[0], None))
            else:
                expanded.append((candidate, None))

        # Dedupe by URL while keeping the first (playlist-associated) entry.
        seen: set[str] = set()
        result: list[tuple[str, str | None]] = []
        for video_url, name in expanded:
            if video_url in seen:
                continue
            seen.add(video_url)
            result.append((video_url, name))
        return result

    def _build_request(
        self, url: str, playlist_name: str | None = None
    ) -> DownloadRequest:
        resolution = normalize_resolution(self.resolution_var.get().strip())
        language_input = [self.subtitle_var.get()]
        languages = normalize_subtitle_languages(
            language_input,
            all_languages=self.all_subtitles_var.get(),
        )
        base_dir = Path(self.output_dir_var.get())
        if playlist_name:
            output_dir = base_dir / _safe_folder_name(playlist_name)
            output_template = PLAYLIST_ITEM_FILENAME_TEMPLATE
        else:
            output_dir = base_dir
            output_template = DEFAULT_FILENAME_TEMPLATE
        return DownloadRequest(
            url=url,
            output_dir=output_dir,
            output_template=output_template,
            resolution=resolution,
            subtitle_languages=languages,
            download_subtitles=self.enable_subtitles_var.get(),
            auto_subtitles=self.auto_subtitles_var.get(),
            embed_subtitles=self.embed_subtitles_var.get(),
        )

    def _halt_executor(self) -> None:
        """Cancel in-flight and queued jobs. .part files are preserved so a later
        Resume/Retry continues instead of restarting from the beginning."""

        if self._executor is not None:
            self._stop_event.set()
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def _submit_job(self, job_id: str, request: DownloadRequest) -> None:
        """Submit (or re-submit) a row's download, tagging it with a fresh attempt
        token so stale messages from a previous invocation are ignored."""

        row = self._download_rows.get(job_id)
        if row is None:
            return
        if self._executor is None:
            workers = max(1, int(self.workers_var.get()))
            self._executor = ThreadPoolExecutor(max_workers=workers)
        attempt = int(row.get("attempt", 0)) + 1
        row["attempt"] = attempt
        row["done"] = False
        self._progress_throttle.pop(job_id, None)
        self._inflight.add(job_id)
        self._executor.submit(self._download_job, job_id, request, attempt)

    def _is_current_attempt(self, job_id: str, attempt: int) -> bool:
        """A queue message is only actionable if it belongs to the row's current
        invocation and that job is still considered active."""

        row = self._download_rows.get(job_id)
        if row is None or job_id not in self._inflight:
            return False
        return attempt == row.get("attempt")

    def _settle_job(self, job_id: str) -> None:
        self._inflight.discard(job_id)
        self._refresh_controls()

    def start_downloads(self) -> None:
        urls = self._collect_urls()
        if not urls:
            messagebox.showerror("Missing URLs", "Provide at least one URL to download.")
            return

        candidates = self._expand_playlist_urls(urls)

        try:
            workers = max(1, int(self.workers_var.get()))
            for url, playlist_name in candidates:
                self._build_request(url, playlist_name)
        except (ValueError, ResolutionParseError, SubtitleLanguageError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self._halt_executor()
        self._paused_jobs = {}
        self._inflight = set()
        self._clear_download_rows()
        self._stop_event.clear()
        self._executor = ThreadPoolExecutor(max_workers=workers)

        for url, playlist_name in candidates:
            job_id = self._next_job_id()
            request = self._build_request(url, playlist_name)
            self._create_download_row(job_id, url, request)
            self._submit_job(job_id, request)

        self._refresh_controls()
        self._append_log(f"Queued {len(candidates)} download(s) with {workers} worker(s).")

    def _download_job(
        self, job_id: str, request: DownloadRequest, attempt: int
    ) -> None:
        try:
            hook = self._make_progress_hook(job_id, attempt)
            result = self.service.download(
                request,
                progress_hook=hook,
                status_callback=lambda msg: self._queue.put(("log", msg)),
                is_cancelled=self._stop_event.is_set,
            )
            label = self._format_result_label(result)
            title = result.title or result.video_id
            self._queue.put(("task_done", (job_id, attempt, True, label, title)))
        except _DownloadCancelled:
            self._queue.put(
                ("task_stopped", (job_id, attempt, f"Stopped: {request.url}"))
            )
        except DownloadError as exc:
            if self._stop_event.is_set():
                self._queue.put(
                    ("task_stopped", (job_id, attempt, f"Stopped: {request.url}"))
                )
            else:
                self._queue.put(
                    (
                        "task_failed",
                        (job_id, attempt, f"Download failed for {request.url}: {exc}"),
                    )
                )
        except Exception as exc:
            self._queue.put(
                (
                    "task_failed",
                    (job_id, attempt, f"Unexpected error for {request.url}: {exc}"),
                )
            )

    @staticmethod
    def _format_result_label(result: DownloadResult) -> str:
        title = result.title or result.video_id or "video"
        saved = str(result.output_path) if result.output_path else "(unknown path)"
        return f"Downloaded: {title} -> {saved}"

    def pause_queue(self) -> None:
        """Pause the queue: cancel in-flight downloads (keeping their .part files)
        and snapshot every unfinished row so it can resume where it left off.
        Rows already paused stay paused (their snapshots are kept)."""

        if self._executor is None and not self._inflight:
            return
        self._halt_executor()
        self._inflight = set()
        newly_paused = 0
        for job_id, row in self._download_rows.items():
            if row.get("done") or row.get("request") is None:
                continue
            self._paused_jobs[job_id] = row["request"]
            self._mark_row_paused(job_id)
            newly_paused += 1

        self._refresh_controls()
        if newly_paused:
            self._append_log(
                f"Paused {newly_paused} download(s). "
                "Resume to continue from the saved .part files."
            )
        else:
            self._append_log("Stopped active queue.")

    def resume_queue(self) -> None:
        """Resume every paused download from its .part file."""

        jobs = list(self._paused_jobs.items())
        self._paused_jobs = {}
        if not jobs:
            self._refresh_controls()
            return
        self._stop_event.clear()
        for job_id, request in jobs:
            row = self._download_rows.get(job_id)
            if row is None:
                continue
            button = row.get("retry")
            if button is not None:
                button.destroy()
                row["retry"] = None
            row["bar"]["value"] = 0
            row["state"].configure(text="Queued")
            row["detail"].configure(text="")
            self._submit_job(job_id, request)
        self._refresh_controls()
        self._append_log(f"Resumed {len(jobs)} download(s).")

    def _mark_row_paused(self, job_id: str) -> None:
        row = self._download_rows.get(job_id)
        if row is None:
            return
        # Settle the row so late queue messages can't overwrite the paused UI.
        row["done"] = True
        row["state"].configure(text="\u23f8 Paused")
        row["detail"].configure(text="Paused \u2014 Resume to continue")
        existing = row.get("retry")
        if existing is not None:
            existing.destroy()
        resume_btn = ttk.Button(
            row["header"],
            text="Resume",
            width=7,
            command=lambda: self._resume_job(job_id),
        )
        resume_btn.pack(side=tk.RIGHT, padx=(6, 0))
        self._bind_mousewheel(resume_btn)
        row["retry"] = resume_btn

    def refresh_downloads_tree(self) -> None:
        self.downloads_tree.delete(*self.downloads_tree.get_children())
        root = Path(self.output_dir_var.get())
        if not root.exists():
            return
        self._populate_downloads_tree("", root, depth=0)

    def _populate_downloads_tree(
        self, parent_id: str, folder: Path, depth: int
    ) -> None:
        """Recursively render a folder's contents so nested layouts (e.g. a
        playlist folder whose videos each sit in their own ``<title> [id]``
        subfolder) are fully browsable, not just the first level."""

        if depth > 8:  # guard against pathological depth / symlink loops
            return
        try:
            entries = list(folder.iterdir())
        except OSError:
            return

        dirs: list[Path] = []
        files: list[Path] = []
        for entry in entries:
            try:
                if entry.is_symlink():  # show but never recurse into symlinks
                    files.append(entry)
                elif entry.is_dir():
                    dirs.append(entry)
                elif entry.is_file():
                    files.append(entry)
            except OSError:
                continue

        dirs.sort(key=lambda p: p.name.lower())
        files.sort(key=lambda p: p.name.lower())

        for sub in dirs:
            node_id = str(sub)
            self.downloads_tree.insert(
                parent_id, tk.END, iid=node_id, text=sub.name, values=("folder",)
            )
            self._populate_downloads_tree(node_id, sub, depth + 1)
        for child in files:
            self.downloads_tree.insert(
                parent_id,
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

    def _on_downloads_double_click(self, event: tk.Event) -> str | None:
        """Open the double-clicked row (file -> player, folder -> Explorer).

        Returning ``"break"`` suppresses the tree's default expand/collapse on
        double-click so it consistently means "open"; the disclosure arrow still
        expands folders in-place.
        """

        row = self.downloads_tree.identify_row(event.y)
        if not row:
            return None
        path = Path(row)
        if not path.exists():
            return None
        self.downloads_tree.selection_set(row)
        _open_path_in_file_manager(path)
        return "break"

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
        self._halt_executor()
        self.root.destroy()


def launch_gui(output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    root = tk.Tk()
    DownloaderGUI(root, output_dir=output_dir)
    root.mainloop()
