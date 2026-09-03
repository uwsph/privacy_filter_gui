"""Colour palette and fonts for the Privacy Filter GUI.

Plain tkinter widgets (Text, Treeview) cannot use customtkinter's
``(dark, light)`` colour tuples, so every colour here is resolved for a
specific appearance mode.
"""

from __future__ import annotations

from .models import REDACTED_LABEL, PII_LABELS

# (dark-mode background, light-mode background)
SPAN_BG: dict[str, tuple[str, str]] = {
    "private_person": ("#6c3fb5", "#e6dbff"),
    "private_email": ("#1f6feb", "#d6e8ff"),
    "private_phone": ("#0e7a63", "#cdefe5"),
    "private_address": ("#8a5a12", "#ffe6c2"),
    "private_date": ("#9a3b5c", "#ffd9e4"),
    "private_url": ("#175f8a", "#d3f0ff"),
    "account_number": ("#7a5c00", "#fff0b8"),
    "secret": ("#9c2b2b", "#ffd3d3"),
    REDACTED_LABEL: ("#4a4a55", "#dcdce2"),
}

# (dark-mode foreground, light-mode foreground)
SPAN_FG: dict[str, tuple[str, str]] = {
    "private_person": ("#f3ecff", "#3b1266"),
    "private_email": ("#e8f1ff", "#0b3a75"),
    "private_phone": ("#e0fff7", "#07463a"),
    "private_address": ("#fff3e0", "#6b3f04"),
    "private_date": ("#ffe9f0", "#7a1e3c"),
    "private_url": ("#e4f6ff", "#08405f"),
    "account_number": ("#fff8dc", "#5c4500"),
    "secret": ("#ffeaea", "#7a1414"),
    REDACTED_LABEL: ("#f2f2f5", "#33333a"),
}

# Text colour for category accents - the per-category counts in the Detection
# summary. Light mode cannot reuse ``SPAN_BG`` pastels (e.g. #e6dbff on #fdfdfe
# is about 1.1:1, effectively invisible), so each light accent is the deep
# version of the same hue and clears WCAG AA (4.5:1) on the light pane.
# Dark mode keeps the existing highlight colours, which read well on charcoal.
SPAN_ACCENT: dict[str, tuple[str, str]] = {
    "private_person": ("#6c3fb5", "#5a2ca6"),
    "private_email": ("#1f6feb", "#1450b8"),
    "private_phone": ("#0e7a63", "#0a5c4b"),
    "private_address": ("#8a5a12", "#7a4d0a"),
    "private_date": ("#9a3b5c", "#8a2c4d"),
    "private_url": ("#175f8a", "#11507a"),
    "account_number": ("#7a5c00", "#6a4f00"),
    "secret": ("#9c2b2b", "#8d2020"),
    REDACTED_LABEL: ("#4a4a55", "#45454f"),
}

FALLBACK_LABEL = "other"
FALLBACK_BG = ("#3f4756", "#e4e7ee")
FALLBACK_FG = ("#eef1f7", "#232733")
FALLBACK_ACCENT = ("#3f4756", "#3a4250")

# Editor / viewer chrome, keyed by appearance mode.
PANE: dict[str, dict[str, str]] = {
    "dark": {
        "bg": "#1f1f27",
        "fg": "#e8e8ee",
        "insert": "#ffffff",
        "select_bg": "#2f5fb3",
        "select_fg": "#ffffff",
        "border": "#2b2b36",
        "active": "#3a6ea5",
    },
    "light": {
        "bg": "#fdfdfe",
        "fg": "#1b1b22",
        "insert": "#111111",
        "select_bg": "#cfe3ff",
        "select_fg": "#10233c",
        "border": "#d5d9e2",
        "active": "#9ec5f0",
    },
}

MONO_FAMILIES = ("Consolas", "Menlo", "DejaVu Sans Mono", "Courier")

# customtkinter paints button text as #DCE4EE in *both* appearance modes (it is
# designed for accent-coloured buttons). On a "transparent" button the face is
# the parent frame's colour, so light mode ends up with near-white text on a
# near-white background. These kwargs override that.
GHOST_BUTTON: dict[str, object] = {
    "fg_color": "transparent",
    "border_width": 1,
    "border_color": ("#a3a9b5", "#5c6270"),
    "hover_color": ("#e2e6ee", "#31323f"),
    "text_color": ("#1b1b22", "#e8e8ee"),
}


