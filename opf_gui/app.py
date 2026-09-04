"""Main window for the Open Privacy Filter GUI."""

from __future__ import annotations

import sys
import tkinter as tk
from collections.abc import Sequence
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import dnd, formatting, theme
from .backends import INSTALL_HINT, model_status
from .engine import (
    MSG_BATCH_ITEM,
    MSG_DONE,
    MSG_ERROR,
    MSG_LOG,
    MSG_PROGRESS,
    MSG_RESULT,
    MSG_STATE,
    MSG_STATUS,
    EngineController,
)
from .models import DECODE_MODES, Outcome, Settings, config_path, display_name
from .widgets import Legend, LogConsole, SpanTable, TabDeck, TextPane

APP_TITLE = "Open Privacy Filter GUI"
VIEWS = ("Output", "Review", "JSON", "Batch", "Log")
"""Results views, switched by the segmented control in the top banner."""
UPSTREAM_URL = "https://github.com/openai/privacy-filter"
MODEL_URL = "https://huggingface.co/openai/privacy-filter"
TEXT_TYPES = [("Text files", "*.txt *.md *.csv *.json *.jsonl *.log *.eml"), ("All files", "*.*")]
ACCEPTED_BATCH = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".log", ".eml", ".html", ".xml", ".yml",
    ".yaml", ".ini", ".cfg", ".py", ".rst",
}


