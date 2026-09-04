"""Reusable GUI widgets built on tkinter/ttk + customtkinter.

Plain ``tkinter.Text`` and ``ttk.Treeview`` are used where per-span colour tags
are required, because customtkinter's ``CTkTextbox`` does not expose tags.
"""

from __future__ import annotations

import customtkinter as ctk
import tkinter as tk
from contextlib import contextmanager
from datetime import datetime
from tkinter import ttk
from typing import Any, Callable, Iterator, Sequence

from . import theme
from .formatting import clamp_spans, resolve_overlaps, table_rows
from .models import Outcome, Span, display_name

CURRENT_TAG = "opf_current"


def span_tag(label: str) -> str:
    return f"opf_span::{label}"


def _offset_index(offset: int) -> str:
    return f"1.0+{max(0, int(offset))}c"


class TabDeck(ctk.CTkFrame):
    """A tabbed pane without a tab strip: pages share one cell, one is visible.

    ``CTkTabview`` draws its strip inside its own frame, which costs the page
    area a ~42 px band, and it centres that strip - so the strip slid sideways
    and the editors resized every time a page asked for a different width. The
    app keeps the switch in the top banner instead, which lets the pages fill
    their column and keeps both text panes the same size in every view.

    ``tab()``/``set()``/``get()`` mirror the ``CTkTabview`` calls they replace.
    """

    def __init__(self, master: Any, pages: Sequence[str], **kwargs: Any) -> None:
        kwargs.setdefault("corner_radius", 6)
        super().__init__(master, **kwargs)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._pages: dict[str, Any] = {name: ctk.CTkFrame(self) for name in pages}
        self._current = ""
        if pages:
            self.set(pages[0])

    def tab(self, name: str) -> Any:
        """The page frame for ``name``."""
        try:
            return self._pages[name]
        except KeyError:
            raise KeyError(f"unknown view {name!r}") from None

    def get(self) -> str:
        return self._current

    def set(self, name: str) -> None:
        """Show the page ``name``; the page it replaces is unmapped, not destroyed."""
        page = self.tab(name)
        if self._current and self._current != name:
            self._pages[self._current].grid_forget()
        page.grid(row=0, column=0, sticky="nsew")
        self._current = name


