"""Minimal stand-ins for tkinter / customtkinter so the GUI layer is testable
without a display. Call :func:`install` BEFORE importing :mod:`opf_gui.app`.

The stubs are behavioural where it matters:
* ``Text`` stores content, resolves the index forms the app uses (``1.0``,
  ``end``, ``end-1c``, "1.0+7c", ``line.col``, ``@x,y``) and keeps tag ranges.
* ``Treeview`` stores rows and selection.
* ``CTk``/``CTkFrame`` record ``grid``/``pack`` so layout can be asserted.
* unknown widget methods are recorded in :data:`UNKNOWN_CALLS` instead of
  raising, so gaps in the stub (or bugs in the app) stay visible.
"""

from __future__ import annotations

import re
import sys
import types
from typing import Any, Callable

UNKNOWN_CALLS: set[str] = set()
MESSAGEBOX_CALLS: list[tuple[str, tuple[Any, ...]]] = []
DIALOG_ANSWERS: dict[str, Any] = {}
CLIPBOARD: list[str] = []
APPEARANCE: dict[str, str] = {"mode": "Dark"}


class TclError(Exception):
    pass


class SimpleNamespace:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class Widget:
    """Base stub: layout no-ops, config storage, call recording."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        self.master = master
        self.options = dict(kwargs)
        self.children: list[Any] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.grid_info_now: dict[str, str] = {}
        self._bindings: dict[str, Callable[..., Any]] = {}
        self._row_config: dict[int, dict[str, Any]] = {}
        self._col_config: dict[int, dict[str, Any]] = {}
        if isinstance(master, Widget):
            master.children.append(self)

    # ---------------- layout ---------------- #
    def _record(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, dict(kwargs)))
        if name == "grid":
            self.grid_info_now = {str(k): v for k, v in kwargs.items()}

    def pack(self, **kwargs: Any) -> None:
        self._record("pack", kwargs)

    def grid(self, **kwargs: Any) -> None:
        self._record("grid", kwargs)

    def place(self, **kwargs: Any) -> None:
        self._record("place", kwargs)

    def grid_remove(self) -> None:
        self._record("grid_remove", {})

    def grid_forget(self) -> None:
        self._record("grid_forget", {})

    def pack_forget(self) -> None:
        self._record("pack_forget", {})

    def _grid_config(self, table: dict[Any, dict[str, Any]], index: Any, cnf: Any, kw: dict[str, Any]) -> Any:
        """Shared logic for grid_rowconfigure/grid_columnconfigure."""
        if isinstance(cnf, str) and not kw:
            # query form: grid_rowconfigure(0, "minsize") -> Tcl string
            key = cnf.lstrip("-")
            return str(table.get(index, {}).get(key, ""))
        values = dict(cnf or {})
        values.update({key.lstrip("-"): value for key, value in kw.items()})
        table.setdefault(index, {}).update(values)
        return None

    def grid_rowconfigure(self, index: Any, cnf: Any = None, **kw: Any) -> Any:
        return self._grid_config(self._row_config, int(index), cnf, kw)

    def grid_columnconfigure(self, index: Any, cnf: Any = None, **kw: Any) -> Any:
        return self._grid_config(self._col_config, str(index), cnf, kw)

    rowconfigure = grid_rowconfigure
    columnconfigure = grid_columnconfigure

    # ---------------- config ---------------- #
    def configure(self, **kwargs: Any) -> None:
        self.options.update(kwargs)
        self._record("configure", kwargs)

    def config(self, **kwargs: Any) -> None:
        self.configure(**kwargs)

    def cget(self, key: str) -> Any:
        return self.options.get(key, "")

    def __setitem__(self, key: str, value: Any) -> None:
        self.options[key] = value

    def __getitem__(self, key: str) -> Any:
        return self.options.get(key, "")

    # ---------------- events ---------------- #
    def bind(self, sequence: str = "", func: Callable[..., Any] | None = None, add: Any = None) -> str:
        if func is not None:
            self._bindings[sequence] = func
        return f"bind#{id(func)}"

    def bind_all(self, sequence: str = "", func: Callable[..., Any] | None = None, add: Any = None) -> str:
        return self.bind(sequence, func, add)

    def unbind(self, sequence: str = "", funcid: Any = None) -> None:
        self._bindings.pop(sequence, None)

    def event_generate(self, sequence: str, **kwargs: Any) -> None:
        handler = self._bindings.get(sequence)
        if handler is not None:
            handler(SimpleNamespace(**kwargs))

    def protocol(self, name: str = "", func: Callable[..., Any] | None = None) -> None:
        if func is not None:
            self._bindings[f"protocol::{name}"] = func

    # ---------------- misc ---------------- #
    def winfo_children(self) -> list[Any]:
        return list(self.children)

    def winfo_exists(self) -> bool:
        return True

    def winfo_width(self) -> int:
        return int(self.options.get("width", 800))

    def winfo_toplevel(self) -> Any:
        node = self
        while isinstance(node.master, Widget):
            node = node.master
        return node

    def focus_set(self) -> None:
        self._record("focus_set", {})

    def focus_force(self) -> None:
        self._record("focus_force", {})

    def update_idletasks(self) -> None:
        pass

    def update(self) -> None:
        pass

    def destroy(self) -> None:
        self._record("destroy", {})
        children = getattr(self.master, "children", None)
        if isinstance(children, list) and self in children:
            children.remove(self)

    def after(self, milliseconds: int, func: Callable[..., Any] | None = None, *args: Any) -> str:
        self._record("after", {"ms": milliseconds, "func": bool(func)})
        return f"after#{milliseconds}"

    def after_cancel(self, name: Any) -> None:
        self._record("after_cancel", {"id": name})

    def title(self, text: str | None = None) -> str:
        if text is not None:
            self.options["title"] = text
        return str(self.options.get("title", ""))

    def geometry(self, value: str | None = None) -> str:
        if value is not None:
            self.options["geometry"] = value
        return str(self.options.get("geometry", ""))

    def minsize(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    def mainloop(self) -> None:
        self._record("mainloop", {})

    def withdraw(self) -> None:
        pass

    def transient(self, master: Any = None) -> None:
        self.options["transient"] = master

    def grab_set(self) -> None:
        self.options["grab"] = True

    def grab_release(self) -> None:
        self.options.pop("grab", None)

    def clipboard_clear(self) -> None:
        CLIPBOARD.clear()

    def clipboard_append(self, text: str) -> None:
        CLIPBOARD.append(text)

    def clipboard_get(self) -> str:
        if not CLIPBOARD:
            raise TclError("clipboard empty")
        return "".join(CLIPBOARD)

    def __getattr__(self, name: str) -> Callable[..., None]:
        if name.startswith("_"):
            raise AttributeError(name)
        UNKNOWN_CALLS.add(f"{type(self).__name__}.{name}")

        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


_INDEX = re.compile(r"^(\d+)\.(\d+)$")
_INDEX_DELTA = re.compile(r"^(\d+)\.(\d+)\+(-?\d+)c$")
_END_DELTA = re.compile(r"^end([+-]\d+)c?$")
_END_LINE = re.compile(r"^end([+-]\d+)l$")


class Text(Widget):
    """Working mini-Text: content, indices, tags."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self._content = ""
        self._insert = 0
        self._click = 0
        self._tags: dict[str, list[tuple[int, int]]] = {}
        self._tag_options: dict[str, dict[str, Any]] = {}
        self._modified = False
        self.raised: list[str] = []
        self.seen: list[str] = []

    # ---- indices ---- #
    def _line_start(self, line: int) -> int:
        offset = 0
        for _ in range(max(0, line - 1)):
            found = self._content.find("\n", offset)
            if found == -1:
                return len(self._content)
            offset = found + 1
        return offset

    def _offset_of(self, index: Any) -> int:
        raw = str(index).strip()
        # Tk keeps an implicit trailing newline: `end` sits one character past
        # the stored text, `end-1c` is the real end of the user's text.
        if raw == "end":
            return len(self._content) + 1
        if raw in {"insert", "current"}:
            return min(self._insert, len(self._content))
        if raw == "end-1c":
            return len(self._content)
        if raw in {"sel.first", "sel.last"}:
            return min(self._insert, len(self._content))
        if raw.startswith("@"):
            return max(0, min(self._click, len(self._content)))
        match = _INDEX_DELTA.match(raw)
        if match:
            line, column, delta = (int(match.group(i)) for i in (1, 2, 3))
            return max(0, min(self._line_start(line) + column + delta, len(self._content)))
        match = _INDEX.match(raw)
        if match:
            return max(0, min(self._line_start(int(match.group(1))) + int(match.group(2)), len(self._content)))
        match = _END_DELTA.match(raw)
        if match:
            return max(0, min(len(self._content) + 1 + int(match.group(1)), len(self._content) + 1))
        match = _END_LINE.match(raw)
        if match:
            end_line = self._content.count("\n", 0, len(self._content) + 1) + 1
            return self._line_start(max(1, end_line + int(match.group(1))))
        raise TclError(f"bad text index: {index!r}")

    def _check_writable(self) -> None:
        """A disabled Text widget refuses every edit, just like Tk does."""
        if str(self.options.get("state", "normal")) == "disabled":
            raise TclError("readonly")

    def index(self, index: Any) -> str:
        offset = self._offset_of(index)
        line = self._content.count("\n", 0, offset) + 1
        return f"{line}.{offset - self._line_start(line)}"

    def count(self, start: Any, stop: Any, *_a: Any) -> tuple[int, ...]:
        return (self._offset_of(stop) - self._offset_of(start),)

    # ---- content ---- #
    def get(self, start: Any = "1.0", stop: Any | None = None) -> str:
        first = min(self._offset_of(start), len(self._content))
        last = len(self._content) if stop is None else min(self._offset_of(stop), len(self._content))
        return self._content[first:max(first, last)]

    def insert(self, index: Any, content: str, tags: Any = None) -> None:
        self._check_writable()
        offset = len(self._content) if str(index) in {"end", "insert"} else self._offset_of(index)
        offset = min(offset, len(self._content))
        self._content = self._content[:offset] + content + self._content[offset:]
        self._insert = offset + len(content)
        self._modified = True
        if tags:
            names = [tags] if isinstance(tags, str) else list(tags)
            for name in names:
                self._tags.setdefault(name, []).append((offset, offset + len(content)))

    def delete(self, start: Any, stop: Any | None = None) -> None:
        self._check_writable()
        first = min(self._offset_of(start), len(self._content))
        last = min(self._offset_of(stop), len(self._content)) if stop is not None else first + 1
        self._content = self._content[:first] + self._content[max(first, last):]
        self._insert = min(self._insert, len(self._content))
        self._modified = True

    def replace(self, start: Any, stop: Any, content: str) -> None:
        self.delete(start, stop)
        self.insert(start, content)

    def edit_modified(self, flag: Any = None) -> Any:
        if flag is None:
            return self._modified
        self._modified = bool(flag)
        return None

    def edit_reset(self) -> None:
        self._modified = False

    def see(self, index: Any) -> None:
        self.seen.append(str(index))

    def yview(self, *_a: Any) -> tuple[float, float]:
        return (0.0, 1.0)

    def xview(self, *_a: Any) -> tuple[float, float]:
        return (0.0, 1.0)

    def dlineinfo(self, index: Any) -> tuple[int, int, int, int, int]:
        return (0, 0, 10, 10, 0)

    def bbox(self, index: Any) -> tuple[int, int, int, int] | None:
        return (0, 0, 10, 10)

    def tag_config(self, name: str, *args: Any, **kwargs: Any) -> None:
        if args:
            self._record("tag_config_WITH_OPTION_INDEX", {"tag": name, "args": args})
        self._tag_options.setdefault(name, {}).update(kwargs)

    tag_configure = tag_config

    def tag_cget(self, name: str, option: str) -> Any:
        return self._tag_options.get(name, {}).get(option)

    def tag_add(self, name: str, start: Any, stop: Any) -> None:
        span = (self._offset_of(start), self._offset_of(stop))
        ranges = self._tags.setdefault(name, [])
        if span not in ranges:
            ranges.append(span)

    def tag_remove(self, name: str, start: Any, stop: Any) -> None:
        first, last = self._offset_of(start), self._offset_of(stop)
        self._tags[name] = [
            span for span in self._tags.get(name, []) if not (span[0] < last and first < span[1])
        ]

    def tag_ranges(self, name: str) -> tuple[str, ...]:
        def as_index(offset: int) -> str:
            line = self._content.count("\n", 0, offset) + 1
            return f"{line}.{offset - self._line_start(line)}"

        flat: list[str] = []
        for start, stop in self._tags.get(name, []):
            flat.extend([as_index(start), as_index(stop)])
        return tuple(flat)

    def tag_names(self, index: Any = None) -> tuple[str, ...]:
        if index is None:
            return tuple(self._tags)
        offset = self._offset_of(index)
        return tuple(
            name for name, ranges in self._tags.items()
            if any(low <= offset < high for low, high in ranges)
        )

    def tag_raise(self, name: str, above: Any = None) -> None:
        self.raised.append(name)

    def tag_delete(self, *names: str) -> None:
        for name in names:
            self._tags.pop(name, None)
            self._tag_options.pop(name, None)

    # ---- test helpers ---- #
    @property
    def content(self) -> str:
        return self._content

    def tag_offsets(self, name: str) -> list[tuple[int, int]]:
        """Resolved (start, stop) character offsets for a tag."""
        return list(self._tags.get(name, []))

    def set_click(self, offset: int) -> None:
        self._click = offset


