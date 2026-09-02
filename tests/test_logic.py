"""Headless unit tests for the non-GUI layers of opf_gui.

Run with:  python -m unittest discover -s tests     (from this directory)
or:        python tests/test_logic.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from opf_gui import formatting, theme
from opf_gui.backends import DemoBackend, ModelStatus, model_status, resolve_device
from opf_gui.engine import (
    MSG_BATCH_ITEM,
    MSG_DONE,
    MSG_ERROR,
    MSG_LOG,
    MSG_PROGRESS,
    MSG_RESULT,
    MSG_STATUS,
    EngineController,
)
from opf_gui.models import (
    Outcome,
    Settings,
    Span,
    placeholder_for,
    redact_manually,
    summarise_outcomes,
)
from opf_gui.theme import resolve_mode, span_bg, span_fg
from opf_gui.backends import Backend

SAMPLE = (
    "Alice Smith (alice.smith@example.com, +1 415 555 0132) lives at "
    "1234 Maple Street, Springfield, IL 62704. Her card ends 4111 1111 1111 1111 "
    "and the key sk-test-ABCDEFGHIJ1234567890 leaked. Ticket: "
    "https://vendor.example.com/tickets/9 on 1990-01-02."
)


class TestModels(unittest.TestCase):
    def test_placeholder_naming(self) -> None:
        self.assertEqual(placeholder_for("private_person"), "<PRIVATE_PERSON>")
        self.assertEqual(placeholder_for("redacted"), "<REDACTED>")

    def test_span_defaults_and_overlap(self) -> None:
        first = Span(label="private_email", start=5, end=20, text="a@b.example")
        self.assertEqual(first.placeholder, "<PRIVATE_EMAIL>")
        self.assertEqual(first.length, 15)
        self.assertTrue(first.overlaps(Span("private_person", 10, 30, "x")))
        self.assertFalse(first.overlaps(Span("private_person", 20, 30, "x")))

    def test_outcome_roundtrips_opf_schema(self) -> None:
        payload = {
            "schema_version": 1,
            "summary": {
                "output_mode": "typed",
                "span_count": 2,
                "by_label": {"private_person": 1, "private_date": 1},
                "decoded_mismatch": False,
            },
            "text": "Alice was born on 1990-01-02.",
            "detected_spans": [
                {"label": "private_person", "start": 0, "end": 5, "text": "Alice",
                 "placeholder": "<PRIVATE_PERSON>"},
                {"label": "private_date", "start": 18, "end": 28, "text": "1990-01-02",
                 "placeholder": "<PRIVATE_DATE>"},
            ],
            "redacted_text": "<PRIVATE_PERSON> was born on <PRIVATE_DATE>.",
        }
        outcome = Outcome.from_payload(payload, latency_ms=1234.5, engine="model")
        self.assertEqual(outcome.span_count, 2)
        self.assertEqual(outcome.by_label()["private_date"], 1)
        self.assertEqual(formatting.format_latency(1234.5), "1.23 s")
        reloaded = json.loads(outcome.to_json())
        self.assertEqual(reloaded["schema_version"], 1)
        self.assertEqual(reloaded["summary"]["span_count"], 2)
        self.assertEqual(reloaded["redacted_text"], payload["redacted_text"])
        self.assertNotIn("warning", reloaded)

    def test_redact_manually_matches_upstream_order(self) -> None:
        text = "Alice was born on 1990-01-02."
        spans = [
            Span("private_date", 18, 28, "1990-01-02"),
            Span("private_person", 0, 5, "Alice"),
        ]
        self.assertEqual(
            redact_manually(text, spans),
            "<PRIVATE_PERSON> was born on <PRIVATE_DATE>.",
        )
        self.assertEqual(redact_manually(text, []), text)

    def test_settings_roundtrip_and_normalisation(self) -> None:
        settings = Settings(engine="demo", device="cuda", font_size=14, n_ctx="4096")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings.save(path)
            loaded = Settings.load(path)
        self.assertEqual(loaded.device, "cuda")
        self.assertEqual(loaded.font_size, 14)
        self.assertEqual(loaded.n_ctx_value, 4096)
        self.assertEqual(Settings.from_dict({"n_ctx": "abc"}).n_ctx_value, None)
        self.assertEqual(Settings.from_dict({"n_ctx": "0"}).n_ctx_value, None)
        # hostile values fall back to safe defaults instead of wedging the UI
        broken = Settings.from_dict({"engine": "nonsense", "device": 12, "appearance": "neon"})
        self.assertEqual(broken.engine, "model")
        self.assertEqual(broken.device, "auto")
        self.assertEqual(broken.appearance, "dark")
        self.assertEqual(Settings.load(Path(folder) / "missing.json").engine, "model")

    def test_recent_files_are_deduped_and_capped(self) -> None:
        settings = Settings()
        for index in range(12):
            settings.add_recent(f"/tmp/file{index}.txt")
        self.assertEqual(len(settings.recent_files), 8)
        settings.add_recent("/tmp/file11.txt")
        self.assertEqual(settings.recent_files[0], "/tmp/file11.txt")
        self.assertEqual(settings.recent_files.count("/tmp/file11.txt"), 1)

    def test_summarise_outcomes(self) -> None:
        outcomes = [
            Outcome(text="a", spans=[Span("private_email", 0, 1, "a")], latency_ms=10),
            Outcome(text="b", spans=[Span("private_date", 0, 1, "b")], latency_ms=5),
        ]
        stats = summarise_outcomes(outcomes)
        self.assertEqual(stats["documents"], 2)
        self.assertEqual(stats["spans"], 2)
        self.assertEqual(stats["latency_ms"], 15)
        self.assertEqual(stats["by_label"]["private_email"], 1)


class TestDemoBackend(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = DemoBackend(Settings(engine="demo"))

    def labels(self, text: str) -> set[str]:
        return {span.label for span in self.backend.redact(text).spans}

    def test_detects_every_category(self) -> None:
        found = self.labels(SAMPLE)
        for expected in (
            "private_person",
            "private_email",
            "private_phone",
            "private_address",
            "account_number",
            "secret",
            "private_url",
            "private_date",
        ):
            self.assertIn(expected, found, f"missing {expected}")

    def test_spans_are_consistent_with_the_text(self) -> None:
        outcome = self.backend.redact(SAMPLE)
        self.assertEqual(outcome.text, SAMPLE)
        self.assertEqual(outcome.engine, "demo")
        for span in outcome.spans:
            self.assertEqual(SAMPLE[span.start : span.end], span.text)
            self.assertEqual(span.placeholder, placeholder_for(span.label))

    def test_redacted_text_contains_no_raw_pii(self) -> None:
        outcome = self.backend.redact(SAMPLE)
        for secret in ("alice.smith@example.com", "ABCDEFGHIJ1234567890", "4111 1111 1111 1111"):
            self.assertNotIn(secret, outcome.redacted_text)
        self.assertIn("<PRIVATE_EMAIL>", outcome.redacted_text)

    def test_redacted_output_mode_collapses_labels(self) -> None:
        backend = DemoBackend(Settings(engine="demo", output_mode="redacted"))
        outcome = backend.redact(SAMPLE)
        self.assertEqual(outcome.output_mode, "redacted")
        self.assertTrue({span.label for span in outcome.spans} == {"redacted"})
        self.assertNotIn("<PRIVATE_EMAIL>", outcome.redacted_text)
        self.assertIn("<REDACTED>", outcome.redacted_text)

    def test_empty_text_is_safe(self) -> None:
        outcome = self.backend.redact("")
        self.assertEqual(outcome.spans, [])
        self.assertEqual(outcome.redacted_text, "")

    def test_overlapping_patterns_are_not_double_counted(self) -> None:
        outcome = self.backend.redact("Call 415 555 0132 or 415 555 0132 now")
        starts = [span.start for span in outcome.spans]
        self.assertEqual(starts, sorted(starts))
        visible, _hidden = formatting.resolve_overlaps(outcome.spans)
        for i, span in enumerate(visible):
            for other in visible[i + 1 :]:
                self.assertFalse(span.overlaps(other))

    def test_describe_mentions_heuristic_warning(self) -> None:
        self.assertIn("not a privacy control", self.backend.describe()["Warning"])

    def test_json_payload_carries_the_demo_warning(self) -> None:
        # an exported file must never look like a real OPF run
        outcome = self.backend.redact("mail alice@corp.example now")
        payload = outcome.to_payload()
        self.assertIn("not a privacy control", payload["warning"])
        self.assertIn("not a privacy control", outcome.to_json())


class TestEnvironmentProbes(unittest.TestCase):
    def test_resolve_device_never_returns_unknown(self) -> None:
        self.assertEqual(resolve_device("cpu"), "cpu")
        self.assertEqual(resolve_device("cuda"), "cuda")
        self.assertIn(resolve_device("auto"), {"cpu", "cuda"})

    def test_model_status_without_package(self) -> None:
        status = model_status("/definitely/not/here")
        self.assertIsInstance(status, ModelStatus)
        self.assertIsInstance(status.installed, bool)
        if not status.installed:
            self.assertFalse(status.checkpoint_present)

    def test_resolve_mode(self) -> None:
        self.assertEqual(resolve_mode("dark"), "dark")
        self.assertEqual(resolve_mode("light"), "light")
        self.assertEqual(resolve_mode("system", "light"), "light")
        self.assertEqual(resolve_mode("system", "bogus"), "dark")

    def test_label_colours_are_hex_and_distinct_per_label(self) -> None:
        from opf_gui.theme import SPAN_BG

        dark = {span_bg(label, "dark") for label in SPAN_BG}
        light = {span_bg(label, "light") for label in SPAN_BG}
        self.assertEqual(len(dark), len(SPAN_BG))
        self.assertEqual(len(light), len(SPAN_BG))
        for label in SPAN_BG:
            self.assertTrue(span_bg(label, "dark").startswith("#"))
            self.assertTrue(span_fg(label, "light").startswith("#"))


class TestFormatting(unittest.TestCase):
    def test_resolve_overlaps_prefers_longer_spans(self) -> None:
        spans = [
            Span("private_person", 0, 5, "Alice"),
            Span("private_email", 2, 20, "lice sm@x.example"),
        ]
        visible, hidden = formatting.resolve_overlaps(spans)
        self.assertEqual([span.label for span in visible], ["private_email"])
        self.assertEqual([span.label for span in hidden], ["private_person"])

    def test_clamp_spans_protects_against_stale_offsets(self) -> None:
        spans = [Span("secret", 0, 999, "x"), Span("secret", 50, 40, "y"), Span("secret", 1, 3, "ab")]
        clamped = formatting.clamp_spans("hello", spans)
        self.assertEqual([span.end for span in clamped], [5, 3])
        self.assertTrue(all(span.end > span.start for span in clamped))

    def test_read_text_file_handles_windows_encodings(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "note.txt"
            path.write_bytes("caf\xe9 cp1252".encode("cp1252"))
            self.assertIn("café", formatting.read_text_file(path))
            utf16 = Path(folder) / "utf16.txt"
            utf16.write_bytes("héllo".encode("utf-16"))
            self.assertEqual(formatting.read_text_file(utf16), "héllo")

    def test_safe_stem(self) -> None:
        self.assertEqual(formatting.safe_stem("/tmp/My Report (2024).txt"), "My_Report_2024")
        self.assertEqual(formatting.safe_stem("###"), "document")
        self.assertEqual(formatting.safe_stem("a" * 200)[:80], "a" * 80)

    def test_table_rows_truncate_long_matches(self) -> None:
        rows = formatting.table_rows([Span("secret", 0, 80, "x" * 80)])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0][2].endswith("..."))
        self.assertEqual(len(rows[0]), 6)

    def test_batch_exports(self) -> None:
        backend = DemoBackend(Settings(engine="demo"))
        outcomes = [backend.redact(SAMPLE), backend.redact("nothing here")]
        outcomes[0].source = "/tmp/ticket 1.txt"
        outcomes[1].source = "/tmp/ticket 2.txt"

        jsonl = formatting.outcomes_to_jsonl(outcomes)
        self.assertEqual(len([line for line in jsonl.splitlines() if line]), 2)
        for line in jsonl.splitlines():
            self.assertEqual(json.loads(line)["schema_version"], 1)

        bundle = json.loads(formatting.outcomes_to_json(outcomes))
        self.assertEqual(bundle["count"], 2)
        self.assertEqual(bundle["aggregate"]["documents"], 2)

        report = formatting.batch_summary_markdown(outcomes, "demo")
        self.assertIn("# Privacy Filter batch report", report)
        self.assertIn("ticket 1.txt", report)
        self.assertIn("| Category | Count |", report)

    def test_plain_summary_mentions_counts_and_latency(self) -> None:
        outcome = DemoBackend(Settings(engine="demo")).redact(SAMPLE)
        summary = formatting.plain_summary(outcome)
        self.assertIn("span(s)", summary)
        self.assertIn("ms" if outcome.latency_ms < 1000 else "s", summary)

    def test_suggest_export_path(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            settings = Settings(export_dir=folder)
            path = formatting.suggest_export_path(settings, "/data/Ticket One.txt", "redacted", ".txt")
            self.assertEqual(path.parent, Path(folder))
            self.assertEqual(path.name, "Ticket_One-redacted.txt")


class TestEngineController(unittest.TestCase):
    """The inline engine runs jobs on the calling thread - deterministic tests."""

    def build(self, **overrides) -> tuple[EngineController, list]:  # noqa: ANN001
        settings = Settings(engine="demo", **overrides)
        messages: list = []
        controller = EngineController(
            settings=settings, host=None, on_message=lambda kind, payload: messages.append((kind, payload)), inline=True
        )
        controller.start()
        return controller, messages

    def kinds(self, messages: list) -> list[str]:
        return [kind for kind, _payload in messages]

    def test_redact_delivers_result_then_done(self) -> None:
        controller, messages = self.build()
        controller.redact(SAMPLE, source="ticket.txt")
        kinds = self.kinds(messages)
        self.assertIn(MSG_RESULT, kinds)
        self.assertEqual(kinds[-1], MSG_DONE)
        outcome = dict(messages)[MSG_RESULT]
        self.assertIsInstance(outcome, Outcome)
        self.assertGreater(outcome.span_count, 0)
        self.assertEqual(outcome.source, "ticket.txt")
        self.assertGreaterEqual(outcome.latency_ms, 0.0)
        self.assertFalse(controller.busy)

    def test_batch_reports_progress_per_item(self) -> None:
        controller, messages = self.build()
        controller.batch([("a.txt", SAMPLE), ("b.txt", "clean text"), ("c.txt", SAMPLE)])
        items = [payload for kind, payload in messages if kind == MSG_BATCH_ITEM]
        self.assertEqual(len(items), 3)
        self.assertEqual([item.source for item in items], ["a.txt", "b.txt", "c.txt"])
        progress = [payload for kind, payload in messages if kind == MSG_PROGRESS]
        self.assertIn((0, 3), progress)
        self.assertIn((3, 3), progress)

    def test_errors_are_reported_not_raised(self) -> None:
        class Boom(Backend):
            name = "boom"

            def describe(self):  # noqa: ANN201
                return {}

            def redact(self, text):  # noqa: ANN001, ARG002
                raise RuntimeError("kaboom")

        controller, messages = self.build()
        controller.backend = Boom()
        controller.redact("hello")
        errors = [payload for kind, payload in messages if kind == MSG_ERROR]
        self.assertTrue(errors and "kaboom" in errors[0])
        self.assertEqual(self.kinds(messages)[-1], MSG_DONE)
        self.assertFalse(controller.busy)

    def test_logs_from_backend_reach_the_ui(self) -> None:
        controller, messages = self.build()
        controller.backend._log("hello from backend")  # noqa: SLF001
        logs = [payload for kind, payload in messages if kind == MSG_LOG]
        self.assertIn("hello from backend", logs)

    def test_engine_rebuild_switches_backend(self) -> None:
        controller, _messages = self.build()  # starts on demo
        self.assertEqual(controller.backend.name, "demo")
        controller.settings.engine = "model"
        controller.request_backend_rebuild()
        controller.redact("Alice alice@example.com")
        # opf is not installed in CI, so the rebuild must surface a helpful error
        self.assertEqual(controller.backend.name, "opf")

    def test_settings_changes_are_picked_up_without_new_controller(self) -> None:
        controller, messages = self.build()
        controller.redact(SAMPLE)
        self.assertTrue(any("<PRIVATE_EMAIL>" in dict(messages)[MSG_RESULT].redacted_text for _ in [0]))
        controller.settings.output_mode = "redacted"
        messages.clear()
        controller.redact(SAMPLE)
        outcome = dict(messages)[MSG_RESULT]
        self.assertNotIn("<PRIVATE_EMAIL>", outcome.redacted_text)
        self.assertIn("<REDACTED>", outcome.redacted_text)

    def test_cancel_stops_a_batch(self) -> None:
        controller, messages = self.build()
        original = controller.backend.redact

        def slow(text: str):  # noqa: ANN001, ANN202
            controller.cancel()
            return original(text)

        controller.backend.redact = slow  # type: ignore[method-assign]
        controller.batch([("a.txt", SAMPLE), ("b.txt", SAMPLE), ("c.txt", SAMPLE)])
        items = [payload for kind, payload in messages if kind == MSG_BATCH_ITEM]
        self.assertEqual(len(items), 1)
        self.assertTrue(any("cancelled" in str(payload) for kind, payload in messages if kind == MSG_STATUS))

    def test_threaded_mode_starts_and_shuts_down(self) -> None:
        import threading

        class FakeHost:
            def __init__(self) -> None:
                self.calls = 0

            def after(self, _ms, func):  # noqa: ANN001, ANN202
                self.calls += 1
                return None

        settings = Settings(engine="demo")
        messages: list = []
        host = FakeHost()
        controller = EngineController(
            settings=settings, host=host, on_message=lambda kind, payload: messages.append((kind, payload))
        )
        controller.start()
        self.assertEqual(threading.active_count(), threading.active_count())
        controller.redact(SAMPLE)
        # drain without a Tk mainloop by polling the private queue directly
        import time

        deadline = time.time() + 5
        while time.time() < deadline and not any(kind == MSG_RESULT for kind, _ in messages):
            drained = False
            while True:
                try:
                    import queue as _queue

                    kind, payload = controller._messages.get_nowait()  # noqa: SLF001
                except _queue.Empty:
                    break
                drained = True
                messages.append((kind, payload))
                if kind == MSG_DONE:
                    controller._busy = max(0, controller._busy - 1)  # noqa: SLF001
            if not drained:
                time.sleep(0.02)
        controller.shutdown()
        self.assertTrue(any(kind == MSG_RESULT for kind, _ in messages))
        self.assertTrue(host.calls >= 1)


class TestThreadSafetySurface(unittest.TestCase):
    GUI_IMPORT = re.compile(r"^\s*(?:import|from)\s+(?:tkinter|customtkinter)[\w.]*", re.MULTILINE)

    def test_no_gui_imports_in_logic_modules(self) -> None:
        """models/backends/engine/formatting must stay importable without tkinter."""
        import opf_gui.backends as backends
        import opf_gui.engine as engine
        import opf_gui.formatting as formatting_module
        import opf_gui.models as models

        for module in (models, backends, engine, formatting_module):
            source = Path(module.__file__).read_text(encoding="utf-8")
            match = self.GUI_IMPORT.search(source)
            self.assertIsNone(match, f"{module.__file__} imports a GUI toolkit")

    def test_logic_modules_import_without_tkinter(self) -> None:
        """A subprocess without tkinter available must still import the logic layer."""
        import subprocess

        code = (
            "import sys; sys.modules['tkinter']=None;"
            "import opf_gui.models, opf_gui.backends, opf_gui.engine, opf_gui.formatting;"
            "print('ok')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ok", result.stdout)


class TestEnvironmentReport(unittest.TestCase):
    """`python -m opf_gui --check` must account for every declared dependency."""

    #: every third-party package the app can use, optional ones included
    DEPENDENCIES = ("tkinter", "customtkinter", "tkinterdnd2", "torch", "huggingface_hub")

    def test_report_names_every_dependency(self) -> None:
        from opf_gui.__main__ import environment_report

        report = environment_report(Settings())
        for module in self.DEPENDENCIES:
            self.assertIn(module, report)

    def test_report_is_headless(self) -> None:
        """The report itself must build without a display or a GUI toolkit."""
        import subprocess

        code = (
            "import sys; sys.modules['tkinter']=None; sys.modules['customtkinter']=None;"
            "from opf_gui.__main__ import environment_report;"
            "from opf_gui.models import Settings;"
            "print(environment_report(Settings()))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for module in self.DEPENDENCIES:
            self.assertIn(module, result.stdout)

    def test_probe_reports_missing_packages(self) -> None:
        from opf_gui.__main__ import _probe

        self.assertEqual(_probe("opf_gui_definitely_not_installed"), "missing")


def _srgb(value: int) -> float:
    channel = value / 255
    return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4


def _luminance(color: str) -> float:
    digits = color.lstrip("#")
    red, green, blue = (int(digits[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _srgb(red) + 0.7152 * _srgb(green) + 0.0722 * _srgb(blue)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG 2.1 contrast ratio between two #rrggbb colours."""
    high, low = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class TestThemeContrast(unittest.TestCase):
    """Status text must stay legible in both appearance modes."""

    #: editor background and toolbar frame (customtkinter's default frame greys)
    SURFACES = {"light": ("#fdfdfe", "#dedede"), "dark": ("#1f1f27", "#383838")}

    def test_status_colours_meet_wcag_aa_on_every_surface(self) -> None:
        for mode, surfaces in self.SURFACES.items():
            for state, pair in theme.STATUS_COLORS.items():
                for surface in surfaces:
                    ratio = contrast_ratio(pair[mode], surface)
                    self.assertGreaterEqual(ratio, 4.5, f"{state} {pair[mode]} on {surface} ({mode})")

    def test_light_mode_colours_are_darker_than_dark_mode(self) -> None:
        for state, pair in theme.STATUS_COLORS.items():
            self.assertLess(_luminance(pair["light"]), _luminance(pair["dark"]), state)

    def test_the_demo_orange_keeps_its_dark_mode_identity(self) -> None:
        self.assertEqual(theme.status_color("demo", "dark"), "#f0a020")
        self.assertNotEqual(theme.status_color("demo", "light"), "#f0a020")
        self.assertLess(contrast_ratio("#f0a020", "#fdfdfe"), 3.0)  # the old bug

    def test_status_color_falls_back_to_the_demo_shade(self) -> None:
        self.assertEqual(theme.status_color("mystery", "light"), theme.STATUS_COLORS["demo"]["light"])
        self.assertEqual(theme.status_color("mystery", "dark"), theme.STATUS_COLORS["demo"]["dark"])

    def test_pii_chips_are_legible_in_light_mode(self) -> None:
        for label in theme.known_labels():
            ratio = contrast_ratio(theme.span_fg(label, "light"), theme.span_bg(label, "light"))
            self.assertGreaterEqual(ratio, 4.5, label)

    def test_legend_counts_are_legible_in_light_mode(self) -> None:
        """Regression: light mode reused the pastel highlight as a text colour."""
        for label in theme.known_labels():
            accent = theme.span_accent(label, "light")
            self.assertNotEqual(accent, theme.span_bg(label, "light"), label)
            self.assertLess(_luminance(accent), 0.2, label)
            for surface in self.SURFACES["light"]:
                ratio = contrast_ratio(accent, surface)
                self.assertGreaterEqual(ratio, 4.5, f"{label} {accent} on {surface}")
        self.assertLess(contrast_ratio(theme.span_bg("private_person", "light"), "#fdfdfe"), 2.0)

    def test_legend_accents_keep_the_dark_mode_hues_and_stay_distinct(self) -> None:
        for label, pair in theme.SPAN_ACCENT.items():
            self.assertEqual(pair[0], theme.span_bg(label, "dark"), label)  # dark look unchanged
        self.assertEqual(
            len({theme.span_accent(label, "light") for label in theme.SPAN_ACCENT}),
            len(theme.SPAN_ACCENT),
        )

    def test_span_accent_falls_back_for_unknown_labels(self) -> None:
        self.assertEqual(theme.span_accent("mystery", "light"), theme.FALLBACK_ACCENT[1])
        self.assertEqual(theme.span_accent("mystery", "dark"), theme.FALLBACK_ACCENT[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