class TextPane(tk.Frame):
    """Scrollable text editor/viewer with per-PII-label colour tags."""

    def __init__(
        self,
        master: tk.Misc,
        *,
        height: int = 12,
        wrap: str = "word",
        font: tuple[Any, ...],
        readonly: bool = False,
        undo: bool = True,
        on_change: Callable[[], None] | None = None,
        on_select_span: Callable[[Span], None] | None = None,
        bg: str = "#1f1f27",
        fg: str = "#e8e8ee",
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._font = font
        self._readonly = readonly
        self._on_change = on_change
        self._on_select_span = on_select_span
        self._spans: list[Span] = []
        self._mode = "dark"
        self._suppress_change = False

        self.text = tk.Text(
            self,
            height=height,
            wrap=wrap,
            font=font,
            bg=bg,
            fg=fg,
            insertbackground=fg,
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=theme.pane_colors(self._mode)["border"],
            highlightcolor=theme.pane_colors(self._mode)["active"],
            undo=undo,
            padx=8,
            pady=8,
            selectbackground=theme.pane_colors(self._mode)["select_bg"],
            selectforeground=theme.pane_colors(self._mode)["select_fg"],
        )
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.text.tag_configure(
            CURRENT_TAG, underline=True, borderwidth=2, relief="solid"
        )
        self.text.bind("<Key>", self._guard_key, add=False)
        self.text.bind("<<Paste>>", self._on_paste, add=True)
        if on_change is not None:
            self.text.bind("<<Modified>>", self._on_modified, add=True)
        if on_select_span is not None:
            self.text.bind("<Button-1>", self._on_click, add=True)
            self.text.bind("<Double-Button-3>", self._on_click, add=True)

    # ------------------------------------------------------------------ #
    # basic editing
    # ------------------------------------------------------------------ #
    def _guard_key(self, event: tk.Event) -> str | None:
        return "break" if self._readonly else None

    def _on_paste(self, _event: tk.Event) -> None:
        if self._readonly:
            return "break"
        return None

    def _on_modified(self, _event: tk.Event) -> None:
        if self.text.edit_modified():
            if not self._suppress_change and self._on_change is not None:
                self._on_change()
            self.text.edit_modified(False)

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, content: str) -> None:
        # Replacing the whole document invalidates any previously positioned
        # highlights: their character offsets were anchored to the old text.  Clear
        # them so a freshly loaded file shows no stale PII marks until a fresh
        # redaction is run (callers that still want marks re-apply them via
        # set_spans() immediately after, e.g. the Review pane).
        self._spans = []
        self._suppress_change = True
        try:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", content)
            self.text.edit_modified(False)
        finally:
            self._suppress_change = False
        self.refresh_tags()

    def append(self, content: str) -> None:
        self.text.insert("end", content)
        self.text.see("end")

    def clear(self) -> None:
        self.set("")

    def set_readonly(self, readonly: bool) -> None:
        self._readonly = bool(readonly)

    def focus_input(self) -> None:
        self.text.focus_set()

    def select_all(self) -> None:
        self.text.tag_add("sel", "1.0", "end")

    # ------------------------------------------------------------------ #
    # highlighting
    # ------------------------------------------------------------------ #
    def set_spans(self, spans: Sequence[Span]) -> None:
        self._spans = list(spans)
        self.refresh_tags()

    def clear_spans(self) -> None:
        self._spans = []
        self.refresh_tags()

    def hidden_span_count(self) -> int:
        _visible, hidden = resolve_overlaps(self._spans)
        return len(hidden)

    def refresh_tags(self) -> None:
        """Re-apply every colour tag for the current appearance mode."""
        colors = theme.pane_colors(self._mode)
        self.text.tag_remove("opf_span", "1.0", "end")
        for label in theme.known_labels():
            self.text.tag_remove(span_tag(label), "1.0", "end")
        self.text.tag_raise(CURRENT_TAG)
        self.text.tag_config(
            CURRENT_TAG,
            underline=True,
            borderwidth=2,
            relief="solid",
            background=colors["active"],
            foreground=colors["select_fg"],
        )

        spans = clamp_spans(self.get(), self._spans)
        visible, _hidden = resolve_overlaps(spans)
        for span in visible:
            tag = span_tag(span.label)
            self.text.tag_config(
                tag,
                background=theme.span_bg(span.label, self._mode),
                foreground=theme.span_fg(span.label, self._mode),
            )
            self.text.tag_add(tag, _offset_index(span.start), _offset_index(span.end))

    def locate(self, span: Span) -> None:
        """Scroll to and emphasise one span."""
        self.text.tag_remove(CURRENT_TAG, "1.0", "end")
        start = _offset_index(span.start)
        end = _offset_index(span.end)
        self.text.tag_add(CURRENT_TAG, start, end)
        self.text.tag_raise(CURRENT_TAG)
        self.text.see(start)

    def span_at(self, index: str) -> Span | None:
        """Return the tightest span covering ``index`` (used for clicks)."""
        offset = _index_to_offset(self.text, index)
        candidates = [span for span in self._spans if span.start <= offset < span.end]
        if not candidates:
            return None
        return min(candidates, key=lambda span: span.length)

    # ------------------------------------------------------------------ #
    # appearance
    # ------------------------------------------------------------------ #
    def apply_appearance(self, mode: str, font: tuple[Any, ...] | None = None) -> None:
        self._mode = "dark" if mode != "light" else "light"
        colors = theme.pane_colors(self._mode)
        options: dict[str, Any] = {
            "bg": colors["bg"],
            "fg": colors["fg"],
            "insertbackground": colors["insert"],
            "selectbackground": colors["select_bg"],
            "selectforeground": colors["select_fg"],
            "highlightbackground": colors["border"],
        }
        if font is not None:
            self._font = font
            options["font"] = font
        self.text.configure(**options)
        self.configure(bg=colors["bg"])
        self.refresh_tags()

    def set_font(self, font: tuple[Any, ...]) -> None:
        self._font = font
        self.text.configure(font=font)

    # ------------------------------------------------------------------ #
    def _on_click(self, event: tk.Event) -> None:
        if self._on_select_span is None:
            return None
        index = self.text.index(f"@{event.x},{event.y}")
        span = self.span_at(index)
        if span is not None:
            self.locate(span)
            self._on_select_span(span)
        return "break" if self._readonly else None


def _index_to_offset(widget: tk.Text, index: str) -> int:
    """Convert a tkinter text index into a character offset from the start.

    ``widget.index()`` always normalises to ``line.column``, so the offset is the
    length of the preceding text plus the column - more reliable than
    ``Text.count``, which needs ``-update`` to be meaningful.
    """
    normalized = widget.index(index)
    line_part, _, column_part = str(normalized).partition(".")
    try:
        line = int(line_part)
        column = int(column_part)
    except ValueError:
        return 0
    prefix = widget.get("1.0", f"{line}.0")
    return len(prefix) + column