# --------------------------------------------------------------------------- #
# ttk
# --------------------------------------------------------------------------- #
class Style(Widget):
    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.themes: list[str] = []
        self.settings: dict[str, dict[str, Any]] = {}

    def theme_use(self, name: str | None = None) -> str:
        if name is not None:
            self.themes.append(name)
        return "clam"

    def theme_configure(self, **kwargs: Any) -> None:
        self._record("theme_configure", kwargs)

    def configure(self, style: str = "", **kwargs: Any) -> None:  # type: ignore[override]
        self.settings.setdefault(style, {}).update(kwargs)

    def map(self, style: str = "", **kwargs: Any) -> None:
        self.settings.setdefault(f"{style}::map", {}).update(kwargs)

    def lookup(self, *_args: Any, **_kwargs: Any) -> str:
        return ""


class Treeview(Widget):
    def __init__(self, master: Any = None, *, columns: Any = None, **kwargs: Any) -> None:
        super().__init__(master, columns=list(columns or []), **kwargs)
        self._rows: list[tuple[str, tuple[Any, ...], tuple[Any, ...]]] = []
        self._selection: tuple[str, ...] = ()
        self._row_tags: dict[str, dict[str, Any]] = {}
        self._counter = 0
        self.headings: dict[str, dict[str, Any]] = {}
        self.col_options: dict[str, dict[str, Any]] = {}

    def heading(self, column: str = "", **kwargs: Any) -> None:
        self.headings.setdefault(column, {}).update(kwargs)

    def column(self, column: str = "", **kwargs: Any) -> None:
        self.col_options.setdefault(column, {}).update(kwargs)

    def insert(self, parent: Any = "", index: Any = "end", iid: str | None = None,
               values: Any = None, tags: Any = None, **_kwargs: Any) -> str:
        self._counter += 1
        row_id = iid or f"Iid{self._counter}"
        self._rows.append((row_id, tuple(values or ()), tuple(tags or ())))
        return row_id

    def delete(self, *items: Any) -> None:
        if not items:
            return
        if items == ("all",):
            self._rows = []
            return
        wanted = set(items[0]) if len(items) == 1 and hasattr(items[0], "__iter__") else set(items)
        self._rows = [row for row in self._rows if row[0] not in wanted]

    def get_children(self, _parent: Any = "") -> tuple[str, ...]:
        return tuple(row_id for row_id, _v, _t in self._rows)

    def item(self, item: str, key: str | None = None, **_kwargs: Any) -> Any:
        for row_id, values, tags in self._rows:
            if row_id == item:
                if key == "values":
                    return values
                if key == "tags":
                    return tags
                return {"values": values, "tags": tags}
        return {}

    def selection(self) -> tuple[str, ...]:
        return self._selection

    def selection_set(self, items: Any) -> None:
        self._selection = tuple(items)

    def tag_configure(self, name: str, **kwargs: Any) -> None:
        self._row_tags.setdefault(name, {}).update(kwargs)

    tag_config = tag_configure

    def tag_cget(self, name: str, key: str) -> Any:
        return self._row_tags.get(name, {}).get(key)

    def identify_row(self, _y: int) -> str:
        return self._rows[0][0] if self._rows else ""

    def yview_moveto(self, *_args: Any) -> None:
        pass

    # ---- test helpers ---- #
    def rows(self) -> list[tuple[Any, ...]]:
        return [row_values for _row_id, row_values, _tags in self._rows]

    def select_row(self, index: int = 0) -> None:
        if not self._rows:
            return
        self._selection = (self._rows[index][0],)
        handler = self._bindings.get("<<TreeviewSelect>>")
        if handler:
            handler(SimpleNamespace())