class PrivacyFilterApp(ctk.CTk):
    """Single-window workbench: editor, redacted output, span review, batch, log."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        inline_engine: bool = False,
        start_text: str | None = None,
        save_config: bool = True,
    ) -> None:
        super().__init__()
        self.settings = settings or Settings.load()
        self.inline_engine = inline_engine
        self.save_config = save_config
        self.last_outcome: Outcome | None = None
        self.batch_outcomes: list[Outcome] = []
        self.batch_files: list[Path] = []
        self.current_source: str | None = None
        self._live_job: str | None = None
        self._quitting = False
        #: Load state of the model engine, kept in step with the worker (see MSG_STATE).
        self.model_loaded = False
        #: While a load/unload job runs, the Model toggle shows the requested target.
        self._model_pending: bool | None = None
        #: A model inference pass has run since the backend was built. Drives the
        #: "Warm up model" button: solid while cold, ghosted once warm.
        self.model_warm = False

        try:
            ctk.set_default_color_theme(self.settings.color_theme)
        except (ValueError, KeyError, tk.TclError):
            self.settings.color_theme = "blue"
            ctk.set_default_color_theme("blue")
        ctk.set_appearance_mode(self.settings.appearance)

        self.title(APP_TITLE)
        self.geometry("1480x920")
        self.minsize(1080, 680)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_fonts()
        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self._bind_shortcuts()

        self.engine = EngineController(
            settings=self.settings,
            host=self,
            on_message=self._on_engine_message,
            inline=inline_engine,
        )
        self.engine.start()

        self._apply_appearance()
        self._setup_drag_and_drop()
        self._refresh_engine_info()
        if start_text is not None:
            self.input_pane.set(start_text)
            self._update_char_count()
        elif self.settings.highlight_input:
            self.input_pane.set("")

        self.log(
            f"Ready. Config: {config_path()}. "
            f"Engine: {'Demo (regex)' if self.settings.engine == 'demo' else 'OpenAI Privacy Filter'}."
        )
        self.after(150, self._startup_check)

    # ================================================================== #
    # construction
    # ================================================================== #
    def _build_fonts(self) -> None:
        size = int(self.settings.font_size)
        self.ui_font = ctk.CTkFont(size=size)
        self.title_font = ctk.CTkFont(size=size + 2, weight="bold")
        self.small_font = ctk.CTkFont(size=max(9, size - 2))
        self.tk_ui_font = theme.ui_font(size)
        self.tk_mono_font = theme.mono_font(size)

    def _build_menu(self) -> None:
        bar = tk.Menu(self, tearoff=False)

        file_menu = tk.Menu(bar, tearoff=False)
        file_menu.add_command(label="Open input file...", command=self.open_file, accelerator="Ctrl+O")
        file_menu.add_command(label="Add to batch list...", command=self.add_batch_files)
        file_menu.add_separator()
        file_menu.add_command(label="Save redacted text...", command=self.save_redacted, accelerator="Ctrl+S")
        file_menu.add_command(label="Save JSON result...", command=self.save_json)
        file_menu.add_command(label="Export batch results...", command=self.export_batch)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_close, accelerator="Ctrl+Q")
        bar.add_cascade(label="File", menu=file_menu)

        run_menu = tk.Menu(bar, tearoff=False)
        run_menu.add_command(label="Redact input", command=self.run_redact, accelerator="Ctrl+Return")
        run_menu.add_command(label="Load model", command=self.load_model)
        run_menu.add_command(label="Warm up model", command=self.warmup_model)
        run_menu.add_command(label="Unload model (free memory)", command=self.unload_model)
        run_menu.add_command(label="Cancel current job", command=self.cancel_job, accelerator="Esc")
        bar.add_cascade(label="Run", menu=run_menu)

        edit_menu = tk.Menu(bar, tearoff=False)
        edit_menu.add_command(label="Paste into input", command=self.paste_input, accelerator="Ctrl+V")
        edit_menu.add_command(label="Insert sample text", command=self.load_sample)
        edit_menu.add_command(label="Copy redacted text", command=self.copy_redacted, accelerator="Ctrl+Shift+C")
        edit_menu.add_command(label="Clear everything", command=self.clear_all)
        bar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = tk.Menu(bar, tearoff=False)
        view_menu.add_command(label="Increase font size", command=lambda: self.change_font_size(1), accelerator="Ctrl++")
        view_menu.add_command(label="Decrease font size", command=lambda: self.change_font_size(-1), accelerator="Ctrl+-")
        view_menu.add_separator()
        view_menu.add_command(label="Advanced settings...", command=self.open_settings)
        bar.add_cascade(label="View", menu=view_menu)

        help_menu = tk.Menu(bar, tearoff=False)
        help_menu.add_command(label="About OPF GUI", command=self.show_about, accelerator="F1")
        help_menu.add_command(label="Upstream repository", command=self._open_upstream)
        help_menu.add_command(label="Activity log", command=lambda: self.show_view("Log"))
        bar.add_cascade(label="Help", menu=help_menu)

        try:
            self.config(menu=bar)
        except tk.TclError:  # pragma: no cover - platform specific
            self.log("Native menu bar unavailable on this platform.", level="warn")
        self.menu_bar = bar

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self, corner_radius=0, border_width=0)
        bar.pack(side="top", fill="x")
        inner = ctk.CTkFrame(bar, fg_color="transparent", corner_radius=0)
        inner.pack(fill="x", padx=14, pady=10)

        controls = [
            ("Engine", ctk.CTkSegmentedButton(
                inner, values=["model", "demo"], width=150, command=self._on_engine_choice)),
            ("Model", ctk.CTkSegmentedButton(
                inner, values=["load", "unload"], width=150, command=self._on_model_choice)),
            ("Labels", ctk.CTkSegmentedButton(
                inner, values=["typed", "redacted"], width=150, command=self._on_output_mode_choice)),
            ("Device", ctk.CTkSegmentedButton(
                inner, values=["auto", "cpu", "cuda"], width=150, command=self._on_device_choice)),
            ("Theme", ctk.CTkSegmentedButton(
                inner, values=["dark", "light"], width=120, command=self._on_theme_choice)),
        ]
        for column, (caption, widget) in enumerate(controls, start=1):
            ctk.CTkLabel(inner, text=caption, font=self.small_font).grid(
                row=0, column=column, sticky="w", padx=(0, 14)
            )
            widget.grid(row=1, column=column, sticky="w", padx=(0, 14), pady=(1, 0))
        (self.engine_switch, self.model_switch, self.output_switch, self.device_switch,
         self.theme_switch) = (widget for _caption, widget in controls)

        # Results view switch, pinned to the right edge of the trailing spacer
        # column - directly above the "Detection summary" panel. It used to be
        # the CTkTabview strip above the "Redacted output" pane, where it stole
        # 42 px of page height and jumped sideways (resizing both editors) every
        # time a view asked for a different width. ("Settings" and "Load model"
        # also used to sit in this row; settings live in View -> Advanced
        # settings..., and load/unload is the Model toggle.)
        ctk.CTkLabel(inner, text="Results view", font=self.small_font).grid(
            row=0, column=len(controls) + 1, sticky="e"
        )
        self.view_switch = ctk.CTkSegmentedButton(inner, values=list(VIEWS), command=self._on_view_choice)
        self.view_switch.grid(row=1, column=len(controls) + 1, sticky="e", pady=(1, 0))
        inner.grid_columnconfigure(len(controls) + 1, weight=1)

        # reflect persisted settings
        self.engine_switch.set(self.settings.engine)
        self.model_switch.set("load" if self.model_loaded else "unload")
        self.output_switch.set(self.settings.output_mode)
        self.device_switch.set(self.settings.device)
        self.theme_switch.set("light" if self.settings.appearance == "light" else "dark")

    def _apply_menu_theme(self) -> None:
        """Update native Tkinter menu bar colors to match the active theme."""
        if not getattr(self, "menu_bar", None):
            return

        mode = self._current_mode()
        
        # Define palette according to light/dark mode
        if mode == "dark":
            bg_color = "#2b2b2b"
            fg_color = "#ffffff"
            active_bg = "#1f538d"
            active_fg = "#ffffff"
        else:
            bg_color = "#dbdbdb"
            fg_color = "#000000"
            active_bg = "#3b8ed0"
            active_fg = "#ffffff"

        # Apply styling to the root menu bar
        self.menu_bar.configure(
            bg=bg_color,
            fg=fg_color,
            activebackground=active_bg,
            activeforeground=active_fg,
            bd=0,
            activeborderwidth=0,
        )

        # Apply styling recursively to all submenus/dropdowns
        for child in self.menu_bar.winfo_children():
            if isinstance(child, tk.Menu):
                child.configure(
                    bg=bg_color,
                    fg=fg_color,
                    activebackground=active_bg,
                    activeforeground=active_fg,
                    selectcolor=active_bg,
                    bd=1,
                    relief="flat",
                )

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(side="top", fill="both", expand=True, padx=12, pady=(6, 0))
        # One uniform group for the two editor columns: they always split the
        # space down the middle, whatever a results view asks for. While the
        # views carried their own strip, the widest view (Batch) propped its
        # column open and dragged the divider off centre whenever a view was
        # clicked.
        body.grid_columnconfigure(0, weight=1, uniform="panes")
        body.grid_columnconfigure(1, weight=1, uniform="panes")
        body.grid_columnconfigure(2, weight=0, minsize=232)
        body.grid_rowconfigure(0, weight=1)

        # ---------------- left: input editor ---------------- #
        # Row plan (mirrored row-for-row by the Output view so both text panes
        # have the same height and the same top/bottom edges):
        #   0 action buttons + caption
        #   1 the editor itself (grows)
        #   2 char count + view switches
        # fg_color: match the results page one shade in, so both editor panes sit
        # on the same grey (a bare CTkFrame would paint the lighter outer shade).
        left = ctk.CTkFrame(body, fg_color=theme.nested_panel_bg())
        self.left_column = left
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        left.grid_rowconfigure(0, minsize=34)
        left.grid_rowconfigure(1, weight=1)
        left.grid_rowconfigure(2, minsize=32)
        left.grid_columnconfigure(0, weight=1)

        # Actions live above the editor (mirrors "Redacted output").
        header = ctk.CTkFrame(left, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        ctk.CTkLabel(header, text="Input text", font=self.title_font).pack(side="left")
        # Packed right-to-left, with "Redact" as the primary action far right:
        # Sample - Paste - Open - Redact - Clear.
        self.clear_button = ctk.CTkButton(
            header, text="Clear", width=58, height=26, command=self.clear_all,
            **theme.ghost_button(),
        )
        self.clear_button.pack(side="right", padx=(0, 6))
        self.redact_button = ctk.CTkButton(
            header, text="Redact", width=88, height=26, command=self.run_redact
        )
        self.redact_button.pack(side="right", padx=(0, 6))
        self.open_button = ctk.CTkButton(
            header, text="Open", width=62, height=26, command=self.open_file
        )
        self.open_button.pack(side="right", padx=(0, 6))
        self.paste_button = ctk.CTkButton(
            header, text="Paste", width=58, height=26, command=self.paste_input
        )
        self.paste_button.pack(side="right", padx=(0, 6))
        self.sample_button = ctk.CTkButton(
            header, text="Sample", width=64, height=26, command=self.load_sample
        )
        self.sample_button.pack(side="right", padx=(0, 6))

        self.input_pane = TextPane(
            left,
            height=18,
            font=self.tk_mono_font,
            on_change=self._on_input_change,
            undo=True,
        )
        self.input_pane.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 6))

        input_footer = ctk.CTkFrame(left, fg_color="transparent")
        input_footer.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.count_label = ctk.CTkLabel(input_footer, text="0 chars", font=self.small_font)
        self.count_label.pack(side="left")
        self.live_switch = ctk.CTkSwitch(
            input_footer, text="Auto-redact while typing", font=self.small_font,
            command=self._on_live_toggle,
        )
        self.live_switch.pack(side="right")
        self.highlight_switch = ctk.CTkSwitch(
            input_footer, text="Highlight PII in input", font=self.small_font,
            command=self._on_highlight_toggle,
        )
        self.highlight_switch.pack(side="right", padx=(0, 16))
        if self.settings.highlight_input:
            self.highlight_switch.select()
        if self.settings.live_detect:
            self.live_switch.select()

        # ---------------- middle: results views ---------------- #
        # A strip-less deck: the switch lives in the banner, so the pages start
        # at the top of the column exactly like the input editor does.
        self.tabs = TabDeck(body, VIEWS)
        self.tabs.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        output_tab = self.tabs.tab("Output")
        output_tab.grid_rowconfigure(1, weight=1)
        output_tab.grid_columnconfigure(0, weight=1)
        output_tab.grid_rowconfigure(0, minsize=34)
        output_tab.grid_rowconfigure(2, minsize=32)
        self.output_pane = TextPane(
            output_tab, height=18, font=self.tk_mono_font, readonly=True, undo=False
        )
        self.output_pane.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 6))
        output_actions = ctk.CTkFrame(output_tab, fg_color="transparent")
        output_actions.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        ctk.CTkLabel(output_actions, text="Redacted output", font=self.title_font).pack(side="left")
        self.copy_output_button = ctk.CTkButton(
            output_actions, text="Copy", width=76, height=26, command=self.copy_redacted
        )
        self.copy_output_button.pack(side="right")
        self.save_output_button = ctk.CTkButton(
            output_actions, text="Save .txt", width=96, height=26, command=self.save_redacted
        )
        self.save_output_button.pack(side="right", padx=(0, 8))
        footer = ctk.CTkFrame(output_tab, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        self.output_hint = ctk.CTkLabel(
            footer, text="Nothing redacted yet.", font=self.small_font, wraplength=520,
            justify="left",
        )
        self.output_hint.pack(side="left")

        review_tab = self.tabs.tab("Review")
        review_tab.grid_rowconfigure(1, weight=5)
        review_tab.grid_rowconfigure(3, weight=4)
        review_tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            review_tab, text="Original text with detected spans (click a span or table row to locate it)",
            font=self.small_font, anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        self.review_pane = TextPane(
            review_tab, height=10, font=self.tk_mono_font, readonly=True, undo=False,
            on_select_span=self._on_span_selected,
        )
        self.review_pane.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 4))
        self.span_table = SpanTable(review_tab, font=self.tk_ui_font, on_select=self._on_span_selected)
        self.span_table.grid(row=3, column=0, sticky="nsew", padx=8, pady=(0, 8))

        json_tab = self.tabs.tab("JSON")
        json_tab.grid_rowconfigure(1, weight=1)
        json_tab.grid_columnconfigure(0, weight=1)
        json_actions = ctk.CTkFrame(json_tab, fg_color="transparent")
        json_actions.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        ctk.CTkLabel(json_actions, text="Structured result (OPF schema v1)", font=self.small_font).pack(
            side="left"
        )
        ctk.CTkButton(json_actions, text="Copy JSON", width=96, command=self.copy_json).pack(side="right")
        ctk.CTkButton(json_actions, text="Save JSON", width=96, command=self.save_json).pack(
            side="right", padx=(0, 8)
        )
        self.json_box = ctk.CTkTextbox(json_tab, font=self.tk_mono_font, wrap="none")
        self.json_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.json_box.configure(state="disabled")

        batch_tab = self.tabs.tab("Batch")
        batch_tab.grid_rowconfigure(2, weight=1)
        batch_tab.grid_columnconfigure(0, weight=1)
        batch_actions = ctk.CTkFrame(batch_tab, fg_color="transparent")
        batch_actions.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        ctk.CTkButton(batch_actions, text="Add files...", width=100, command=self.add_batch_files).pack(
            side="left"
        )
        ctk.CTkButton(batch_actions, text="Add folder...", width=100, command=self.add_batch_folder).pack(
            side="left", padx=(8, 0)
        )
        ctk.CTkButton(batch_actions, text="Clear list", width=92, command=self.clear_batch_list).pack(
            side="left", padx=(8, 0)
        )
        ctk.CTkButton(batch_actions, text="Run batch", width=104, command=self.run_batch).pack(
            side="right"
        )
        ctk.CTkButton(batch_actions, text="Export all", width=104, command=self.export_batch).pack(
            side="right", padx=(0, 8)
        )
        self.batch_status = ctk.CTkLabel(batch_tab, text="0 files queued", font=self.small_font, anchor="w")
        self.batch_status.grid(row=1, column=0, sticky="ew", padx=10, pady=(6, 0))
        self.batch_box = ctk.CTkTextbox(batch_tab, font=self.tk_mono_font)
        self.batch_box.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.batch_box.configure(state="disabled")

        log_tab = self.tabs.tab("Log")
        log_tab.grid_rowconfigure(1, weight=1)
        log_tab.grid_columnconfigure(0, weight=1)
        log_actions = ctk.CTkFrame(log_tab, fg_color="transparent")
        log_actions.grid(row=0, column=0, sticky="ew", padx=8, pady=(6, 0))
        ctk.CTkLabel(log_actions, text="Activity log", font=self.small_font).pack(side="left")
        ctk.CTkButton(log_actions, text="Clear log", width=92, command=self._clear_log).pack(side="right")
        self.copy_log_button = ctk.CTkButton(
            log_actions, text="Copy log", width=92,
            command=self._copy_log, **theme.ghost_button(),
        )
        self.copy_log_button.pack(side="right", padx=(0, 8))
        self.log_box = ctk.CTkTextbox(log_tab, font=self.tk_mono_font, wrap="word")
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.log_box.configure(state="disabled")
        self.console = LogConsole(self.log_box)

        # ---------------- right: summary sidebar ---------------- #
        sidebar = ctk.CTkScrollableFrame(body, label_text="Detection summary")
        sidebar.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        sidebar.grid_columnconfigure(0, weight=1)
        self.legend = Legend(sidebar, font=self.tk_ui_font)
        self.legend.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 8))
        self.summary_label = ctk.CTkLabel(
            sidebar, text="No result yet.", font=self.small_font, anchor="w", justify="left",
            wraplength=210,
        )
        self.summary_label.grid(row=1, column=0, sticky="ew", padx=4)
        self.engine_info_label = ctk.CTkLabel(
            sidebar, text="", font=self.small_font, anchor="w", justify="left", wraplength=210
        )
        self.engine_info_label.grid(row=2, column=0, sticky="ew", padx=4, pady=(10, 4))
        # Model load/unload moved to the toolbar toggle, so only warm-up is left here.
        # Built active (solid); _style_warmup_button() ghosts it once the model is warm.
        self.warmup_button = ctk.CTkButton(
            sidebar, text="Warm up model", width=200, height=28,
            command=self.warmup_model,
        )
        self.warmup_button.grid(row=3, column=0, sticky="ew", padx=4, pady=(4, 0))

    def _build_statusbar(self) -> None:
        bar = ctk.CTkFrame(self, corner_radius=0)
        bar.pack(side="bottom", fill="x")
        self.status_label = ctk.CTkLabel(bar, text="Idle", font=self.small_font, anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True, padx=12, pady=6)
        self.progress = ctk.CTkProgressBar(bar, width=170, mode="indeterminate")
        self.progress.pack(side="right", padx=(0, 12))
        self.metrics_label = ctk.CTkLabel(bar, text="", font=self.small_font)
        self.metrics_label.pack(side="right", padx=(0, 12))

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-Return>", lambda _e: self.run_redact())
        self.bind_all("<KP_Enter>", lambda _e: self.run_redact())
        self.bind_all("<Control-o>", lambda _e: self.open_file())
        self.bind_all("<Control-s>", lambda _e: self.save_redacted())
        self.bind_all("<Control-S>", lambda _e: self.copy_redacted())
        self.bind_all("<Control-Shift-C>", lambda _e: self.copy_redacted())
        self.bind_all("<Control-plus>", lambda _e: self.change_font_size(1))
        self.bind_all("<Control-equal>", lambda _e: self.change_font_size(1))
        self.bind_all("<Control-minus>", lambda _e: self.change_font_size(-1))
        self.bind_all("<Escape>", lambda _e: self.cancel_job())
        self.bind_all("<F1>", lambda _e: self.show_about())
        self.bind_all("<Control-q>", lambda _e: self._on_close())

    # ================================================================== #
    # appearance
    # ================================================================== #
    def _current_mode(self) -> str:
        mode = ctk.get_appearance_mode()
        return theme.resolve_mode(self.settings.appearance, "dark" if "Dark" in str(mode) else "light")

    def _apply_appearance(self) -> None:
        mode = self._current_mode()
        colors = theme.pane_colors(mode)
        for pane in (self.input_pane, self.output_pane, self.review_pane):
            pane.apply_appearance(mode, self.tk_mono_font)
        self.span_table.apply_appearance(mode)
        self.legend.apply_appearance(mode)
        for box in (self.json_box, self.batch_box, self.log_box):
            box.configure(fg_color=colors["bg"], text_color=colors["fg"])
        self.console.apply_appearance(mode)

        # Apply theme colors to the menu bar
        self._apply_menu_theme()
        self._style_warmup_button()  # keeps the warm/cold face on the current palette

    def change_font_size(self, delta: int) -> None:
        size = max(8, min(24, int(self.settings.font_size) + delta))
        if size == self.settings.font_size:
            return
        self.settings.font_size = size
        self.tk_ui_font = theme.ui_font(size)
        self.tk_mono_font = theme.mono_font(size)
        self.ui_font.configure(size=size)
        self.title_font.configure(size=size + 2)
        self.small_font.configure(size=max(9, size - 2))
        for pane in (self.input_pane, self.output_pane, self.review_pane):
            pane.set_font(self.tk_mono_font)
        self.span_table.apply_appearance(self._current_mode())
        self.legend.rebuild(self._legend_labels())
        self.legend.update_counts(self.last_outcome)
        self._save_settings()

    def _legend_labels(self) -> list[str]:
        extra = sorted(self.last_outcome.by_label().keys()) if self.last_outcome else []
        return theme.known_labels(extra)

    # ================================================================== #
    # engine wiring
    # ================================================================== #
    def _startup_check(self) -> None:
        status = model_status(self.settings.checkpoint)
        if self.settings.engine == "model" and not status.installed:
            self.log("OpenAI Privacy Filter package is not installed - switching to Demo engine.", level="warn")
            self._set_engine("demo", notify=True)
            messagebox.showwarning(APP_TITLE, INSTALL_HINT, parent=self)
        elif self.settings.engine == "model":
            self.log(f"Model engine: {status.detail}")
            if status.checkpoint_present and self.settings.auto_load_model:
                self.load_model()
            elif not status.checkpoint_present:
                self.log("First redaction will download the checkpoint (approx. 1.5 GB).", level="warn")
        if self.settings.engine == "demo":
            self.log("Demo engine uses regex heuristics - not a privacy control.", level="warn")
        self._refresh_engine_info()

    def _on_engine_message(self, kind: str, payload: object) -> None:
        if self._quitting:
            return
        if kind == MSG_LOG:
            self.log(str(payload))
        elif kind == MSG_STATUS:
            self.set_status(str(payload))
        elif kind == MSG_ERROR:
            self.log(str(payload), level="error")
            self.set_status("Error - see Log tab")
            self._set_busy(False)
        elif kind == MSG_RESULT:
            self.show_outcome(payload)  # type: ignore[arg-type]
        elif kind == MSG_BATCH_ITEM:
            self._on_batch_item(payload)  # type: ignore[arg-type]
        elif kind == MSG_PROGRESS:
            done, total = payload  # type: ignore[misc]
            self.batch_status.configure(text=f"{done}/{total} files processed")
        elif kind == MSG_STATE:
            if isinstance(payload, dict):
                self.model_loaded = bool(payload.get("loaded", False))
                self.model_warm = bool(payload.get("warm", False))
            self._sync_model_switch()
            self._style_warmup_button()
            self._refresh_engine_info()
        elif kind == MSG_DONE:
            self._set_busy(False)
            self.set_status("Ready")
            self._model_pending = None
            self._sync_model_switch()
            self._style_warmup_button()
            self._refresh_engine_info()

    def _set_busy(self, busy: bool) -> None:
        if busy:
            self.progress.start()
        else:
            self.progress.stop()

    def set_status(self, text: str) -> None:
        self.status_label.configure(text=text)

    def log(self, message: str, level: str = "info") -> None:
        if hasattr(self, "console"):
            self.console.log(message, level)

    def report_callback_exception(self, exc_type, exc_value, exc_tb) -> int:  # noqa: ANN001
        import traceback

        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb)).strip()
        try:
            self.log(text, level="error")
        except Exception:  # noqa: BLE001 - never let error reporting hide the error
            print(text, file=sys.stderr)
        return 1

    def _refresh_engine_info(self) -> None:
        """Populate the engine status panel in the "Detection summary".

        This panel is the single source of truth for which engine is active:
        it shows the active backend's describe() (checkpoint, device, mode...)
        or marks an unavailable engine. (The old toolbar "engine: ..." badge
        duplicated this panel and has been removed.)
        """
        backend = self.engine.backend
        try:
            info = backend.describe()
        except Exception as exc:  # noqa: BLE001
            info = {"Engine": f"unavailable ({exc})"}
        self.engine_info_label.configure(
            text="\n".join(f"{key}: {value}" for key, value in info.items())
        )

    # ================================================================== #
    # settings controls
    # ================================================================== #
    def _set_engine(self, engine: str, notify: bool = False) -> None:
        self.settings.engine = engine
        self.engine_switch.set(engine)
        self.engine.request_backend_rebuild()
        self._forget_model()  # the rebuild drops any weights held in RAM
        self._save_settings()
        if notify:
            self.log(f"Engine -> {engine}")
        self.after(60, self._refresh_engine_info)

    def _on_engine_choice(self, value: str) -> None:
        if value == self.settings.engine:
            return
        self._set_engine(value, notify=True)
        if value == "model":
            status = model_status(self.settings.checkpoint)
            if not status.installed:
                self.log("opf package missing - staying on Demo.", level="warn")
                self._set_engine("demo")
                messagebox.showwarning(APP_TITLE, INSTALL_HINT, parent=self)
            elif not status.checkpoint_present:
                self.log(status.detail)

    def _on_model_choice(self, value: str) -> None:
        """Toolbar Model toggle: `load` pulls the checkpoint into RAM, `unload` frees it."""
        want_loaded = value == "load"
        if self._model_pending is not None:
            self.set_status("Model job already running - Esc cancels it")
            self._sync_model_switch()
            return
        if want_loaded == self.model_loaded:
            self._sync_model_switch()
            return
        self._model_pending = want_loaded  # claimed first: an inline engine finishes below
        started = self.load_model() if want_loaded else self.unload_model()
        if not started:
            self._model_pending = None
        self._sync_model_switch()  # optimistic while it runs, truthful after

    def _forget_model(self) -> None:
        """Mark the model as not loaded (a backend rebuild throws the weights away).

        An in-flight load/unload claim is left alone: its MSG_DONE re-syncs the
        toggle from the worker's report either way.
        """
        self.model_loaded = False
        self.model_warm = False
        self._sync_model_switch()
        self._style_warmup_button()

    def _sync_model_switch(self) -> None:
        """Point the Model toggle at the real load state, or at the target of a
        load/unload job still in flight."""
        state = self.model_loaded if self._model_pending is None else self._model_pending
        self.model_switch.set("load" if state else "unload")

    def _active_button_face(self) -> dict[str, object]:
        """Colours of a normal (active) button, read from the live CTkButton theme."""
        wanted = ("fg_color", "hover_color", "text_color", "border_color", "border_width")
        colors: dict[str, object] = {}
        try:
            from customtkinter.windows.widgets.theme.theme_manager import ThemeManager  # noqa: PLC0415

            face = ThemeManager.theme.get("CTkButton", {})
            for key in wanted:
                if key in face:
                    colors[key] = list(face[key]) if isinstance(face[key], list) else face[key]
        except Exception:  # noqa: BLE001 - stubbed or relocated internals
            colors = {}
        return {**theme.ACTIVE_BUTTON, **colors}

    def _style_warmup_button(self) -> None:
        """The warm-up button is the warm/cold indicator: accent-coloured like the
        other action buttons while the model is cold, ghosted once it is warm.

        Ghosted under the Demo engine too - regex detection has no model to warm.
        """
        ghosted = self.model_warm or self.settings.engine != "model"
        options = theme.ghost_button() if ghosted else self._active_button_face()
        self.warmup_button.configure(**options)

    def _on_output_mode_choice(self, value: str) -> None:
        self.settings.output_mode = value
        self._save_settings()
        self.log(f"Label mode -> {value}")
        if self.last_outcome is not None:
            self.run_redact()
        self._refresh_engine_info()

    def _on_device_choice(self, value: str) -> None:
        self.settings.device = value
        self._save_settings()
        self.log(f"Device -> {value} (applies on the next run)")
        self._refresh_engine_info()

    def _on_theme_choice(self, value: str) -> None:
        self.settings.appearance = value
        ctk.set_appearance_mode(value)
        self._apply_appearance()
        self._save_settings()

    def _on_highlight_toggle(self) -> None:
        self.settings.highlight_input = bool(self.highlight_switch.get())
        if not self.settings.highlight_input:
            self.input_pane.clear_spans()
        elif self.last_outcome is not None:
            self._highlight_input(self.last_outcome)
        self._save_settings()

    def _on_live_toggle(self) -> None:
        self.settings.live_detect = bool(self.live_switch.get())
        self._save_settings()
        if self.settings.live_detect:
            self.log("Auto-redact is on - best paired with the Demo engine or a warm model.")

    def _on_view_choice(self, value: str) -> None:
        self.show_view(value)

    def show_view(self, name: str) -> None:
        """Switch the results deck and keep the banner switch pointing at it."""
        self.tabs.set(name)
        self.view_switch.set(name)

    def _on_input_change(self) -> None:
        self._update_char_count()
        if not self.settings.live_detect:
            return
        self._schedule_live_redact()

    def _update_char_count(self) -> None:
        self.count_label.configure(text=f"{len(self.input_pane.get()):,} chars")

    def _schedule_live_redact(self) -> None:
        if not self.settings.live_detect:
            return
        if self._live_job is not None:
            self.after_cancel(self._live_job)
        self._live_job = self.after(500, self._live_redact)

    def _live_redact(self) -> None:
        self._live_job = None
        if not self.settings.live_detect or self.engine.busy:
            return
        self.run_redact(silent=True)

    def open_settings(self) -> None:
        SettingsDialog(self, self.settings, on_apply=self._after_settings_change)

    def _after_settings_change(self) -> None:
        self.engine.request_backend_rebuild()
        self._forget_model()
        self.device_switch.set(self.settings.device)
        self.output_switch.set(self.settings.output_mode)
        self.engine_switch.set(self.settings.engine)
        self._apply_drag_and_drop()
        self._save_settings()
        self._refresh_engine_info()

    def _save_settings(self) -> None:
        if not self.save_config:
            return
        try:
            self.settings.save()
        except OSError as exc:  # pragma: no cover - disk problems
            self.log(f"Could not save settings: {exc}", level="warn")

    # ================================================================== #
    # actions
    # ================================================================== #
    def run_redact(self, silent: bool = False) -> None:
        text = self.input_pane.get()
        if not text.strip():
            self.set_status("Nothing to redact - enter or paste text first")
            return
        if self.engine.busy:
            self.set_status("Busy - cancel or wait for the current job")
            return
        if not silent:
            self._set_busy(True)
            self.set_status("Queued...")
        self.engine.redact(text, source=self.current_source)

    def load_model(self) -> bool:
        """Queue a model load. Returns True when a job actually started.

        The environment is probed before the engine is switched, so a refused or
        cancelled load leaves the previous engine (usually Demo) in place.
        """
        status = model_status(self.settings.checkpoint)
        if not status.installed:
            messagebox.showwarning(APP_TITLE, INSTALL_HINT, parent=self)
            return False
        if not status.checkpoint_present:
            proceed = messagebox.askyesno(
                APP_TITLE,
                "No local checkpoint was found.\n\n"
                f"{status.detail}\n\nThe first load downloads the model from HuggingFace "
                "(about 1.5 GB, one time). Download and load now?",
                parent=self,
            )
            if not proceed:
                self.set_status("Model load cancelled")
                return False
        if self.settings.engine != "model":
            self._set_engine("model", notify=True)
        self._set_busy(True)
        self.engine.load()
        return True

    def warmup_model(self) -> None:
        if self.settings.engine != "model":
            self.set_status("Warm-up needs the model engine - set Engine to 'model' first")
            return
        self._set_busy(True)
        self.engine.warmup()

    def unload_model(self) -> bool:
        """Queue an unload (freeing the weights). Returns True when a job started."""
        self._set_busy(True)
        self.engine.unload()
        return True

    def cancel_job(self) -> None:
        if self.engine.busy:
            self.engine.cancel()
        else:
            self.set_status("Nothing running")

    def load_sample(self) -> None:
        self.input_pane.set(formatting.sample_text())
        self.current_source = None
        self._on_input_change()
        self.log("Loaded synthetic sample text.")

    def paste_input(self) -> None:
        try:
            clip = self.clipboard_get()
        except tk.TclError:
            self.set_status("Clipboard unavailable")
            return
        self.input_pane.text.insert("insert", clip)
        self.input_pane.focus_input()

    def open_file(self) -> None:
        paths = self._ask_files()
        if paths:
            self._load_paths(paths)

    def _load_paths(self, paths: list[Path]) -> None:
        """Load the first file into the editor and queue any extras for batch."""
        if not paths:
            return
        try:
            content = formatting.read_text_file(paths[0])
        except OSError as exc:
            messagebox.showerror(APP_TITLE, f"Could not read file:\n{exc}", parent=self)
            return
        self.input_pane.set(content)
        self.current_source = str(paths[0])
        self.settings.add_recent(paths[0])
        self._save_settings()
        self._on_input_change()
        self.log(f"Loaded {paths[0].name} ({len(content):,} chars).")
        if len(paths) > 1:
            self._extend_batch(paths[1:])

    def _ask_files(self) -> list[Path]:
        initial = Path(self.settings.export_dir).expanduser() if self.settings.export_dir else Path.home()
        try:
            picked = filedialog.askopenfilenames(
                parent=self, title="Open text file(s)", initialdir=str(initial),
                filetypes=TEXT_TYPES,
            )
        except tk.TclError:
            return []
        return [Path(item) for item in picked]

    # ------------------------- drag & drop ------------------------- #
    def _setup_drag_and_drop(self) -> None:
        """Register the input editor as a file drop target (optional feature)."""
        self._drop_zones: list[dnd.DropZone] = []
        self._saved_status: str | None = None
        if not self.settings.drag_and_drop:
            self.log("Drag & drop is switched off in settings.")
            return
        version = dnd.enable(self)
        if version is None:
            self.log(f"Drag & drop unavailable. {dnd.DND_HINT}", level="warn")
            return
        zone = dnd.register(
            self.input_pane.text,
            self._on_drop_files,
            accepted=ACCEPTED_BATCH,
            on_enter=self._on_drag_enter,
            on_leave=self._on_drag_leave,
        )
        if zone is None:
            self.log(f"Drag & drop could not attach to the editor. {dnd.DND_HINT}", level="warn")
            return
        self._drop_zones.append(zone)
        self.log(
            f"Drag & drop ready (tkdnd {version}) - drop .txt/.md/.csv/.json files on the "
            "input editor, or several at once to queue a batch."
        )

    def _apply_drag_and_drop(self) -> None:
        """Re-register drop targets after the settings flag changed."""
        for zone in getattr(self, "_drop_zones", []):
            zone.remove()
        self._setup_drag_and_drop()

    def _on_drag_enter(self, paths: list[Path]) -> None:
        colors = theme.pane_colors(self._current_mode())
        self.input_pane.text.configure(
            highlightbackground=colors["active"], highlightcolor=colors["active"]
        )
        names = ", ".join(path.name or str(path) for path in paths[:2])
        if len(paths) > 2:
            names += f" (+{len(paths) - 2} more)"
        # tkdnd fires DropEnter for nested widgets too; only remember the first.
        if self._saved_status is None:
            self._saved_status = self.status_label.cget("text")
        self.set_status(f"Release to load: {names or 'files'}")

    def _on_drag_leave(self) -> None:
        colors = theme.pane_colors(self._current_mode())
        self.input_pane.text.configure(
            highlightbackground=colors["border"], highlightcolor=colors["active"]
        )
        if self._saved_status:
            self.set_status(str(self._saved_status))
            self._saved_status = None

    def _on_drop_files(self, files: list[Path], rejected: list[Path]) -> None:
        if rejected:
            self.log(
                "Ignored unsupported drop(s): " + ", ".join(path.name for path in rejected[:6]),
                level="warn",
            )
        if not files:
            self.set_status("Drop ignored - not a supported text file")
            return
        paths = self._expand_dropped(files)
        if not paths:
            self.set_status("Drop ignored - no supported text files found")
            self.log("Dropped folder(s) contained no supported text files.", level="warn")
            return
        label = paths[0].name if len(paths) == 1 else f"{len(paths)} files"
        self.log(f"Dropped {label}.")
        if len(paths) > 1:
            self.show_view("Batch")
        self._load_paths(paths)

    @staticmethod
    def _expand_dropped(paths: Sequence[Path]) -> list[Path]:
        """Expand dropped folders into the supported text files they contain."""
        expanded: list[Path] = []
        for path in paths:
            if path.is_dir():
                expanded.extend(
                    item for item in sorted(path.rglob("*"))
                    if item.is_file() and item.suffix.lower() in ACCEPTED_BATCH
                )
            else:
                expanded.append(path)
        return expanded

    def clear_all(self) -> None:
        self.input_pane.clear()
        self.output_pane.clear()
        self.review_pane.clear()
        self.span_table.populate([])
        self._set_json("")
        self.last_outcome = None
        self.current_source = None
        self.legend.update_counts(None)
        self.summary_label.configure(text="No result yet.")
        self.metrics_label.configure(text="")
        self.output_hint.configure(text="Nothing redacted yet.")
        self.count_label.configure(text="0 chars")
        self.set_status("Cleared")

    # ------------------------- batch ------------------------- #
    def add_batch_files(self) -> None:
        paths = self._ask_files()
        if paths:
            self._extend_batch(paths)

    def add_batch_folder(self) -> None:
        initial = Path(self.settings.export_dir).expanduser() if self.settings.export_dir else Path.home()
        try:
            folder = filedialog.askdirectory(parent=self, title="Choose folder", initialdir=str(initial))
        except tk.TclError:
            return
        if not folder:
            return
        found = self._expand_dropped([Path(folder).expanduser()])
        if not found:
            messagebox.showinfo(APP_TITLE, "No supported text files in that folder.", parent=self)
            return
        self._extend_batch(found)

    def _extend_batch(self, paths: list[Path]) -> None:
        existing = {str(item) for item in self.batch_files}
        added = [item for item in paths if str(item) not in existing]
        self.batch_files.extend(added)
        self._render_batch_list()
        self.log(f"Batch list: +{len(added)} file(s), {len(self.batch_files)} total.")

    def clear_batch_list(self) -> None:
        self.batch_files = []
        self.batch_outcomes = []
        self._render_batch_list()

    def _render_batch_list(self) -> None:
        self.batch_box.configure(state="normal")
        self.batch_box.delete("1.0", "end")
        if self.batch_outcomes:
            by_source = {item.source: item for item in self.batch_outcomes if item.source}
            for path in self.batch_files:
                outcome = by_source.get(str(path))
                count = outcome.span_count if outcome else "-"
                self.batch_box.insert("end", f"{count:>5}  {path.name}    {path}\n")
        else:
            for path in self.batch_files:
                self.batch_box.insert("end", f"{'-':>5}  {path.name}    {path}\n")
        self.batch_box.configure(state="disabled")
        self.batch_status.configure(text=f"{len(self.batch_files)} files queued")

    def run_batch(self) -> None:
        if not self.batch_files:
            self.set_status("Add files to the batch list first")
            return
        if self.engine.busy:
            self.set_status("Busy - cancel or wait")
            return
        items: list[tuple[str, str]] = []
        skipped = 0
        for path in self.batch_files:
            try:
                items.append((str(path), formatting.read_text_file(path)))
            except (OSError, UnicodeError) as exc:
                self.log(f"Skipped {path.name}: {exc}", level="warn")
                skipped += 1
        if not items:
            self.set_status("No readable files")
            return
        self.batch_outcomes = []
        self._set_busy(True)
        self.set_status(f"Batch: {len(items)} file(s)")
        if skipped:
            self.log(f"{skipped} unreadable file(s) skipped.", level="warn")
        self.engine.batch(items)

    def _on_batch_item(self, outcome: Outcome) -> None:
        self.batch_outcomes.append(outcome)
        self.last_outcome = outcome
        self._render_batch_list()
        total_spans = sum(item.span_count for item in self.batch_outcomes)
        self.metrics_label.configure(
            text=f"{len(self.batch_outcomes)} file(s), {total_spans} span(s)"
        )

    def export_batch(self) -> None:
        if not self.batch_outcomes:
            self.set_status("Run a batch first")
            return
        try:
            folder = filedialog.askdirectory(parent=self, title="Export folder")
        except tk.TclError:
            return
        if not folder:
            return
        target = Path(folder).expanduser()
        written = 0
        for outcome in self.batch_outcomes:
            source = outcome.source or "document"
            out_path = target / f"{formatting.safe_stem(source)}.redacted.txt"
            formatting.write_text_file(out_path, outcome.redacted_text)
            written += 1
        formatting.write_text_file(
            target / "results.jsonl", formatting.outcomes_to_jsonl(self.batch_outcomes)
        )
        formatting.write_text_file(
            target / "report.md",
            formatting.batch_summary_markdown(self.batch_outcomes, self.engine.backend.name),
        )
        self.settings.export_dir = str(target)
        self._save_settings()
        self.log(f"Batch export complete: {written} file(s) + results.jsonl + report.md -> {target}")
        self.set_status(f"Exported {written} file(s) to {target.name}")
        messagebox.showinfo(APP_TITLE, f"Exported {written} redacted file(s) to:\n{target}", parent=self)

    # ------------------------- results ------------------------- #
    def show_outcome(self, outcome: Outcome) -> None:
        self.last_outcome = outcome
        self.current_source = outcome.source or self.current_source
        self.output_pane.set(outcome.redacted_text)
        self.review_pane.set(outcome.text)
        self.review_pane.set_spans(outcome.spans)
        self.span_table.populate(outcome.spans)
        self._set_json(outcome.to_json())
        self.legend.rebuild(self._legend_labels())
        self.legend.update_counts(outcome)
        self._highlight_input(outcome)

        stats = outcome.by_label()
        headline = f"{outcome.span_count} span(s) in {formatting.format_latency(outcome.latency_ms)}"
        self.summary_label.configure(
            text="\n".join(
                [headline] + [f"{count} x {display_name(label)}" for label, count in sorted(stats.items(), key=lambda kv: -kv[1])]
            )
        )
        self.metrics_label.configure(text=formatting.plain_summary(outcome))
        hint = f"Engine: {'OpenAI Privacy Filter' if outcome.engine == 'model' else 'Demo regex'}"
        if outcome.warning:
            hint += f" - {outcome.warning}"
        _visible, hidden = formatting.resolve_overlaps(outcome.spans)
        if hidden:
            hint += f" - {len(hidden)} overlapping span(s) hidden in the highlight view"
        self.output_hint.configure(text=hint)
        self.set_status(formatting.plain_summary(outcome))
        self.log(
            f"Redaction complete: {outcome.span_count} span(s), "
            f"{formatting.format_latency(outcome.latency_ms)}"
            + (f" [{outcome.source}]" if outcome.source else "")
        )

    def _highlight_input(self, outcome: Outcome) -> None:
        if self.settings.highlight_input and self.input_pane.get() == outcome.text:
            self.input_pane.set_spans(outcome.spans)
        elif not self.settings.highlight_input:
            self.input_pane.clear_spans()

    def _on_span_selected(self, span) -> None:  # noqa: ANN001
        self.review_pane.locate(span)
        self.show_view("Review")
        if self.last_outcome is not None and self.settings.highlight_input:
            if self.input_pane.get() == self.last_outcome.text:
                self.input_pane.locate(span)
        self.set_status(f"{display_name(span.label)}: {span.text!r} -> {span.placeholder}")

    def _set_json(self, content: str) -> None:
        self.json_box.configure(state="normal")
        self.json_box.delete("1.0", "end")
        self.json_box.insert("1.0", content)
        self.json_box.configure(state="disabled")

    # ------------------------- export ------------------------- #
    def copy_redacted(self) -> None:
        text = self.output_pane.get()
        if not text:
            self.set_status("Nothing to copy")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.set_status(f"Copied {len(text):,} chars of redacted text")

    def copy_json(self) -> None:
        text = self.json_box.get("1.0", "end-1c")
        if not text.strip():
            self.set_status("Nothing to copy")
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.set_status("Copied JSON result")

    def save_redacted(self) -> None:
        if self.last_outcome is None:
            self.set_status("Run a redaction first")
            return
        suggested = formatting.suggest_export_path(self.settings, self.current_source, "redacted", ".txt")
        path = self._ask_save(suggested)
        if not path:
            return
        formatting.write_text_file(path, self.last_outcome.redacted_text)
        self._remember_export(path)
        self.log(f"Wrote redacted text to {path}")
        messagebox.showinfo(APP_TITLE, f"Redacted text saved to:\n{path}", parent=self)

    def save_json(self) -> None:
        if self.last_outcome is None:
            self.set_status("Run a redaction first")
            return
        suggested = formatting.suggest_export_path(self.settings, self.current_source, "result", ".json")
        path = self._ask_save(suggested)
        if not path:
            return
        formatting.write_text_file(path, self.last_outcome.to_json())
        self._remember_export(path)
        self.log(f"Wrote JSON result to {path}")

    def _ask_save(self, suggested: Path) -> Path | None:
        try:
            picked = filedialog.asksaveasfilename(
                parent=self,
                title="Save as",
                defaultextension=suggested.suffix,
                initialdir=str(suggested.parent),
                initialfile=suggested.name,
                filetypes=TEXT_TYPES,
            )
        except tk.TclError:
            return None
        return Path(picked) if picked else None

    def _remember_export(self, path: Path) -> None:
        self.settings.export_dir = str(path.parent)
        self.settings.add_recent(path)
        self._save_settings()
        self.set_status(f"Saved {path.name}")

    # ------------------------- misc ------------------------- #
    def _clear_log(self) -> None:
        self.console.clear()
        self.set_status("Activity log cleared")

    def _copy_log(self) -> None:
        content = self.console.text()
        if not content.strip():
            self.set_status("Activity log is empty")
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.set_status(f"Activity log copied ({len(content.splitlines())} lines)")

    def _open_upstream(self) -> None:
        message = f"OpenAI Privacy Filter\n\nCode: {UPSTREAM_URL}\nWeights: {MODEL_URL}\n\nCopy the link from this dialog."
        self.clipboard_clear()
        self.clipboard_append(UPSTREAM_URL)
        messagebox.showinfo(APP_TITLE, message + "\n\n(repo link copied to clipboard)", parent=self)

    def show_about(self) -> None:
        documents = len(self.batch_outcomes) + (1 if self.last_outcome else 0)
        spans = sum(item.span_count for item in self.batch_outcomes)
        if self.last_outcome is not None:
            spans += self.last_outcome.span_count
        messagebox.showinfo(
            APP_TITLE,
            "Open Privacy Filter GUI\n\n"
            "Desktop front-end for the open-weight 1.5B MoE PII redaction model "
            "(Apache 2.0) from OpenAI. Inference runs locally on your machine; text "
            "never leaves the device. The only network access is the one-time "
            "checkpoint download from HuggingFace.\n\n"
            f"Session documents: {documents}\n"
            f"Session PII spans: {spans}\n"
            f"Config file: {config_path()}\n\n"
            "This GUI is licensed under the Apache License 2.0.\n"
            "Demo engine = regex heuristics for interface previews only.",
            parent=self,
        )

    def _on_close(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        try:
            self._save_settings()
            self.engine.shutdown()
        finally:
            self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    """Advanced runtime settings (checkpoint, context window, decoding)."""

    def __init__(self, master: PrivacyFilterApp, settings: Settings, on_apply) -> None:  # noqa: ANN001
        super().__init__(master)
        self.master_app = master
        self.settings = settings
        self.on_apply = on_apply
        self.title("Privacy Filter settings")
        self.geometry("620x620")
        self.transient(master)
        self.grab_set()

        frame = ctk.CTkScrollableFrame(self, label_text="Runtime settings")
        frame.pack(fill="both", expand=True, padx=12, pady=12)
        frame.grid_columnconfigure(1, weight=1)

        self.checkpoint_var = tk.StringVar(value=settings.checkpoint)
        self.nctx_var = tk.StringVar(value=settings.n_ctx)
        self.calibration_var = tk.StringVar(value=settings.viterbi_calibration_path)
        self.export_var = tk.StringVar(value=settings.export_dir)
        self.trim_var = tk.BooleanVar(value=settings.trim_whitespace)
        self.overlap_var = tk.BooleanVar(value=settings.discard_overlapping)
        self.autoload_var = tk.BooleanVar(value=settings.auto_load_model)
        self.drop_var = tk.BooleanVar(value=settings.drag_and_drop)
        self.decode_var = tk.StringVar(value=settings.decode_mode)

        row = 0
        row = self._add_entry(frame, row, "Checkpoint directory", self.checkpoint_var,
                             "Empty = OPF_CHECKPOINT env var or ~/.opf/privacy_filter (auto-download)")
        row = self._add_entry(frame, row, "Context window (n_ctx)", self.nctx_var,
                             "Blank = model default (128k); lower values save memory")
        row = self._add_entry(frame, row, "Viterbi calibration JSON", self.calibration_var,
                             "Blank = <checkpoint>/viterbi_calibration.json, else zero biases")
        row = self._add_entry(frame, row, "Default export folder", self.export_var,
                              "Used by Save / Export dialogs")
        row = self._add_choice(
            frame, row, "Decode mode (reloads runtime)", self.decode_var, list(DECODE_MODES),
            "viterbi = more accurate (slower); argmax = faster (no constraint). "
            "Applies only to the model engine.",
        )
        for label, var in (
            ("Trim whitespace from spans (reloads runtime)", self.trim_var),
            ("Discard overlapping predicted spans (reloads runtime)", self.overlap_var),
            ("Load model automatically at startup", self.autoload_var),
            ("Accept text files dropped on the editor (requires tkinterdnd2)", self.drop_var),
        ):
            ctk.CTkCheckBox(
                frame, text=label, variable=var, font=self.master_app.small_font
            ).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=6
            )
            row += 1

        ctk.CTkLabel(
            frame,
            text=(
                "Settings marked 'reloads runtime' force the model to be rebuilt on the "
                "next run. Device and decode-mode changes behave the same way."
            ),
            font=master.small_font,
            wraplength=560,
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 4))
        row += 1

        buttons = ctk.CTkFrame(frame, fg_color="transparent")
        buttons.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ctk.CTkButton(buttons, text="Apply", width=110, command=self._apply).pack(side="right")
        ctk.CTkButton(
            buttons, text="Cancel", width=110, command=self.destroy, **theme.ghost_button(),
        ).pack(side="right", padx=(0, 8))

    def _add_entry(self, frame, row: int, label: str, var, help_text: str):  # noqa: ANN001, ANN202
        ctk.CTkLabel(
            frame, text=label, anchor="w", font=self.master_app.small_font
        ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
        ctk.CTkEntry(frame, textvariable=var).grid(row=row, column=1, sticky="ew", pady=(8, 0))
        row += 1
        ctk.CTkLabel(frame, text=help_text, font=self.master_app.small_font, anchor="w",
                     wraplength=420, justify="left").grid(row=row, column=1, sticky="w")
        return row + 1

    def _add_choice(self, frame, row: int, label: str, var, options, help_text: str) -> int:  # noqa: ANN001, ANN202
        ctk.CTkLabel(
            frame, text=label, anchor="w", font=self.master_app.small_font
        ).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=(8, 0))
        ctk.CTkSegmentedButton(
            frame, values=list(options), variable=var, font=self.master_app.small_font
        ).grid(row=row, column=1, sticky="w", pady=(8, 0))
        row += 1
        ctk.CTkLabel(frame, text=help_text, font=self.master_app.small_font, anchor="w",
                     wraplength=420, justify="left").grid(row=row, column=1, sticky="w")
        return row + 1

    def _apply(self) -> None:
        self.settings.checkpoint = self.checkpoint_var.get().strip()
        self.settings.n_ctx = self.nctx_var.get().strip()
        self.settings.viterbi_calibration_path = self.calibration_var.get().strip()
        self.settings.export_dir = self.export_var.get().strip()
        self.settings.decode_mode = self.decode_var.get()
        self.settings.trim_whitespace = bool(self.trim_var.get())
        self.settings.discard_overlapping = bool(self.overlap_var.get())
        self.settings.auto_load_model = bool(self.autoload_var.get())
        self.settings.drag_and_drop = bool(self.drop_var.get())
        self.master_app.log("Settings updated.")
        self.on_apply()
        self.destroy()