def ghost_button(**overrides: object) -> dict[str, object]:
    """Widget kwargs for a frame-coloured button that stays legible in light mode."""
    colors = dict(GHOST_BUTTON)
    colors.update(overrides)
    return colors


#: The face of a normal, active CTkButton - customtkinter's default "blue" theme
#: (tuples are customtkinter's ``(light, dark)`` order). Used as a fallback when
#: the live theme cannot be read, so a button can always be un-ghosted.
ACTIVE_BUTTON: dict[str, object] = {
    "fg_color": ("#3B8ED0", "#1F6AA5"),
    "hover_color": ("#36719F", "#144870"),
    "text_color": ("#DCE4EE", "#DCE4EE"),
    "border_color": "transparent",
    "border_width": 0,
}


def resolve_mode(appearance: str, actual: str = "dark") -> str:
    """Map a user appearance preference to a concrete ``dark``/``light`` mode.

    ``actual`` is what customtkinter reports for ``system`` mode.
    """
    if appearance in {"dark", "light"}:
        return appearance
    return actual if actual in {"dark", "light"} else "dark"


def span_bg(label: str, mode: str) -> str:
    pair = SPAN_BG.get(label, FALLBACK_BG)
    return pair[0] if mode == "dark" else pair[1]


def span_fg(label: str, mode: str) -> str:
    pair = SPAN_FG.get(label, FALLBACK_FG)
    return pair[0] if mode == "dark" else pair[1]


def span_accent(label: str, mode: str) -> str:
    """Text colour for a category's accent (legend counts).

    Unlike :func:`span_bg`, the light-mode value is dark enough to read as text.
    """
    pair = SPAN_ACCENT.get(label, FALLBACK_ACCENT)
    return pair[0] if mode == "dark" else pair[1]


def pane_colors(mode: str) -> dict[str, str]:
    """Editor colours for one appearance mode (dark by default)."""
    return PANE["dark" if mode != "light" else "light"]


# Status text colours (engine badge and friends), (light mode, dark mode) kept as
# explicit keys. The bright orange that reads so well on charcoal is close to
# unreadable on a light pane - about 2.1:1 - so light mode uses deep variants.
# Every colour below clears WCAG AA (4.5:1) against both the editor background and
# the toolbar frame (customtkinter's default frame: gray87 light / gray22 dark).
STATUS_COLORS = {
    "model": {"dark": "#57c785", "light": "#0a6b39"},
    "demo": {"dark": "#f0a020", "light": "#8a4a00"},
    "error": {"dark": "#ff8a8a", "light": "#a11c26"},
    "neutral": {"dark": "#b9bfd0", "light": "#4c5466"},
}


def status_color(state: str, mode: str) -> str:
    """Text colour for a status state ('model', 'demo', 'error', 'neutral')."""
    pair = STATUS_COLORS.get(state, STATUS_COLORS["demo"])
    return pair["dark" if mode != "light" else "light"]


def known_labels(extra: list[str] | None = None) -> list[str]:
    """Base taxonomy plus any labels discovered in the current result."""
    labels = list(PII_LABELS) + [REDACTED_LABEL]
    for label in extra or []:
        if label not in labels:
            labels.append(label)
    return labels


def mono_font(size: int) -> tuple[str, int]:
    """Best available monospace font tuple for tkinter."""
    import tkinter.font as tkfont  # local import keeps this module importable headless

    available = set(tkfont.families())
    for family in MONO_FAMILIES:
        if family in available:
            return (family, size)
    return ("Courier", size)


def ui_font(size: int, weight: str = "normal") -> tuple[str, int] | tuple[str, int, str]:
    import tkinter.font as tkfont

    available = set(tkfont.families())
    family = "Segoe UI"
    for candidate in ("Segoe UI", "Helvetica", "Arial", "DejaVu Sans"):
        if candidate in available:
            family = candidate
            break
    if weight == "normal":
        return (family, size)
    return (family, size, weight)