class Variable:
    _DEFAULT: Any = ""

    def __init__(self, master: Any = None, value: Any = None, **_: Any) -> None:
        self._value = self._DEFAULT if value is None else value

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value

    def trace_add(self, *_args: Any) -> str:
        return "trace"

    def trace_variable(self, *_args: Any) -> str:
        return "trace"


class StringVar(Variable):
    _DEFAULT = ""


class BooleanVar(Variable):
    _DEFAULT = False


class IntVar(Variable):
    _DEFAULT = 0


class DoubleVar(Variable):
    _DEFAULT = 0.0


class Menu(Widget):
    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.entries: list[tuple[str, dict[str, Any]]] = []

    def add_cascade(self, **kwargs: Any) -> None:
        self.entries.append(("cascade", kwargs))

    def add_command(self, **kwargs: Any) -> None:
        self.entries.append(("command", kwargs))

    def add_separator(self, **kwargs: Any) -> None:
        self.entries.append(("separator", kwargs))


# --------------------------------------------------------------------------- #
# customtkinter
# --------------------------------------------------------------------------- #
class CTkTextbox(Text):
    """customtkinter's textbox offers a Text-like facade."""


class CTkFont(Widget):
    def __init__(self, master: Any = None, *, size: int = 12, weight: str = "normal",
                 family: str = "", **kwargs: Any) -> None:
        super().__init__(master, size=size, weight=weight, family=family, **kwargs)
        self.size = size
        self.weight = weight

    def configure(self, **kwargs: Any) -> None:  # type: ignore[override]
        self.size = kwargs.get("size", self.size)
        self.weight = kwargs.get("weight", self.weight)
        self.options.update(kwargs)

    def cget(self, key: str) -> Any:
        return getattr(self, key, self.options.get(key))


