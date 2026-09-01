"""Redaction backends.

``ModelBackend`` wraps the real ``opf.OPF`` Python API from
https://github.com/openai/privacy-filter. ``DemoBackend`` is a dependency-free
regex stand-in used for UI previews, tests and machines without the checkpoint.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .models import (
    Outcome,
    PII_LABELS,
    REDACTED_LABEL,
    Settings,
    Span,
    placeholder_for,
    redact_manually,
)

INSTALL_HINT = (
    "OpenAI Privacy Filter is not installed in this Python environment.\n\n"
    "  git clone https://github.com/openai/privacy-filter\n"
    "  cd privacy-filter && pip install -e .\n\n"
    "Switch the engine selector to Demo to try the interface without the model."
)


class BackendError(RuntimeError):
    """Raised when a backend cannot produce a result."""


@dataclass(frozen=True)
class ModelStatus:
    """Environment probe used to decide what the GUI can actually run."""

    installed: bool
    checkpoint_present: bool
    detail: str


class Backend:
    """Common interface implemented by every engine."""

    name = "base"

    def describe(self) -> dict[str, str]:
        raise NotImplementedError

    def warmup(self) -> None:
        """Optional eager initialisation hook, run on the worker thread."""

    def redact(self, text: str) -> Outcome:
        raise NotImplementedError

    def close(self) -> None:
        """Release heavy resources (model weights) if possible."""


def _torch_cuda_available() -> bool:
    try:
        import torch  # noqa: PLC0415 - heavy import, deliberately deferred

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def resolve_device(requested: str) -> str:
    """Translate the GUI device choice into an ``opf`` device string."""
    if requested == "cuda":
        return "cuda"
    if requested == "cpu":
        return "cpu"
    return "cuda" if _torch_cuda_available() else "cpu"


class ModelBackend(Backend):
    """Thin, restartable wrapper around :class:`opf.OPF`."""

    name = "opf"

    #: Optional filename attached to the next result (batch mode).
    pending_source: str | None = None

    def __init__(self, settings: Settings, log: Callable[[str], None] | None = None):
        self.settings = settings
        self._log = log or (lambda _message: None)
        self._opf: Any = None
        self._checkpoint_key: tuple[Any, ...] | None = None
        self.resolved_device = ""
        self._applied: dict[str, Any] = {}

    # ------------------------------------------------------------------ #
    @property
    def loaded(self) -> bool:
        return self._opf is not None

    def _constructor_key(self) -> tuple[Any, ...]:
        """Settings that force a full model rebuild (no setter upstream)."""
        return (
            self.settings.checkpoint.strip(),
            self.settings.n_ctx_value,
            bool(self.settings.discard_overlapping),
        )

    def _ensure_instance(self) -> Any:
        try:
            from opf import OPF  # noqa: PLC0415 - optional dependency
        except ImportError as exc:
            raise BackendError(INSTALL_HINT) from exc

        key = self._constructor_key()
        if self._opf is None:
            checkpoint = self.settings.checkpoint.strip() or None
            device = resolve_device(self.settings.device)
            self.resolved_device = device
            self._log(
                f"Loading checkpoint "
                f"{checkpoint or os.environ.get('OPF_CHECKPOINT') or '~/.opf/privacy_filter'} "
                f"on {device} (first run downloads ~1.5 GB)..."
            )
            try:
                self._opf = OPF(
                    model=checkpoint,
                    device=device,  # type: ignore[arg-type]
                    output_mode="typed",  # GUI collapses labels itself; avoids reloads
                    decode_mode=self.settings.decode_mode,  # type: ignore[arg-type]
                    trim_whitespace=self.settings.trim_whitespace,
                    discard_overlapping_predicted_spans=self.settings.discard_overlapping,
                    context_window_length=self.settings.n_ctx_value,
                    output_text_only=False,
                )
            except BackendError:
                raise
            except Exception as exc:  # noqa: BLE001 - surface any load failure in the UI
                self._opf = None
                raise BackendError(f"Could not load checkpoint: {exc}") from exc
            self._checkpoint_key = key
            self._applied = {
                "device": self.resolved_device,
                "trim_whitespace": self.settings.trim_whitespace,
                "decode_mode": self.settings.decode_mode,
                "calibration": self.settings.viterbi_calibration_path.strip(),
            }
            self._log("Model ready.")
        elif key != self._checkpoint_key:
            # n_ctx / overlap handling changed: rebuilding reloads the weights.
            self._log("Rebuilding runtime (context window or overlap setting changed)...")
            self._opf = None
            return self._ensure_instance()
        return self._opf

    def _apply_hot_settings(self, opf: Any) -> None:
        """Apply only the settings that really changed.

        Upstream setters such as ``set_device`` and ``trim_whitespace`` drop the
        cached runtime, which reloads the weights, so calling them on every run
        would make the GUI unusably slow. ``output_mode`` is pure post-processing
        upstream, so the runtime always runs in ``typed`` mode and the GUI
        collapses labels itself when ``redacted`` is selected.
        """
        wanted_device = resolve_device(self.settings.device)
        if self._applied.get("device") != wanted_device:
            self._log(f"Device -> {wanted_device} (runtime rebuild)")
            opf.set_device(device=wanted_device)  # type: ignore[arg-type]
            self._applied["device"] = wanted_device
            self.resolved_device = wanted_device

        if self._applied.get("trim_whitespace") != self.settings.trim_whitespace:
            self._log(
                "Trim span whitespace -> "
                f"{'on' if self.settings.trim_whitespace else 'off'} (runtime rebuild)"
            )
            opf.trim_whitespace(self.settings.trim_whitespace)
            self._applied["trim_whitespace"] = self.settings.trim_whitespace

        calibration = self.settings.viterbi_calibration_path.strip()
        decode_mode = self.settings.decode_mode
        if decode_mode == "viterbi" and self._applied.get("calibration") != calibration:
            opf.set_viterbi_decoder(calibration_path=calibration or None)
            self._applied["calibration"] = calibration
            self._log(f"Viterbi calibration -> {calibration or 'checkpoint default'}")

        # set_decode_mode runs last: set_viterbi_decoder forces viterbi mode.
        if self._applied.get("decode_mode") != decode_mode:
            opf.set_decode_mode(decode_mode)  # type: ignore[arg-type]
            self._applied["decode_mode"] = decode_mode
            self._log(f"Decode mode -> {decode_mode}")

    # ------------------------------------------------------------------ #
    def load(self) -> None:
        self._ensure_instance()

    def warmup(self) -> None:
        opf = self._ensure_instance()
        self._apply_hot_settings(opf)
        started = time.perf_counter()
        opf.redact("Warm up: Alice Smith alice@example.com 1990-01-02.")
        self._log(f"Warm-up pass finished in {(time.perf_counter() - started) * 1000:.0f} ms.")

    def describe(self) -> dict[str, str]:
        checkpoint = self.settings.checkpoint.strip()
        if not checkpoint:
            checkpoint = os.environ.get("OPF_CHECKPOINT") or str(
                Path.home() / ".opf" / "privacy_filter"
            )
        return {
            "Engine": "OpenAI Privacy Filter",
            "Checkpoint": checkpoint,
            "Device": self.resolved_device or self.settings.device,
            "Output mode": self.settings.output_mode,
            "Decode": self.settings.decode_mode,
            "Context window": str(self.settings.n_ctx_value or "model default"),
            "Loaded": "yes" if self.loaded else "no",
        }

    def redact(self, text: str) -> Outcome:
        opf = self._ensure_instance()
        self._apply_hot_settings(opf)
        started = time.perf_counter()
        try:
            result = opf.redact(text)
        except Exception as exc:  # noqa: BLE001
            raise BackendError(f"Inference failed: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000.0
        payload = result.to_dict() if hasattr(result, "to_dict") else {"text": text}
        outcome = Outcome.from_payload(payload, latency_ms=latency_ms, engine="model")
        if self.settings.output_mode == "redacted":
            outcome.spans = [
                Span(
                    label=REDACTED_LABEL,
                    start=span.start,
                    end=span.end,
                    text=span.text,
                    placeholder="<REDACTED>",
                )
                for span in outcome.spans
            ]
            outcome.redacted_text = redact_manually(outcome.text, outcome.spans)
            outcome.output_mode = "redacted"
        outcome.source = self.pending_source
        return outcome

    def close(self) -> None:
        self._opf = None
        self._checkpoint_key = None
        self._applied = {}


#: Shown in the sidebar and written into every JSON payload the demo engine makes,
#: so a heuristic result can never be mistaken for a real OPF run.
DEMO_WARNING = "Demo engine: heuristic regex detection only - not a privacy control."


class DemoBackend(Backend):
    """Offline regex detector used when the model is unavailable.

    It emits the same eight categories and placeholders as the model so the
    whole interface (and export format) can be exercised without torch.
    Detection quality is heuristic and intentionally NOT a privacy control.
    """

    name = "demo"

    #: Priority order matters: earlier patterns win overlapping character ranges.
    PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        (
            "secret",
            re.compile(
                r"(?:\b(?:sk|pk|rk|ghp|xoxb|xoxp)[-_][A-Za-z0-9_\-]{12,}\b)"
                r"|\bAKIA[0-9A-Z]{16}\b"
                r"|\bAIza[0-9A-Za-z_\-]{20,}\b"
                r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
                r"|\b(?:password|passwd|pwd|passphrase|api[_ -]?key|secret|token)\b"
                r"\s*[:=]\s*[^\s,;\"']{4,}",
                re.IGNORECASE,
            ),
        ),
        ("private_email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
        (
            "private_url",
            re.compile(r"(?:https?|ftp)://[^\s<>\"'`(){}]+|\bwww\.[^\s<>\"'`(){}]"),
        ),
        (
            "private_phone",
            re.compile(
                r"\+?\d{1,2}[\s.\-]?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b"
                r"|\b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b"
            ),
        ),
        (
            "private_date",
            re.compile(
                r"\b[12]\d{3}[-/]\d{1,2}[-/]\d{1,2}\b"
                r"|\b\d{1,2}[-/]\d{1,2}[-/](?:19|20)\d{2}\b"
                r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
                r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s+(?:19|20)\d{2}\b"
                r"|\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
                r",?\s+(?:19|20)\d{2}\b",
                re.IGNORECASE,
            ),
        ),
        (
            "private_address",
            re.compile(
                r"\b\d{1,6}\s+[A-Za-z0-9.'\-]+(?:\s+[A-Za-z0-9.'\-]+){0,5}\s+"
                r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|"
                r"Way|Place|Pl|Terrace|Ter|Circle|Cir|Highway|Hwy|Parkway|Pkwy|Apt|Unit|Suite|Ste)\b\.?"
                r",?\s*"
                r"(?:[A-Za-z.\-]+\s*,?\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)?",
                re.IGNORECASE,
            ),
        ),
        (
            "account_number",
            re.compile(r"\b(?:\d[\s\-]?){8,19}\d\b"),
        ),
        (
            "private_person",
            re.compile(
                r"\b(?:Mr|Mrs|Ms|Dr|Prof|Mx)\.?\s+[A-Z][A-Za-z'\-]+"
                r"(?:\s+[A-Z][A-Za-z'\-]+){0,3}"
                r"|\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b"
            ),
        ),
    )

    def describe(self) -> dict[str, str]:
        return {
            "Engine": "Demo (regex, offline)",
            "Warning": DEMO_WARNING,
            "Output mode": self.settings.output_mode,
            "Loaded": "always",
        }

    def __init__(self, settings: Settings, log: Callable[[str], None] | None = None):
        self.settings = settings
        self._log = log or (lambda _message: None)

    def redact(self, text: str) -> Outcome:
        started = time.perf_counter()
        spans: list[Span] = []
        for label, pattern in self.PATTERNS:
            for match in pattern.finditer(text):
                span = Span(
                    label=label,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                    placeholder=placeholder_for(label),
                )
                if span.text.strip() and not self._collides(span, spans):
                    spans.append(span)
        spans.sort(key=lambda item: item.start)
        if self.settings.output_mode == "redacted":
            spans = [
                Span(
                    label=REDACTED_LABEL,
                    start=span.start,
                    end=span.end,
                    text=span.text,
                    placeholder="<REDACTED>",
                )
                for span in spans
            ]
        return Outcome(
            text=text,
            spans=spans,
            redacted_text=redact_manually(text, spans),
            output_mode=self.settings.output_mode,
            engine="demo",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            warning=DEMO_WARNING,
        )

    @staticmethod
    def _collides(span: Span, existing: list[Span]) -> bool:
        return any(span.overlaps(other) for other in existing)


def create_backend(settings: Settings, log: Callable[[str], None] | None = None) -> Backend:
    """Build the backend selected by ``settings.engine``."""
    if settings.engine == "demo":
        return DemoBackend(settings, log=log)
    return ModelBackend(settings, log=log)


def default_checkpoint_dir() -> Path:
    """Where OPF looks for / downloads the weights when nothing is configured."""
    return Path.home() / ".opf" / "privacy_filter"


def model_status(configured_checkpoint: str = "") -> ModelStatus:
    """Report whether the ``opf`` package is installed and weights are local.

    ``configured_checkpoint`` is the GUI setting; when empty, the ``OPF_CHECKPOINT``
    environment variable and then ``~/.opf/privacy_filter`` are used, mirroring
    ``opf._api.resolve_checkpoint_path``.
    """
    try:
        import opf  # noqa: F401, PLC0415 - optional dependency probe
    except ImportError:
        return ModelStatus(
            installed=False, checkpoint_present=False, detail="opf package not installed"
        )
    raw = configured_checkpoint.strip() or os.environ.get("OPF_CHECKPOINT", "").strip()
    if raw:
        path = Path(raw).expanduser()
        return ModelStatus(
            installed=True,
            checkpoint_present=path.exists(),
            detail=f"configured checkpoint: {path}",
        )
    default = default_checkpoint_dir()
    return ModelStatus(
        installed=True,
        checkpoint_present=default.exists(),
        detail=(
            f"local checkpoint: {default}"
            if default.exists()
            else f"no local checkpoint; first load downloads weights to {default}"
        ),
    )


__all__ = [
    "Backend",
    "BackendError",
    "DemoBackend",
    "INSTALL_HINT",
    "ModelBackend",
    "ModelStatus",
    "PII_LABELS",
    "create_backend",
    "default_checkpoint_dir",
    "model_status",
    "resolve_device",
]
