"""Text helpers: highlight planning, file IO and exports (no GUI imports)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .models import Outcome, Settings, Span, display_name, summarise_outcomes

READ_ENCODINGS = ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1")


# --------------------------------------------------------------------- #
# span / highlight planning
# --------------------------------------------------------------------- #
def resolve_overlaps(spans: Sequence[Span]) -> tuple[list[Span], list[Span]]:
    """Split spans into ``(visible, hidden)`` for single-colour highlighting.

    tkinter stacks tags, so overlapping spans would fight over the background
    colour and one would silently win. Longer spans win, ties go to the earlier
    start; the losers are returned so the UI can report them.
    """
    ordered = sorted(spans, key=lambda span: (-span.length, span.start, span.label))
    visible: list[Span] = []
    hidden: list[Span] = []
    for span in ordered:
        if any(span.overlaps(kept) for kept in visible):
            hidden.append(span)
        else:
            visible.append(span)
    visible.sort(key=lambda span: span.start)
    hidden.sort(key=lambda span: span.start)
    return visible, hidden


def clamp_spans(text: str, spans: Sequence[Span]) -> list[Span]:
    """Guard against offsets that fall outside the current editor contents."""
    limit = len(text)
    safe: list[Span] = []
    for span in spans:
        start = max(0, min(span.start, limit))
        end = max(start, min(span.end, limit))
        if end > start:
            safe.append(
                Span(
                    label=span.label,
                    start=start,
                    end=end,
                    text=text[start:end],
                    placeholder=span.placeholder,
                )
            )
    return safe


def plain_summary(outcome: Outcome) -> str:
    """One-line status text for the status bar."""
    bits = [f"{outcome.span_count} span(s)"]
    for label, count in sorted(outcome.by_label().items(), key=lambda kv: -kv[1])[:4]:
        bits.append(f"{count} {display_name(label)}")
    bits.append(format_latency(outcome.latency_ms))
    if outcome.source:
        bits.append(Path(outcome.source).name)
    return " - ".join(bits)


def format_latency(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f} ms"
    return f"{ms / 1000:.2f} s"


def table_rows(
    spans: Sequence[Span],
) -> list[tuple[str, str, str, str, str, str]]:
    """Rows for the span table: (#, label, text, chars, offset, placeholder)."""
    rows = []
    for index, span in enumerate(spans, start=1):
        preview = span.text if len(span.text) <= 60 else span.text[:57] + "..."
        rows.append(
            (
                str(index),
                display_name(span.label),
                preview.replace("\n", " ").replace("\t", " "),
                str(span.length),
                f"{span.start}-{span.end}",
                span.placeholder,
            )
        )
    return rows


# --------------------------------------------------------------------- #
# label text
# --------------------------------------------------------------------- #
#: Longest run of characters a narrow panel label can put on one line. Tk breaks
#: a label's lines at *whitespace only*, so a value without spaces - the model
#: checkpoint path, a long label name - never wraps: it runs past the edge of the
#: Detection summary panel and is clipped.
LABEL_MAX_RUN = 26

#: Preferred break points inside an over-long word, so a path splits after a
#: separator and a snake_case label after an underscore rather than mid-word.
TOKEN_BREAK_AFTER = "/\\_-."


def break_long_token(token: str, max_run: int = LABEL_MAX_RUN) -> list[str]:
    """Split one whitespace-free ``token`` into pieces no longer than ``max_run``."""
    limit = max(1, int(max_run))
    pieces: list[str] = []
    rest = token
    while len(rest) > limit:
        cut = limit
        for index in range(limit, 0, -1):
            if rest[index - 1] in TOKEN_BREAK_AFTER:
                cut = index  # break after the last separator that still fits
                break
        pieces.append(rest[:cut])
        rest = rest[cut:]
    return pieces + [rest]


def wrap_long_tokens(text: str, max_run: int = LABEL_MAX_RUN) -> str:
    """Hard-break over-long words with newlines so a fixed-width label can wrap.

    ``wraplength`` handles the words: an ordinary sentence wraps inside the panel
    whatever its length. What it cannot do is break a single word longer than the
    panel, which is why the Demo engine's wording wrapped neatly while the model
    engine's ``Checkpoint: /home/ana/.opf/privacy_filter`` was cut off. Adding the
    breaks here lets both engines render in full.
    """
    lines: list[str] = []
    for line in str(text).splitlines() or [""]:
        lines.append(
            " ".join(
                "\n".join(break_long_token(word, max_run)) if len(word) > max_run else word
                for word in line.split(" ")
            )
        )
    return "\n".join(lines)


# --------------------------------------------------------------------- #
# files
# --------------------------------------------------------------------- #
def read_text_file(path: str | Path) -> str:
    """Read a text file, tolerating the usual Windows encodings."""
    file_path = Path(path).expanduser()
    data = file_path.read_bytes()
    for encoding in READ_ENCODINGS:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def write_text_file(path: str | Path, content: str) -> Path:
    file_path = Path(path).expanduser()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding="utf-8")
    return file_path