class CTkTabview(Widget):
    """Emulates the tabview geometry: 3 header rows then the content rows."""

    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self._tabs: dict[str, Widget] = {}
        self._current: str | None = None
        for row, minsize in ((0, 10.0), (1, 8.0), (2, 18.0)):
            self._row_config[row] = {"weight": 0, "minsize": minsize}
        self._row_config[3] = {"weight": 1, "minsize": 0}

    def add(self, name: str) -> Widget:
        frame = CTkFrame(self, tab_name=name)
        self._tabs[name] = frame
        if self._current is None:
            self._current = name
        return frame

    def tab(self, name: str) -> Widget:
        if name not in self._tabs:
            raise KeyError(f"unknown tab {name!r}")
        return self._tabs[name]

    def set(self, name: str) -> None:
        if name in self._tabs:
            self._current = name

    def get(self) -> str:
        return self._current or ""


class CTkSwitch(Widget):
    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self._selected = False
        self._command: Callable[..., Any] | None = kwargs.get("command")
        self._variable = kwargs.get("variable")

    def select(self) -> None:
        self._selected = True
        if self._variable is not None:
            self._variable.set(True)

    def deselect(self) -> None:
        self._selected = False
        if self._variable is not None:
            self._variable.set(False)

    def toggle(self) -> None:
        (self.deselect if self._selected else self.select)()
        if self._command:
            self._command()

    def get(self) -> Any:
        return self._variable.get() if self._variable is not None else self._selected

    def invoke(self) -> None:
        self.toggle()