class SpanTable(ttk.Frame):
    """Colour-coded table of detected spans."""

    COLUMNS = ("idx", "label", "text", "chars", "offset", "placeholder")
    HEADINGS = (
        ("idx", "#", 34),
        ("label", "Category", 120),
        ("text", "Matched text", 280),
        ("chars", "Chars", 52),
        ("offset", "Offsets", 84),
        ("placeholder", "Placeholder", 150),
    )

    def __init__(
        self,
        master: tk.Misc,
        *,
        font: tuple[Any, ...],
        on_select: Callable[[Span], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(master, **kwargs)
        self._spans: list[Span] = []
        self._on_select = on_select
        self._mode = "dark"
        self._font = font

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Opf.Treeview",
            rowheight=max(22, int(font[1] * 1.7)) if len(font) > 1 else 24,
        )

        self.tree = ttk.Treeview(
            self,
            columns=self.COLUMNS,
            show="headings",
            style="Opf.Treeview",
            selectmode="browse",
        )
        for key, title, width in self.HEADINGS:
            self.tree.heading(key, text=title)
            anchor = "w" if key in {"text", "label", "placeholder"} else "e"
            self.tree.column(key, width=width, anchor=anchor, stretch=key == "text")

        self.v_scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.h_scroll = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=self.v_scroll.set, xscrollcommand=self.h_scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def populate(self, spans: Sequence[Span]) -> None:
        self._spans = list(spans)
        self.tree.delete(*self.tree.get_children())
        for row in table_rows(spans):
            self.tree.insert("", "end", values=row, tags=(row[1],))
        self.apply_appearance(self._mode)

    def selected_span(self) -> Span | None:
        selection = self.tree.selection()
        if not selection:
            return None
        children = self.tree.get_children()
        try:
            position = list(children).index(selection[0])
        except ValueError:
            return None
        if 0 <= position < len(self._spans):
            return self._spans[position]
        return None

    def _on_tree_select(self, _event: tk.Event) -> None:
        if self._on_select is not None:
            span = self.selected_span()
            if span is not None:
                self._on_select(span)

    def apply_appearance(self, mode: str) -> None:
        self._mode = "dark" if mode != "light" else "light"
        colors = theme.pane_colors(self._mode)
        style = ttk.Style(self)
        style.configure(
            "Opf.Treeview",
            background=colors["bg"],
            fieldbackground=colors["bg"],
            foreground=colors["fg"],
            bordercolor=colors["border"],
            lightcolor=colors["bg"],
            darkcolor=colors["bg"],
            font=self._font,
        )
        style.configure(
            "Opf.Treeview.Heading",
            background=colors["border"],
            foreground=colors["fg"],
            relief="flat",
            font=self._font,
        )
        style.configure(
            "TFrame",
            background=colors["bg"]
        )
        style.map(
            "Opf.Treeview",
            background=[("selected", colors["active"])],
            foreground=[("selected", colors["select_fg"])],
        )
        style.map(
            "Opf.Treeview.Heading",
            background=[("active", colors["active"])],
            foreground=[("selected", colors["select_fg"])],
        )
        # REMOVE OR COMMENT OUT THIS LINE:
        # self.configure(bg=colors["bg"])

        for label in theme.known_labels():
            self.tree.tag_configure(
                display_name(label),
                background=theme.span_bg(label, self._mode),
                foreground=theme.span_fg(label, self._mode),
            )
        self.tree.tag_configure(
            "unknown", background=colors["bg"], foreground=colors["fg"]
        )


class Legend(tk.Frame):
    """Colour key with live per-category counts."""

    def __init__(self, master: tk.Misc, *, font: tuple[Any, ...], **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self._font = font
        self._mode = "dark"
        self._rows: dict[str, tuple[tk.Frame, tk.Label, tk.Label]] = {}
        self._total: tk.Label | None = None
        self.rebuild(theme.known_labels())

    def rebuild(self, labels: Sequence[str]) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._rows = {}
        self._total = None
        for label in labels:
            row = tk.Frame(self)
            swatch = tk.Frame(row, width=14, height=14)
            swatch.pack(side="left", padx=(0, 6))
            title = display_name(label)
            name = tk.Label(row, text=title, font=self._font, anchor="w")
            name.pack(side="left", fill="x", expand=True)
            count = tk.Label(row, text="", font=self._font, width=4, anchor="e")
            count.pack(side="right", padx=(6, 0))
            row.pack(fill="x", pady=1)
            self._rows[label] = (swatch, name, count)
            self._paint_row(label, swatch, name)
        self._total = tk.Label(self, text="0 span(s)", font=self._font, anchor="w")
        self._total.pack(fill="x", pady=(6, 0))
        self.apply_appearance(self._mode)

    def _paint_row(self, label: str, swatch: tk.Frame, name: tk.Label) -> None:
        colors = theme.pane_colors(self._mode)
        swatch.configure(
            bg=theme.span_bg(label, self._mode),
            highlightthickness=1,
            highlightbackground=colors["border"],
        )
        name.configure(bg=colors["bg"], fg=colors["fg"])

    def update_counts(self, outcome: Outcome | None) -> None:
        counts = outcome.by_label() if outcome else {}
        for label, (_swatch, _name, count) in self._rows.items():
            value = counts.get(label, 0)
            count.configure(text=str(value) if value else "")
        if self._total is not None:
            total = outcome.span_count if outcome else 0
            hidden = len(resolve_overlaps(outcome.spans)[1]) if outcome else 0
            suffix = f", {hidden} overlapped" if hidden else ""
            self._total.configure(text=f"{total} span(s){suffix}")

    def apply_appearance(self, mode: str) -> None:
        self._mode = "dark" if mode != "light" else "light"
        colors = theme.pane_colors(self._mode)
        self.configure(bg=colors["bg"])
        for child in self.winfo_children():
            child.configure(bg=colors["bg"])
        for label, (swatch, name, count) in self._rows.items():
            swatch.configure(
                bg=theme.span_bg(label, self._mode),
                highlightbackground=colors["border"],
            )
            name.configure(bg=colors["bg"], fg=colors["fg"])
            count.configure(bg=colors["bg"], fg=theme.span_accent(label, self._mode))
        if self._total is not None:
            self._total.configure(bg=colors["bg"], fg=colors["fg"])


class LogConsole:
    """Append-only activity log written into a read-only textbox.

    The Activity log tab keeps its ``Text`` widget in ``state="disabled"`` so the
    user cannot type into it - and a disabled Tk text widget refuses *programmatic*
    writes too (``TclError: readonly``). Every edit therefore happens inside
    :meth:`_writing`, which unlocks, edits and re-locks the widget.
    """

    MAX_LINES = 1500
    KEEP_LINES = 1000
    PREFIXES = {"info": "", "warn": "[warn] ", "error": "[error] "}
    #: foreground colours per level, (light mode, dark mode)
    LEVEL_TAGS = {"opf_warn": ("#8a5300", "#f2b134"), "opf_error": ("#a51d2d", "#ff6b6b")}

    def __init__(self, textbox: Any) -> None:
        self.textbox = textbox
        self._mode = "dark"
        self._tagged = False

    # ------------------------------------------------------------------ #
    @contextmanager
    def _writing(self) -> Iterator[None]:
        locked = False
        try:
            locked = str(self.textbox.cget("state")) == "disabled"
        except Exception:  # noqa: BLE001 - widget without a state option
            locked = False
        if locked:
            self.textbox.configure(state="normal")
        try:
            yield
        finally:
            if locked:
                self.textbox.configure(state="disabled")

    def _ensure_tags(self) -> None:
        if self._tagged:
            return
        index = 0 if self._mode == "light" else 1
        try:
            for tag, colors in self.LEVEL_TAGS.items():
                self.textbox.tag_config(tag, foreground=colors[index])
        except Exception:  # noqa: BLE001 - text widget without tag support still logs
            pass
        self._tagged = True

    def apply_appearance(self, mode: str) -> None:
        self._mode = "light" if mode == "light" else "dark"
        self._tagged = False
        self._ensure_tags()

    # ------------------------------------------------------------------ #
    def log(self, message: str, level: str = "info") -> None:
        self._ensure_tags()
        prefix = self.PREFIXES.get(level, "")
        tag = {"warn": "opf_warn", "error": "opf_error"}.get(level)
        stamp = datetime.now().strftime("%H:%M:%S")
        lines = str(message).splitlines() or [""]
        with self._writing():
            for line in lines:
                self.textbox.insert("end", f"{stamp} {prefix}{line}\n")
                if tag:
                    try:
                        self.textbox.tag_add(tag, "end-2l", "end-1l")
                    except Exception:  # noqa: BLE001
                        pass
            self._trim()
        self.textbox.see("end")

    def _trim(self) -> None:
        """Drop the oldest lines so a long session cannot grow without bound."""
        try:
            line_count = int(str(self.textbox.index("end-1c")).split(".")[0]) - 1
        except Exception:  # noqa: BLE001
            return
        if line_count > self.MAX_LINES:
            self.textbox.delete("1.0", f"{line_count - self.KEEP_LINES}.0")

    def clear(self) -> None:
        with self._writing():
            self.textbox.delete("1.0", "end")

    def text(self) -> str:
        return str(self.textbox.get("1.0", "end-1c"))
