"""Headless smoke tests for the GUI layer, using the tkinter/customtkinter stubs.

Run:  python tests/test_gui_smoke.py     (from the project root or tests/)
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import stub_gui  # noqa: E402  - must install stubs before opf_gui.app
from stub_gui import DIALOG_ANSWERS, MESSAGEBOX_CALLS, SimpleNamespace  # noqa: E402

stub_gui.install()

from opf_gui import dnd, theme  # noqa: E402
from opf_gui.app import ACCEPTED_BATCH, PrivacyFilterApp  # noqa: E402
from opf_gui.models import Settings  # noqa: E402
from opf_gui.widgets import span_tag  # noqa: E402

SAMPLE = (
    "Alice Smith (alice.smith@example.com, +1 415 555 0132) filed ticket 4111 1111 1111 1111 "
    "on 1990-01-02 from https://vendor.example.com/tickets/9."
)


def make_app(**overrides) -> PrivacyFilterApp:  # noqa: ANN003
    stub_gui.reset()
    settings = Settings(engine="demo", appearance="dark")
    for key, value in overrides.items():
        setattr(settings, key, value)
    return PrivacyFilterApp(settings=settings, inline_engine=True, start_text=SAMPLE, save_config=False)


HEADER_BUTTONS = (
    "clear_button", "redact_button", "open_button", "paste_button", "sample_button",
)


def widget_texts(widget: Any) -> list[str]:
    """Every ``text`` option in a widget subtree (stub-friendly tree walk)."""
    found = [str(widget.cget("text"))]
    for child in widget.winfo_children():
        found.extend(widget_texts(child))
    return found


class TestInputHeaderLayout(unittest.TestCase):
    def setUp(self) -> None:
        self.app = make_app()

    def test_buttons_sit_above_the_editor_in_workflow_order(self) -> None:
        header = self.app.redact_button.master
        self.assertEqual(header.grid_info_now["row"], 1)
        self.assertEqual(self.app.input_pane.grid_info_now["row"], 2)
        self.assertEqual(self.app.count_label.master.grid_info_now["row"], 3)

        buttons = [getattr(self.app, name) for name in HEADER_BUTTONS]
        for button in buttons:
            self.assertEqual(button.calls[0][0], "pack")
            self.assertEqual(button.calls[0][1]["side"], "right")
            self.assertEqual(button.master, header)
        # packed right-to-left, so the visible order is the reverse of pack order
        visible = [button.text for button in reversed(buttons)]
        self.assertEqual(visible, ["Sample", "Paste", "Open", "Redact", "Clear"])

    def test_char_count_is_the_last_row(self) -> None:
        self.assertEqual(self.app.count_label.cget("text"), f"{len(SAMPLE):,} chars")
        self.app.input_pane.set("12345")
        self.app._on_input_change()  # noqa: SLF001
        self.assertEqual(self.app.count_label.cget("text"), "5 chars")

    def test_input_editor_matches_output_editor_geometry(self) -> None:
        left = self.app.left_column
        output_tab = self.app.tabs.tab("Output")
        # spacer absorbing the tab strip (10+8+18 header rows + 6 inner padding),
        # then the button header, the growing pane row and the footer
        self.assertEqual(left.grid_rowconfigure(0, "minsize"), "42")
        self.assertEqual(left.grid_rowconfigure(1, "minsize"), "34")
        self.assertEqual(self.app.input_pane.grid_info_now["row"], 2)
        self.assertEqual(self.app.output_pane.grid_info_now["row"], 1)
        self.assertEqual(
            self.app.input_pane.grid_info_now["pady"], self.app.output_pane.grid_info_now["pady"]
        )
        self.assertEqual(
            self.app.input_pane.grid_info_now["padx"], self.app.output_pane.grid_info_now["padx"]
        )
        # header rows on both sides must be identical so the panes line up
        self.assertEqual(left.grid_rowconfigure(1, "minsize"), output_tab.grid_rowconfigure(0, "minsize"))

    def test_tab_strip_height_follows_widget_scaling(self) -> None:
        self.app.tabs.grid_rowconfigure(0, minsize=12.5)
        self.app.tabs.grid_rowconfigure(1, minsize=10.0)
        self.app.tabs.grid_rowconfigure(2, minsize=22.5)
        self.assertEqual(self.app._tab_strip_height(), 51)  # noqa: SLF001


class TestToolbarAndButtonStyling(unittest.TestCase):
    def test_toolbar_switches_are_segmented_and_decode_is_in_settings(self) -> None:
        from opf_gui.app import SettingsDialog

        app = make_app(decode_mode="argmax")
        for name, values in (
            ("engine_switch", ["model", "demo"]),
            ("output_switch", ["typed", "redacted"]),
            ("device_switch", ["auto", "cpu", "cuda"]),
            ("theme_switch", ["dark", "light"]),
        ):
            self.assertIsInstance(getattr(app, name), type(app.engine_switch))
            self.assertEqual(getattr(app, name).values, values)
        # Decode was removed from the toolbar and lives in the settings dialog.
        # hasattr()/getattr() cannot prove absence under the stubs: Widget.__getattr__
        # answers any public name with a recorded no-op, so every name "exists".
        # Assert against real widget state instead (as TestToolbarCleanup does).
        self.assertNotIn("decode_switch", vars(app))
        toolbar = app.engine_switch.master.master  # segmented button -> inner -> toolbar
        self.assertNotIn("Decode", [t for t in widget_texts(toolbar) if t])
        dialog = SettingsDialog(app, app.settings, on_apply=app._after_settings_change)
        self.assertEqual(dialog.decode_var.get(), "argmax")
        self.assertEqual(dialog.decode_var.get(), app.settings.decode_mode)

    def test_choice_widgets_apply_settings(self) -> None:
        from opf_gui.app import SettingsDialog

        app = make_app(decode_mode="argmax", device="auto")
        # Decode is now a settings-dialog control; apply it the way a user would.
        dialog = SettingsDialog(app, app.settings, on_apply=app._after_settings_change)
        self.assertEqual(dialog.decode_var.get(), "argmax")
        dialog.decode_var.set("viterbi")
        dialog._apply()  # noqa: SLF001
        self.assertEqual(app.settings.decode_mode, "viterbi")
        # The remaining toolbar switches still fire a callback on a real user click.
        app.device_switch.set("cuda")  # programmatic .set() does not fire the command
        self.assertEqual(app.settings.device, "auto")
        app.device_switch.choose("cuda")  # a genuine click does
        self.assertEqual(app.settings.device, "cuda")

    def test_transparent_buttons_are_legible_in_light_mode(self) -> None:
        app = make_app()
        buttons = {
            "Unload model": app.unload_button,
            "Warm up model": app.warmup_button,
            "Clear": app.clear_button,
        }
        for name, button in buttons.items():
            self.assertEqual(button.options["fg_color"], "transparent", name)
            text_color = button.options["text_color"]
            self.assertIsInstance(text_color, tuple, f"{name} needs a (light, dark) text colour")
            self.assertEqual(len(text_color), 2)
            self.assertTrue(theme_is_darker(text_color[0], text_color[1]), name)

    def test_ghost_button_helper_shape(self) -> None:
        kwargs = theme.ghost_button()
        self.assertEqual(kwargs["fg_color"], "transparent")
        self.assertEqual(kwargs["text_color"], ("#1b1b22", "#e8e8ee"))
        self.assertEqual(theme.ghost_button(text_color="red")["text_color"], "red")
        # returned dict is a copy
        theme.ghost_button()["border_width"] = 99
        self.assertEqual(theme.GHOST_BUTTON["border_width"], 1)


def theme_is_darker(light: str, dark: str) -> bool:
    """customtkinter tuples are (light-mode, dark-mode) values."""
    return _luminance(light) < _luminance(dark)


def _luminance(color: str) -> float:
    value = color.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


class TestRedactionFlow(unittest.TestCase):
    def setUp(self) -> None:
        self.app = make_app()

    def test_redact_updates_every_view(self) -> None:
        self.app.run_redact()
        outcome = self.app.last_outcome
        self.assertIsNotNone(outcome)
        self.assertGreater(outcome.span_count, 0)
        self.assertIn("<PRIVATE_EMAIL>", self.app.output_pane.get())
        self.assertNotIn("alice.smith@example.com", self.app.output_pane.get())
        self.assertGreaterEqual(len(self.app.span_table.tree.rows()), outcome.span_count)
        self.assertIn('"schema_version"', self.app.json_box.get())
        self.assertIn("span", self.app.metrics_label.cget("text"))
        # input pane is tagged with the detected labels
        tagged = self.app.input_pane.text.tag_names()
        self.assertIn(span_tag("private_email"), tagged)
        covered = self._tagged_text(span_tag("private_email"))
        self.assertIn("alice.smith@example.com", covered)

    def _tagged_text(self, tag: str) -> str:
        widget = self.app.input_pane.text
        ranges = widget.tag_ranges(tag)
        self.assertEqual(len(ranges) % 2, 0)
        return "".join(widget.get(ranges[i], ranges[i + 1]) for i in range(0, len(ranges), 2))

    def test_multiline_input_highlights_the_exact_span(self) -> None:
        # spans are character offsets, so highlighting must survive newlines
        self.app.input_pane.set(
            "line one\nline two\ncontact me at bob@corp.example or 415 555 0132\nfooter\n"
        )
        self.app.run_redact()
        covered = self._tagged_text(span_tag("private_email"))
        self.assertEqual(covered, "bob@corp.example")

    def test_loading_a_new_file_clears_previous_highlights(self) -> None:
        # Highlight PII is on by default, so a redaction paints the input pane.
        self.app.run_redact()
        self.assertTrue(self.app.input_pane._spans)  # noqa: SLF001
        email_tag = span_tag("private_email")
        self.assertTrue(self.app.input_pane.text.tag_offsets(email_tag))

        # A fresh file (that itself contains PII) is loaded. The previous file's
        # marks must disappear, and the new text must NOT be auto-highlighted -
        # highlighting happens only after Redact is pressed.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fresh.txt"
            path.write_text("Call 415 555 0132 or alice.smith@example.com.", encoding="utf-8")
            self.app._load_paths([path])  # noqa: SLF001
        loaded = self.app.input_pane.get()
        self.assertIn("alice.smith@example.com", loaded)
        # The pane no longer holds any spans, so a repaint can't resurface them...
        self.assertEqual(self.app.input_pane._spans, [])  # noqa: SLF001
        # ...and no PII range is visible over the freshly loaded text.
        for tag in self.app.input_pane.text.tag_names():
            if tag.startswith("opf_span::"):
                for start, _stop in self.app.input_pane.text.tag_offsets(tag):
                    self.assertGreaterEqual(start, len(loaded))

        # Pressing Redact on the (PII-bearing) new text re-highlights as usual...
        self.app.run_redact()
        self.assertTrue(self.app.input_pane._spans)  # noqa: SLF001
        # ...and the Sample button clears them again via the same replacement path.
        self.app.load_sample()
        self.assertEqual(self.app.input_pane._spans, [])  # noqa: SLF001

    def test_span_selection_locates_and_switches_tab(self) -> None:
        self.app.run_redact()
        self.app.tabs.set("Batch")
        self.app.span_table.tree.select_row(0)
        self.assertEqual(self.app.tabs.get(), "Review")
        self.assertTrue(self.app.review_pane.text.seen)

    def test_output_mode_switch_re_redacts(self) -> None:
        self.app.output_switch.choose("redacted")
        self.assertEqual(self.app.settings.output_mode, "redacted")
        self.app.run_redact()
        self.assertIn("<REDACTED>", self.app.output_pane.get())
        self.assertNotIn("<PRIVATE_EMAIL>", self.app.output_pane.get())

    def test_clear_resets_everything(self) -> None:
        self.app.run_redact()
        self.app.clear_all()
        self.assertEqual(self.app.input_pane.get(), "")
        self.assertEqual(self.app.count_label.cget("text"), "0 chars")
        self.assertIsNone(self.app.last_outcome)
        self.assertEqual(self.app.span_table.tree.rows(), [])

    def test_missing_opf_package_falls_back_to_demo(self) -> None:
        self.app.engine_switch.choose("model")
        # opf is not installed in this environment, so the app must stay usable
        self.assertEqual(self.app.settings.engine, "demo")
        self.assertEqual(self.app.engine_switch.get(), "demo")
        self.assertIn("opf package missing", self.app.log_box.get())
        self.assertTrue(MESSAGEBOX_CALLS and MESSAGEBOX_CALLS[-1][0] == "showwarning")

    def test_font_size_change_repaints(self) -> None:
        before = self.app.settings.font_size
        self.app.change_font_size(2)
        self.assertEqual(self.app.settings.font_size, before + 2)
        self.app.change_font_size(-2)
        self.assertEqual(self.app.settings.font_size, before)

    def test_light_mode_recolours_panes(self) -> None:
        dark_bg = self.app.input_pane.text.cget("bg")
        self.app.theme_switch.choose("light")
        self.assertEqual(self.app.settings.appearance, "light")
        self.assertNotEqual(self.app.input_pane.text.cget("bg"), dark_bg)
        self.app.theme_switch.choose("dark")
        self.assertEqual(self.app.input_pane.text.cget("bg"), dark_bg)


class TestDragAndDrop(unittest.TestCase):
    def setUp(self) -> None:
        self.app = make_app()

    def tearDown(self) -> None:
        for name in ("enable", "register"):
            original = getattr(self, f"real_{name}", None)
            if original is not None:
                setattr(dnd, name, original)

    def patch(self, *, available: bool = True) -> None:
        self.real_enable = dnd.enable
        self.real_register = dnd.register
        dnd.enable = lambda _root: "3.2-stub" if available else None  # type: ignore[assignment]
        self.zones: list[dnd.DropZone] = []

        def fake_register(widget, on_files, **kwargs):  # noqa: ANN001, ANN202
            zone = dnd.DropZone(widget, on_files, **kwargs)
            self.zones.append(zone)
            return zone

        dnd.register = fake_register  # type: ignore[assignment]

    def test_unavailable_backend_is_logged_and_tolerated(self) -> None:
        self.patch(available=False)
        self.app._setup_drag_and_drop()  # noqa: SLF001
        self.assertEqual(self.app._drop_zones, [])  # noqa: SLF001
        self.assertIn("Drag & drop unavailable", self.app.log_box.get())

    def test_disabled_by_setting(self) -> None:
        self.patch()
        self.app.settings.drag_and_drop = False
        self.app._setup_drag_and_drop()  # noqa: SLF001
        self.assertEqual(self.app._drop_zones, [])
        self.assertIn("switched off", self.app.log_box.get())

    def test_single_dropped_file_loads_into_editor(self) -> None:
        self.patch()
        self.app._setup_drag_and_drop()  # noqa: SLF001
        self.assertEqual(len(self.app._drop_zones), 1)  # noqa: SLF001
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ticket one.txt"
            path.write_text("Call Alice on 415 555 0132", encoding="utf-8")
            self.app._on_drop_files([path], [])  # noqa: SLF001
            self.assertIn("415 555 0132", self.app.input_pane.get())
            self.assertEqual(Path(self.app.current_source).name, "ticket one.txt")
            self.assertIn("Dropped ticket one.txt", self.app.log_box.get())

    def test_multiple_drops_are_queued_for_batch(self) -> None:
        self.patch()
        self.app._setup_drag_and_drop()  # noqa: SLF001
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index in range(3):
                path = Path(folder) / f"note{index}.txt"
                path.write_text(f"note {index} alice@example.com", encoding="utf-8")
                paths.append(path)
            self.app._on_drop_files(paths, [])  # noqa: SLF001
            self.assertEqual(self.app.tabs.get(), "Batch")
            # the first file fills the editor, the rest are queued for batch
            self.assertEqual(Path(self.app.current_source).name, "note0.txt")
            self.assertEqual([p.name for p in self.app.batch_files], ["note1.txt", "note2.txt"])

    def test_folder_drop_expands_supported_files(self) -> None:
        self.patch()
        self.app._setup_drag_and_drop()  # noqa: SLF001
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "b.md").write_text("b", encoding="utf-8")
            (root / "image.png").write_bytes(b"\x89PNG")
            files, rejected = dnd.filter_paths([root], ACCEPTED_BATCH)
            self.app._on_drop_files(files, rejected)  # noqa: SLF001
            self.assertEqual([p.name for p in self.app.batch_files], ["b.md"])
            self.assertEqual(self.app.input_pane.get(), "a")

    def test_unsupported_drop_is_rejected_with_feedback(self) -> None:
        self.patch()
        self.app._setup_drag_and_drop()  # noqa: SLF001
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "payload.exe"
            binary.write_bytes(b"not text")
            files, rejected = dnd.filter_paths([binary], ACCEPTED_BATCH)
            self.app._on_drop_files(files, rejected)  # noqa: SLF001
            self.assertEqual(files, [])
            self.assertIn("not a supported text file", self.app.status_label.cget("text"))
            self.assertIn("Ignored unsupported drop", self.app.log_box.get())

    def test_drop_data_parsing_handles_spaces_and_many_files(self) -> None:
        payload = "{/tmp/my report.txt} {/tmp/second one.log} /tmp/plain.txt"
        paths = dnd.parse_drop_data(self.app.input_pane.text, payload)
        self.assertEqual([str(p) for p in paths], ["/tmp/my report.txt", "/tmp/second one.log", "/tmp/plain.txt"])

    def test_drag_feedback_highlights_pane_and_status(self) -> None:
        self.patch()
        self.app._setup_drag_and_drop()  # noqa: SLF001
        self.app.set_status("Idle")
        zone = self.app._drop_zones[0]  # noqa: SLF001
        active = theme.pane_colors("dark")["active"]
        zone._on_enter(SimpleNamespace(data="/tmp/a.txt"))  # noqa: SLF001
        self.assertEqual(self.app.input_pane.text.cget("highlightbackground"), active)
        self.assertIn("Release to load", self.app.status_label.cget("text"))
        zone._on_leave(SimpleNamespace())  # noqa: SLF001
        self.assertEqual(self.app.status_label.cget("text"), "Idle")
        self.assertEqual(
            self.app.input_pane.text.cget("highlightbackground"), theme.pane_colors("dark")["border"]
        )

    def test_settings_toggle_reregisters_targets(self) -> None:
        self.patch()
        self.app._setup_drag_and_drop()  # noqa: SLF001
        self.app.settings.drag_and_drop = False
        self.app._apply_drag_and_drop()  # noqa: SLF001
        self.assertEqual(self.app._drop_zones, [])  # noqa: SLF001
        self.app.settings.drag_and_drop = True
        self.app._apply_drag_and_drop()  # noqa: SLF001
        self.assertEqual(len(self.app._drop_zones), 1)


class FakeDnDWidget:
    """Mimics the methods tkinterdnd2 bolts onto tkinter.BaseWidget."""

    def __init__(self) -> None:
        self.registered: list[tuple[Any, ...]] = []
        self.bindings: dict[str, Any] = {}
        self.unregistered = False

    def drop_target_register(self, *types: Any) -> None:
        self.registered.append(types)

    def dnd_bind(self, sequence: str, func: Any = None) -> Any:
        if func is None:
            return self.bindings.get(sequence)
        if func == "":
            self.bindings.pop(sequence, None)
            return None
        self.bindings[sequence] = func
        return f"after{id(func)}"

    def drop_target_unregister(self) -> None:
        self.unregistered = True


class TestDropZoneProtocol(unittest.TestCase):
    """Guards the real tkinterdnd2 API surface (constants, unbinding, actions)."""

    MODULE = SimpleNamespace(
        DND_FILES="DND_Files",
        COPY="copy",
        TkinterDnD=SimpleNamespace(require=lambda _root: "3.4"),
    )

    def setUp(self) -> None:
        self.widget = FakeDnDWidget()
        self.dropped: list[tuple[list, list]] = []
        self.zone = dnd.DropZone(self.widget, lambda files, rejected: self.dropped.append((files, rejected)))

    def test_install_uses_the_dnd_files_type_and_binds_all_events(self) -> None:
        self.assertTrue(self.zone.install(self.MODULE))
        self.assertEqual(self.widget.registered, [("DND_Files",)])
        self.assertEqual(
            set(self.widget.bindings),
            {"<<DropEnter>>", "<<DropPosition>>", "<<DropLeave>>", "<<Drop>>"},
        )

    def test_drop_callback_returns_the_copy_action(self) -> None:
        self.zone.install(self.MODULE)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "a.txt"
            path.write_text("hello", encoding="utf-8")
            action = self.widget.bindings["<<Drop>>"](SimpleNamespace(data=str(path)))
        self.assertEqual(action, "copy")
        self.assertEqual([p.name for p in self.dropped[0][0]], ["a.txt"])

    def test_remove_unbinds_and_unregisters(self) -> None:
        self.zone.install(self.MODULE)
        self.zone.remove()
        self.assertEqual(self.widget.bindings, {})
        self.assertTrue(self.widget.unregistered)

    def test_install_fails_cleanly_without_tkdnd_hooks(self) -> None:
        class Plain:
            pass

        zone = dnd.DropZone(Plain(), lambda _f, _r: None)  # type: ignore[arg-type]
        self.assertFalse(zone.install(self.MODULE))
        self.assertEqual(zone._bound, [])  # noqa: SLF001

    def test_enable_prefers_require_and_falls_back_to_private_loader(self) -> None:
        original = dnd.dnd_module
        try:
            dnd.dnd_module = lambda: self.MODULE  # type: ignore[assignment]
            self.assertEqual(dnd.enable(object()), "3.4")
            legacy = SimpleNamespace(TkinterDnD=SimpleNamespace(_require=lambda _root: "2.9"))
            dnd.dnd_module = lambda: legacy  # type: ignore[assignment]
            self.assertEqual(dnd.enable(object()), "2.9")
            dnd.dnd_module = lambda: SimpleNamespace(TkinterDnD=SimpleNamespace())  # type: ignore[assignment]
            self.assertIsNone(dnd.enable(object()))
        finally:
            dnd.dnd_module = original  # type: ignore[assignment]

    def test_register_wires_a_real_zone(self) -> None:
        original = dnd.dnd_module
        try:
            dnd.dnd_module = lambda: self.MODULE  # type: ignore[assignment]
            zone = dnd.register(self.widget, lambda _f, _r: None)
            self.assertIsInstance(zone, dnd.DropZone)
            self.assertEqual(self.widget.registered, [("DND_Files",)])
        finally:
            dnd.dnd_module = original  # type: ignore[assignment]


class TestActivityLog(unittest.TestCase):
    """The Activity log tab is read-only, but still has to fill up."""

    def setUp(self) -> None:
        self.app = make_app()

    def test_startup_activity_is_visible_and_box_stays_read_only(self) -> None:
        self.assertEqual(self.app.log_box.cget("state"), "disabled")
        self.assertIn("Ready.", self.app.console.text())
        self.app.log("Something happened", level="warn")
        self.assertIn("[warn] Something happened", self.app.console.text())
        self.assertEqual(self.app.log_box.cget("state"), "disabled")

    def test_writing_to_the_disabled_box_directly_raises(self) -> None:
        # this is exactly what used to happen inside LogConsole.log()
        with self.assertRaises(stub_gui.TclError):
            self.app.log_box.insert("end", "nope\n")
        with self.assertRaises(stub_gui.TclError):
            self.app.log_box.delete("1.0", "end")

    def test_redaction_appends_activity(self) -> None:
        before = len(self.app.console.text().splitlines())
        self.app.run_redact()
        after = len(self.app.console.text().splitlines())
        self.assertGreater(after, before)

    def test_levels_are_tagged_and_recoloured(self) -> None:
        self.app.log("disk almost full", level="warn")
        self.app.log("model exploded", level="error")
        self.assertTrue(self.app.log_box.tag_offsets("opf_warn"))
        self.assertTrue(self.app.log_box.tag_offsets("opf_error"))
        dark = self.app.log_box.tag_cget("opf_error", "foreground")
        self.app.console.apply_appearance("light")
        self.assertEqual(self.app.log_box.tag_cget("opf_error", "foreground"), "#a51d2d")
        self.app.console.apply_appearance("dark")
        self.assertEqual(self.app.log_box.tag_cget("opf_error", "foreground"), dark)

    def test_log_is_trimmed_to_a_bounded_number_of_lines(self) -> None:
        for index in range(1600):
            self.app.log(f"line {index}")
        lines = self.app.console.text().splitlines()
        self.assertLessEqual(len(lines), self.app.console.MAX_LINES)
        self.assertIn("line 1599", lines[-1])

    def test_copy_and_clear_buttons(self) -> None:
        self.app._clear_log()  # noqa: SLF001
        self.app._copy_log()  # noqa: SLF001
        self.assertEqual(self.app.status_label.cget("text"), "Activity log is empty")
        self.app.log("notice me")
        self.app._copy_log()  # noqa: SLF001
        self.assertIn("notice me", stub_gui.CLIPBOARD[0])
        self.assertIn("copied", self.app.status_label.cget("text"))
        self.app._clear_log()  # noqa: SLF001
        self.assertEqual(self.app.console.text(), "")
        self.assertEqual(self.app.log_box.cget("state"), "disabled")


class FakeOpfBackend:
    name = "opf"

    def describe(self) -> dict[str, str]:
        return {"Model": "opf-21m", "Device": "cpu"}


class BrokenBackend:
    name = "opf"

    def describe(self) -> dict[str, str]:
        raise RuntimeError("no checkpoint")


class TestToolbarCleanup(unittest.TestCase):
    """Redundant controls (toolbar badge, Cancel button) are gone; the
    'Detection summary' panel is the single engine-status surface."""

    def setUp(self) -> None:
        self.app = make_app()

    def _use_backend(self, backend: Any) -> None:
        original = self.app.engine.backend
        self.app.engine.backend = backend
        self.addCleanup(setattr, self.app.engine, "backend", original)

    def test_redundant_controls_are_absent(self) -> None:
        attrs = vars(self.app)
        for removed in ("engine_badge", "cancel_button", "decode_switch"):
            self.assertNotIn(removed, attrs)

    def test_demo_panel_names_the_engine(self) -> None:
        self.assertIn("Demo", self.app.engine_info_label.cget("text"))

    def test_model_panel_lists_the_checkpoint(self) -> None:
        self._use_backend(FakeOpfBackend())
        self.app._refresh_engine_info()  # noqa: SLF001
        self.assertIn("Model: opf-21m", self.app.engine_info_label.cget("text"))

    def test_unavailable_engine_flags_the_panel(self) -> None:
        self._use_backend(BrokenBackend())
        self.app._refresh_engine_info()  # noqa: SLF001
        self.assertIn("unavailable", self.app.engine_info_label.cget("text"))


class TestSettingsDialog(unittest.TestCase):
    def test_apply_roundtrip(self) -> None:
        from opf_gui.app import SettingsDialog

        app = make_app()
        dialog = SettingsDialog(app, app.settings, on_apply=app._after_settings_change)  # noqa: SLF001
        dialog.checkpoint_var.set("/opt/opf/checkpoint")
        dialog.nctx_var.set("32768")
        dialog.drop_var.set(False)
        dialog.trim_var.set(False)
        dialog._apply()  # noqa: SLF001
        self.assertEqual(app.settings.checkpoint, "/opt/opf/checkpoint")
        self.assertEqual(app.settings.n_ctx, "32768")
        self.assertFalse(app.settings.drag_and_drop)
        self.assertFalse(app.settings.trim_whitespace)
        self.assertEqual(app.settings.n_ctx_value, 32768)

    def test_cancel_leaves_settings_untouched(self) -> None:
        from opf_gui.app import SettingsDialog

        app = make_app()
        before = app.settings.to_dict()
        dialog = SettingsDialog(app, app.settings, on_apply=app._after_settings_change)  # noqa: SLF001
        dialog.nctx_var.set("999")
        dialog.destroy()
        self.assertEqual(app.settings.to_dict(), before)


class TestAppLifecycle(unittest.TestCase):
    def test_close_saves_and_shuts_down(self) -> None:
        app = make_app()
        app._on_close()  # noqa: SLF001
        self.assertTrue(app._quitting)  # noqa: SLF001

    def test_menu_has_expected_commands(self) -> None:
        app = make_app()
        labels = [entry[1].get("label") for entry in app.menu_bar.entries]
        self.assertIn("File", labels)
        self.assertIn("Help", labels)

    def test_messagebox_not_used_on_happy_path(self) -> None:
        app = make_app()
        app.run_redact()
        self.assertEqual(MESSAGEBOX_CALLS, [])


if __name__ == "__main__":
    result = unittest.main(verbosity=2, exit=False)
    if stub_gui.UNKNOWN_CALLS:
        # Methods the app called that the stub does not model. Real Tk almost
        # certainly has them, but this list is worth a glance after refactors.
        print("\nstub: unmodelled widget calls ->", ", ".join(sorted(stub_gui.UNKNOWN_CALLS)))
    sys.exit(0 if result.result.wasSuccessful() else 1)