class CTkCheckBox(CTkSwitch):
    pass


class CTkButton(Widget):
    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.command = kwargs.get("command")
        self.text = kwargs.get("text", "")

    def invoke(self) -> None:
        if self.command is not None:
            self.command()

    def get(self) -> str:
        return str(self.text)


class _ChoiceWidget(Widget):
    """Segmented buttons and option menus, both used as single-choice pickers."""

    #: customtkinter's CTkOptionMenu opens on its first value; a segmented button
    #: starts with NOTHING selected (`_current_value = ""`) until set() or a
    #: variable picks one - which is why an app must set() its view switch.
    DEFAULT_TO_FIRST = True

    def __init__(self, master: Any = None, *, values: list[str] | None = None, **kwargs: Any) -> None:
        super().__init__(master, values=list(values or []), **kwargs)
        self.values = list(values or [])
        self._command: Callable[..., Any] | None = kwargs.get("command")
        self._variable = kwargs.get("variable")
        if self._variable is not None:
            self._value = self._variable.get()
        elif self.values and self.DEFAULT_TO_FIRST:
            self._value = self.values[0]
        else:
            self._value = ""

    def set(self, value: Any) -> None:
        # customtkinter's set() deliberately does NOT fire command.
        self._value = value
        if self._variable is not None:
            self._variable.set(value)

    def get(self) -> Any:
        return self._variable.get() if self._variable is not None else self._value

    def choose(self, value: Any) -> None:
        """Simulate a user click, which does fire command."""
        self.set(value)
        if self._command is not None:
            self._command(value)