def safe_stem(name: str) -> str:
    """Filesystem-safe stem derived from a filename or arbitrary string."""
    stem = Path(name).name
    stem = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", stem)
    stem = re.sub(r"[^A-Za-z0-9._\-]+", "_", stem).strip("._-")
    return stem[:80] or "document"


def timestamp_slug() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def suggest_export_path(
    settings: Settings, source: str | None, suffix: str, extension: str
) -> Path:
    """Suggest ``<export_dir>/<stem>-<suffix><extension>``."""
    base = Path(settings.export_dir).expanduser() if settings.export_dir else Path.home()
    stem = safe_stem(source) if source else "redacted"
    return base / f"{stem}-{suffix}{extension}"


# --------------------------------------------------------------------- #
# exports
# --------------------------------------------------------------------- #
def outcomes_to_jsonl(outcomes: Iterable[Outcome]) -> str:
    return "\n".join(outcome.to_json(indent=None) for outcome in outcomes) + "\n"


def outcomes_to_json(outcomes: Sequence[Outcome]) -> str:
    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "count": len(outcomes),
        "aggregate": summarise_outcomes(outcomes),
        "results": [outcome.to_payload() for outcome in outcomes],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def batch_summary_markdown(outcomes: Sequence[Outcome], engine: str) -> str:
    """Markdown report suitable for a change/CI record."""
    stats = summarise_outcomes(outcomes)
    lines = [
        "# Privacy Filter batch report",
        "",
        f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"- Engine: {engine}",
        f"- Documents: {stats['documents']}",
        f"- Total PII spans: {stats['spans']}",
        f"- Characters processed: {stats['chars']}",
        f"- Total inference time: {format_latency(stats['latency_ms'])}",
    ]
    if stats["warnings"]:
        lines.append(f"- Tokenizer round-trip warnings: {stats['warnings']}")
    lines += ["", "## Spans by category", "", "| Category | Count |", "| --- | ---: |"]
    for label, count in sorted(stats["by_label"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {display_name(label)} | {count} |")
    if not stats["by_label"]:
        lines.append("| (none detected) | 0 |")
    lines += ["", "## Per document", "", "| Document | Spans | Categories | Time |",
              "| --- | ---: | --- | ---: |"]
    for outcome in outcomes:
        name = Path(outcome.source or "inline").name
        labels = ", ".join(
            f"{display_name(label)} x{count}"
            for label, count in sorted(outcome.by_label().items(), key=lambda kv: -kv[1])
        )
        lines.append(
            f"| {name} | {outcome.span_count} | {labels or '-'} | "
            f"{format_latency(outcome.latency_ms)} |"
        )
    lines.append("")
    return "\n".join(lines)


SAMPLE_TEXT = """Incident INC-4821 - escalation notes
Reporter: Alice Smith (alice.smith@example.com, +1 415 555 0132)
Account affected: 4111 1111 1111 1111
Date of first occurrence: 1990-01-02 (contract signed March 5, 2021)
Home address on file: 1234 Maple Street, Springfield, IL 62704
Vendor ticket: https://vendor.example.com/tickets/99887
Debug note: the integration key sk-test-ABCDEFGHIJ1234567890 was left in the
config file; rotate it and close the change request.
"""


def sample_text() -> str:
    """Synthetic example text (no real personal data)."""
    return SAMPLE_TEXT
