"""Core data types for the Privacy Filter GUI.

This module is deliberately free of any GUI or model imports so it can be
unit-tested (and reused by scripts) without tkinter, customtkinter or torch.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1
"""Matches ``opf._common.constants.SCHEMA_VERSION``."""

PII_LABELS: tuple[str, ...] = (
    "account_number",
    "private_address",
    "private_email",
    "private_person",
    "private_phone",
    "private_url",
    "private_date",
    "secret",
)
"""The eight span categories shipped with the base OpenAI Privacy Filter model."""

REDACTED_LABEL = "redacted"
"""Collapsed label used by ``output_mode="redacted"``."""

OUTPUT_MODES: tuple[str, ...] = ("typed", "redacted")
DECODE_MODES: tuple[str, ...] = ("viterbi", "argmax")
DEVICES: tuple[str, ...] = ("auto", "cpu", "cuda")
ENGINES: tuple[str, ...] = ("model", "demo")

DISPLAY_NAMES: dict[str, str] = {
    "account_number": "Account number",
    "private_address": "Address",
    "private_email": "Email",
    "private_person": "Person",
    "private_phone": "Phone",
    "private_url": "URL",
    "private_date": "Date",
    "secret": "Secret / key",
    REDACTED_LABEL: "Redacted",
}


def placeholder_for(label: str) -> str:
    """Return the replacement marker OPF inserts for a label."""
    if label == REDACTED_LABEL:
        return "<REDACTED>"
    return f"<{label.upper()}>"


def display_name(label: str) -> str:
    """Human friendly label used in the legend and tables."""
    return DISPLAY_NAMES.get(label, label.replace("_", " ").title())


@dataclass(frozen=True)
class Span:
    """One detected PII span (character offsets into :attr:`Outcome.text`)."""

    label: str
    start: int
    end: int
    text: str
    placeholder: str = ""

    def __post_init__(self) -> None:
        if not self.placeholder:
            object.__setattr__(self, "placeholder", placeholder_for(self.label))

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)

    def overlaps(self, other: "Span") -> bool:
        return self.start < other.end and other.start < self.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "placeholder": self.placeholder,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Span":
        return Span(
            label=str(raw.get("label", "")),
            start=int(raw.get("start", 0)),
            end=int(raw.get("end", 0)),
            text=str(raw.get("text", "")),
            placeholder=str(raw.get("placeholder", "")),
        )


@dataclass
class Outcome:
    """Normalised result of one redaction run, engine independent."""

    text: str
    spans: list[Span] = field(default_factory=list)
    redacted_text: str = ""
    output_mode: str = "typed"
    engine: str = "model"
    latency_ms: float = 0.0
    decoded_mismatch: bool = False
    warning: str | None = None
    source: str | None = None

    # ------------------------------------------------------------------ #
    # construction
    # ------------------------------------------------------------------ #
    @staticmethod
    def from_payload(
        payload: dict[str, Any],
        *,
        latency_ms: float = 0.0,
        engine: str = "model",
        source: str | None = None,
    ) -> "Outcome":
        """Build an Outcome from an OPF ``RedactionResult.to_dict()`` payload."""
        summary = dict(payload.get("summary") or {})
        spans = [Span.from_dict(item) for item in payload.get("detected_spans") or []]
        warning = payload.get("warning")
        return Outcome(
            text=str(payload.get("text", "")),
            spans=spans,
            redacted_text=str(payload.get("redacted_text", "")),
            output_mode=str(summary.get("output_mode", "typed")),
            engine=engine,
            latency_ms=float(latency_ms),
            decoded_mismatch=bool(summary.get("decoded_mismatch", False)),
            warning=str(warning) if warning else None,
            source=source,
        )

    # ------------------------------------------------------------------ #
    # derived data
    # ------------------------------------------------------------------ #
    def by_label(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for span in self.spans:
            counts[span.label] = counts.get(span.label, 0) + 1
        return counts

    @property
    def span_count(self) -> int:
        return len(self.spans)

    def to_payload(self) -> dict[str, Any]:
        """Serialise using the upstream OPF JSON schema (v1)."""
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "summary": {
                "output_mode": self.output_mode,
                "span_count": self.span_count,
                "by_label": self.by_label(),
                "decoded_mismatch": self.decoded_mismatch,
            },
            "text": self.text,
            "detected_spans": [span.to_dict() for span in self.spans],
            "redacted_text": self.redacted_text,
        }
        if self.warning:
            payload["warning"] = self.warning
        return payload

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_payload(), indent=indent, ensure_ascii=False)


def redact_manually(text: str, spans: Sequence[Span]) -> str:
    """Apply span placeholders to ``text`` (mirrors ``opf._api._redact_text``)."""
    if not spans:
        return text
    ordered = sorted(spans, key=lambda s: s.start)
    pieces: list[str] = []
    cursor = 0
    for span in ordered:
        if span.start < cursor:
            continue
        pieces.append(text[cursor : span.start])
        pieces.append(span.placeholder or placeholder_for(span.label))
        cursor = span.end
    pieces.append(text[cursor:])
    return "".join(pieces)


# ---------------------------------------------------------------------- #
# settings
# ---------------------------------------------------------------------- #

DEFAULT_CONFIG_PATH = Path.home() / ".opf_gui" / "settings.json"


def config_path() -> Path:
    """Resolve the settings file location (``OPF_GUI_CONFIG`` wins)."""
    raw = os.environ.get("OPF_GUI_CONFIG")
    if raw:
        return Path(raw).expanduser()
    return DEFAULT_CONFIG_PATH


@dataclass
class Settings:
    """Everything the GUI can configure, mirrored to disk as JSON."""

    engine: str = "model"
    device: str = "auto"
    output_mode: str = "typed"
    decode_mode: str = "viterbi"
    checkpoint: str = ""
    n_ctx: str = ""
    trim_whitespace: bool = True
    discard_overlapping: bool = False
    viterbi_calibration_path: str = ""
    appearance: str = "dark"
    color_theme: str = "blue"
    font_size: int = 12
    highlight_input: bool = True
    live_detect: bool = False
    auto_load_model: bool = False
    drag_and_drop: bool = True
    export_dir: str = ""
    recent_files: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "device": self.device,
            "output_mode": self.output_mode,
            "decode_mode": self.decode_mode,
            "checkpoint": self.checkpoint,
            "n_ctx": self.n_ctx,
            "trim_whitespace": self.trim_whitespace,
            "discard_overlapping": self.discard_overlapping,
            "viterbi_calibration_path": self.viterbi_calibration_path,
            "appearance": self.appearance,
            "color_theme": self.color_theme,
            "font_size": self.font_size,
            "highlight_input": self.highlight_input,
            "live_detect": self.live_detect,
            "auto_load_model": self.auto_load_model,
            "drag_and_drop": self.drag_and_drop,
            "export_dir": self.export_dir,
            "recent_files": list(self.recent_files),
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Settings":
        settings = Settings()
        data = dict(raw or {})
        text_fields = (
            "engine",
            "device",
            "output_mode",
            "decode_mode",
            "checkpoint",
            "n_ctx",
            "viterbi_calibration_path",
            "appearance",
            "color_theme",
            "export_dir",
        )
        bool_fields = (
            "trim_whitespace",
            "discard_overlapping",
            "highlight_input",
            "live_detect",
            "auto_load_model",
            "drag_and_drop",
        )
        for key in text_fields:
            value = data.get(key)
            if isinstance(value, str):
                setattr(settings, key, value)
        for key in bool_fields:
            if isinstance(data.get(key), bool):
                setattr(settings, key, data[key])
        if isinstance(data.get("font_size"), (int, float)):
            settings.font_size = int(data["font_size"])
        if isinstance(data.get("recent_files"), list):
            settings.recent_files = [str(item) for item in data["recent_files"][:10]]

        # Normalise enums so a hand-edited config can never wedge the UI.
        if settings.engine not in ENGINES:
            settings.engine = "model"
        if settings.device not in DEVICES:
            settings.device = "auto"
        if settings.output_mode not in OUTPUT_MODES:
            settings.output_mode = "typed"
        if settings.decode_mode not in DECODE_MODES:
            settings.decode_mode = "viterbi"
        if settings.appearance not in {"dark", "light", "system"}:
            settings.appearance = "dark"
        return settings

    @property
    def n_ctx_value(self) -> int | None:
        """Parsed ``--n-ctx`` override, or ``None`` when unset/invalid."""
        raw = self.n_ctx.strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if value > 0 else None

    def add_recent(self, path: str | os.PathLike[str], limit: int = 8) -> None:
        resolved = str(Path(path).expanduser())
        files = [item for item in self.recent_files if item != resolved]
        files.insert(0, resolved)
        self.recent_files = files[:limit]

    def save(self, path: Path | None = None) -> Path:
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return target

    @staticmethod
    def load(path: Path | None = None) -> "Settings":
        target = path or config_path()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return Settings()
        if not isinstance(raw, dict):
            return Settings()
        return Settings.from_dict(raw)


def summarise_outcomes(outcomes: Iterable[Outcome]) -> dict[str, Any]:
    """Aggregate statistics for batch runs."""
    items = list(outcomes)
    by_label: dict[str, int] = {}
    total_latency = 0.0
    total_chars = 0
    for outcome in items:
        for label, count in outcome.by_label().items():
            by_label[label] = by_label.get(label, 0) + count
        total_latency += outcome.latency_ms
        total_chars += len(outcome.text)
    return {
        "documents": len(items),
        "spans": sum(item.span_count for item in items),
        "by_label": by_label,
        "chars": total_chars,
        "latency_ms": total_latency,
        "warnings": sum(1 for item in items if item.warning),
    }