class CTkSegmentedButton(_ChoiceWidget):
    DEFAULT_TO_FIRST = False


class CTkOptionMenu(_ChoiceWidget):
    pass


class CTkEntry(Widget):
    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self._variable = kwargs.get("textvariable")

    def get(self) -> str:
        if self._variable is not None:
            return str(self._variable.get())
        return str(self.options.get("text", ""))

    def delete(self, *_args: Any) -> None:
        if self._variable is not None:
            self._variable.set("")

    def insert(self, _index: Any, content: str) -> None:
        if self._variable is not None:
            self._variable.set(content)


class CTkProgressBar(Widget):
    def __init__(self, master: Any = None, **kwargs: Any) -> None:
        super().__init__(master, **kwargs)
        self.running = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def set(self, _value: float) -> None:
        pass


CTkFrame = type("CTkFrame", (Widget,), {})
CTkLabel = type("CTkLabel", (Widget,), {})
CTkScrollableFrame = type("CTkScrollableFrame", (Widget,), {})


# --------------------------------------------------------------------------- #
# module assembly
# --------------------------------------------------------------------------- #
def _build_tkinter() -> types.ModuleType:
    tkinter = types.ModuleType("tkinter")
    for name, value in {
        "TclError": TclError, "Misc": Widget, "Widget": Widget, "Frame": Widget,
        "Text": Text, "Menu": Menu, "StringVar": StringVar, "BooleanVar": BooleanVar,
        "IntVar": IntVar, "DoubleVar": DoubleVar, "Variable": Variable,
        "Event": SimpleNamespace, "Toplevel": type("Toplevel", (Widget,), {}),
        "Tk": type("Tk", (Widget,), {}), "Canvas": type("Canvas", (Widget,), {}),
        "Label": CTkLabel, "Scrollbar": type("Scrollbar", (Widget,), {}),
        "BaseWidget": Widget,
    }.items():
        setattr(tkinter, name, value)
    for const, value in {
        "NORMAL": "normal", "DISABLED": "disabled", "READONLY": "readonly", "WORD": "word",
        "CHAR": "char", "NONE": "none", "LEFT": "left", "RIGHT": "right", "TOP": "top",
        "BOTTOM": "bottom", "BOTH": "both", "X": "x", "Y": "y", "N": "n", "S": "s", "E": "e",
        "W": "w", "NSEW": "nsew", "EW": "ew", "NS": "ns", "CENTER": "center", "SOLID": "solid",
        "FLAT": "flat", "RIDGE": "ridge", "GROOVE": "groove", "VERTICAL": "vertical",
        "HORIZONTAL": "horizontal", "END": "end", "INSERT": "insert", "SEL_FIRST": "sel.first",
        "SEL_LAST": "sel.last", "PRIVATE": "private", "COPY": "copy", "MOVE": "move",
        "ASK": "ask", "LINK": "link", "REFUSE_DROP": "refuse_drop",
    }.items():
        setattr(tkinter, const, value)

    ttk = types.ModuleType("tkinter.ttk")
    ttk.Style = Style
    ttk.Treeview = Treeview
    for name in ("Frame", "Label", "Button", "Entry", "Combobox", "Notebook", "Progressbar",
                 "Scrollbar", "Checkbutton", "Radiobutton", "Separator", "Sizegrip",
                 "Labelframe"):
        setattr(ttk, name, type(name, (Widget,), {}))
    ttk.LabelFrame = ttk.Labelframe

    font = types.ModuleType("tkinter.font")
    font.families = lambda *_a, **_k: [
        "Segoe UI", "Consolas", "DejaVu Sans Mono", "Menlo", "Courier", "Arial", "Helvetica"
    ]

    class _TkFont(Widget):
        def __init__(self, master: Any = None, *, size: int = 12, family: str = "", **kw: Any) -> None:
            super().__init__(master, size=size, family=family, **kw)

    font.Font = _TkFont

    filedialog = types.ModuleType("tkinter.filedialog")

    def _answer(key: str, default: Any) -> Any:
        value = DIALOG_ANSWERS.get(key, default)
        return value() if callable(value) else value

    filedialog.askopenfilenames = lambda **_kw: _answer("askopenfilenames", ())
    filedialog.askopenfilename = lambda **_kw: _answer("askopenfilename", "")
    filedialog.asksaveasfilename = lambda **_kw: _answer("asksaveasfilename", "")
    filedialog.askdirectory = lambda **_kw: _answer("askdirectory", "")

    messagebox = types.ModuleType("tkinter.messagebox")

    def _recorder(name: str):  # noqa: ANN202
        def _show(*args: Any, **_kwargs: Any) -> Any:
            MESSAGEBOX_CALLS.append((name, args))
            if name.startswith("ask"):
                return bool(DIALOG_ANSWERS.get(name, True))
            return "ok"

        return _show

    for name in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askyesnocancel"):
        setattr(messagebox, name, _recorder(name))

    constants = types.ModuleType("tkinter.constants")
    for name in dir(tkinter):
        if name.isupper():
            setattr(constants, name, getattr(tkinter, name))

    tkinter.ttk = ttk
    tkinter.font = font
    tkinter.filedialog = filedialog
    tkinter.messagebox = messagebox
    tkinter.constants = constants
    return tkinter


