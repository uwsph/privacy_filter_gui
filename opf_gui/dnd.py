"""Optional drag-and-drop support for text files, backed by tkinterdnd2/tkdnd.

Everything here degrades gracefully: if ``tkinterdnd2`` is not installed, or the
bundled ``tkdnd`` native library cannot be loaded, :func:`enable` returns
``None`` and the GUI simply keeps the Open button as the only import path.
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

DND_HINT = "Drag & drop of text files needs the optional package:  pip install tkinterdnd2"

_BRACED = re.compile(r"\{([^{}]*)\}|(\S+)")


#: tkdnd type constants live on the ``tkinterdnd2`` package (not on its
#: ``TkinterDnD`` submodule), so keep literals for when the import fails.
DND_FILES = "DND_Files"
COPY_ACTION = "copy"


def dnd_module() -> Any | None:
    """Return the ``tkinterdnd2`` package, or ``None`` when it is unavailable.

    The package re-exports ``TkinterDnD`` plus the ``DND_*``/``COPY`` constants and
    is what patches ``tkinter.BaseWidget`` with ``drop_target_register`` and
    ``dnd_bind`` - so importing it is enough to give every Tk widget those methods.
    """
    try:
        import tkinterdnd2  # noqa: PLC0415 - optional dependency
        from tkinterdnd2 import TkinterDnD  # noqa: F401, PLC0415 - installs BaseWidget hooks
    except Exception:  # noqa: BLE001 - ImportError, or a broken native lib
        return None
    return tkinterdnd2


def _loader(module: Any) -> Callable[[tk.Misc], Any] | None:
    """Find the function that loads tkdnd into an existing root."""
    tkdnd = getattr(module, "TkinterDnD", None)
    for name in ("require", "_require"):  # _require: tkinterdnd2 < 0.4
        loader = getattr(tkdnd, name, None)
        if callable(loader):
            return loader
    return None


def enable(root: tk.Misc) -> str | None:
    """Load the tkdnd package into an existing Tk root (customtkinter compatible).

    Returns the tkdnd version string, or ``None`` when drag-and-drop cannot be
    used. Must be called once, after the root window exists.
    """
    module = dnd_module()
    if module is None:
        return None
    loader = _loader(module)
    if loader is None:
        return None
    try:
        version = loader(root)
    except Exception:  # noqa: BLE001 - RuntimeError("Unable to load tkdnd library.")
        return None
    return str(version or "unknown")


def parse_drop_data(widget: tk.Misc, data: str) -> list[Path]:
    """Turn tkdnd's ``%D`` payload into paths.

    Dropped paths arrive as a Tcl list where names containing spaces are
    brace-quoted. ``splitlist`` handles that; the regex fallback covers builds
    where the payload is a plain string.
    """
    raw = data or ""
    items: list[str] = []
    try:
        items = list(widget.tk.splitlist(raw))
    except Exception:  # noqa: BLE001 - ValueError/TclError on odd payloads
        items = [braced or bare for braced, bare in _BRACED.findall(raw)]
    paths: list[Path] = []
    for item in items:
        cleaned = item.strip().strip('"')
        if cleaned:
            paths.append(Path(cleaned).expanduser())
    return paths


def filter_paths(paths: Sequence[Path], accepted: Iterable[str] | None = None) -> tuple[list[Path], list[Path]]:
    """Split a drop into (usable files, rejected items)."""
    allowed = {suffix.lower() for suffix in accepted or ()}
    files: list[Path] = []
    rejected: list[Path] = []
    for path in paths:
        if path.is_dir():
            files.append(path)  # callers expand folders for batch runs
        elif path.is_file() and (not allowed or path.suffix.lower() in allowed):
            files.append(path)
        else:
            rejected.append(path)
    return files, rejected


class DropZone:
    """A widget registered as a file drop target."""

    def __init__(
        self,
        widget: tk.Misc,
        on_files: Callable[[list[Path], list[Path]], None],
        *,
        accepted: Iterable[str] | None = None,
        on_enter: Callable[[list[Path]], None] | None = None,
        on_leave: Callable[[], None] | None = None,
    ) -> None:
        self.widget = widget
        self.on_files = on_files
        self.accepted = accepted
        self.on_enter = on_enter
        self.on_leave = on_leave
        self._module: Any = None
        self._bound: list[str] = []

    # ------------------------------------------------------------------ #
    def install(self, module: Any) -> bool:
        """Register the widget with tkdnd and wire the drop events."""
        self._module = module
        try:
            self.widget.drop_target_register(getattr(module, "DND_FILES", DND_FILES))
            for sequence, handler in (
                ("<<DropEnter>>", self._on_enter),
                ("<<DropPosition>>", self._on_position),
                ("<<DropLeave>>", self._on_leave),
                ("<<Drop>>", self._on_drop),
            ):
                self.widget.dnd_bind(sequence, handler)
                self._bound.append(sequence)
        except Exception:  # noqa: BLE001 - tkdnd not loaded, widget cannot bind
            self.remove()
            return False
        return True

    def remove(self) -> None:
        # func="" removes a binding; func=None would merely query it.
        for sequence in self._bound:
            try:
                self.widget.dnd_bind(sequence, "")
            except Exception:  # noqa: BLE001
                pass
        self._bound = []
        try:
            self.widget.drop_target_unregister()
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ #
    def _copy(self) -> str:
        # tkdnd expects the accepted action back from these callbacks.
        return str(getattr(self._module, "COPY", COPY_ACTION))

    def _event_paths(self, event: Any) -> list[Path]:
        return parse_drop_data(self.widget, getattr(event, "data", "") or "")

    def _on_enter(self, event: Any) -> str:
        if self.on_enter is not None:
            self.on_enter(self._event_paths(event))
        return self._copy()

    def _on_position(self, _event: Any) -> str:
        return self._copy()

    def _on_leave(self, _event: Any) -> None:
        if self.on_leave is not None:
            self.on_leave()
        return None

    def _on_drop(self, event: Any) -> str:
        paths = self._event_paths(event)
        try:
            files, rejected = filter_paths(paths, self.accepted)
            self.on_files(files, rejected)
        finally:
            if self.on_leave is not None:
                self.on_leave()
        return self._copy()


def register(widget: tk.Misc, on_files: Callable[[list[Path], list[Path]], None], **kwargs: Any) -> DropZone | None:
    """Register ``widget`` as a drop target; ``None`` when tkdnd is unavailable."""
    module = dnd_module()
    if module is None:
        return None
    zone = DropZone(widget, on_files, **kwargs)
    if not zone.install(module):
        return None
    return zone