def _build_customtkinter(tkinter: types.ModuleType) -> types.ModuleType:
    ctk = types.ModuleType("customtkinter")
    ctk.__version__ = "6.0.0-stub"
    ctk.TclError = TclError
    for name in ("StringVar", "BooleanVar", "IntVar", "DoubleVar", "Variable", "Text", "Frame"):
        setattr(ctk, name, getattr(tkinter, name))
    for name in dir(tkinter.constants):
        if name.isupper():
            setattr(ctk, name, getattr(tkinter.constants, name))

    ctk.CTk = type("CTk", (Widget,), {})
    ctk.CTkToplevel = type("CTkToplevel", (Widget,), {})
    ctk.CTkTextbox = CTkTextbox
    ctk.CTkFont = CTkFont
    ctk.CTkTabview = CTkTabview
    ctk.CTkSwitch = CTkSwitch
    ctk.CTkCheckBox = CTkCheckBox
    ctk.CTkButton = CTkButton
    ctk.CTkSegmentedButton = CTkSegmentedButton
    ctk.CTkOptionMenu = CTkOptionMenu
    ctk.CTkEntry = CTkEntry
    ctk.CTkFrame = CTkFrame
    ctk.CTkLabel = CTkLabel
    ctk.CTkScrollableFrame = CTkScrollableFrame
    ctk.CTkProgressBar = CTkProgressBar
    for name in ("CTkCanvas", "CTkScrollbar", "CTkSlider", "CTkRadioButton", "CTkComboBox",
                 "CTkImage", "CTkInputDialog", "CTkBaseClass"):
        setattr(ctk, name, type(name, (Widget,), {}))

    def set_appearance_mode(mode: str) -> None:
        APPEARANCE["mode"] = {"dark": "Dark", "light": "Light", "system": "Dark"}.get(mode, str(mode))

    def get_appearance_mode() -> str:
        return APPEARANCE["mode"]

    def set_default_color_theme(value: str) -> None:
        if value not in {"blue", "dark-blue", "green"}:
            raise ValueError(f"unknown color theme: {value!r}")
        APPEARANCE["theme"] = value

    ctk.set_appearance_mode = set_appearance_mode
    ctk.get_appearance_mode = get_appearance_mode
    ctk.set_default_color_theme = set_default_color_theme
    for name in ("set_widget_scaling", "set_window_scaling", "deactivate_window_scaling",
                 "deactivate_widget_scaling"):
        setattr(ctk, name, lambda *_a: None)
    return ctk


def install() -> dict[str, types.ModuleType]:
    """Register the stub tkinter/customtkinter modules in sys.modules."""
    tkinter = _build_tkinter()
    ctk = _build_customtkinter(tkinter)
    modules = {
        "tkinter": tkinter,
        "tkinter.ttk": ttk_of(tkinter),
        "tkinter.font": tkinter.font,
        "tkinter.filedialog": tkinter.filedialog,
        "tkinter.messagebox": tkinter.messagebox,
        "tkinter.constants": tkinter.constants,
        "customtkinter": ctk,
    }
    for name, module in modules.items():
        sys.modules[name] = module
    return modules


def ttk_of(tkinter: types.ModuleType) -> types.ModuleType:
    return tkinter.ttk


def reset() -> None:
    """Clear recorded state between tests."""
    UNKNOWN_CALLS.clear()
    MESSAGEBOX_CALLS.clear()
    DIALOG_ANSWERS.clear()
    CLIPBOARD.clear()
    APPEARANCE.clear()
    APPEARANCE.update({"mode": "Dark", "theme": "blue"})
