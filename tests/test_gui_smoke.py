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

from opf_gui import __version__, dnd, formatting, theme  # noqa: E402
from opf_gui.app import ACCEPTED_BATCH, APP_TITLE, VIEWS, PrivacyFilterApp  # noqa: E402
from opf_gui.models import Outcome, Settings, Span  # noqa: E402
from opf_gui.widgets import span_tag  # noqa: E402

SAMPLE = (
    "Alice Smith (alice.smith@example.com, +1 415 555 0132) filed ticket 4111 1111 1111 1111 "
    "on 1990-01-02 from https://vendor.example.com/tickets/9."
)


def make_app(start_text: str | None = SAMPLE, **overrides) -> PrivacyFilterApp:  # noqa: ANN003
    stub_gui.reset()
    settings = Settings(engine="demo", appearance="dark")
    for key, value in overrides.items():
        setattr(settings, key, value)
    return PrivacyFilterApp(settings=settings, inline_engine=True, start_text=start_text, save_config=False)


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
        self.assertEqual(header.grid_info_now["row"], 0)
        self.assertEqual(self.app.input_pane.grid_info_now["row"], 1)
        self.assertEqual(self.app.count_label.master.grid_info_now["row"], 2)

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
        # Both columns start at the same pixel row - the view switch lives in the
        # banner, so there is no strip-height spacer above the input buttons -
        # and they repeat the same three rows: header, growing pane, footer.
        self.assertEqual(left.grid_rowconfigure(0, "minsize"), "34")
        self.assertEqual(left.grid_rowconfigure(2, "minsize"), "32")
        self.assertEqual(self.app.input_pane.grid_info_now["row"], 1)
        self.assertEqual(self.app.output_pane.grid_info_now["row"], 1)
        self.assertEqual(
            self.app.input_pane.grid_info_now["pady"], self.app.output_pane.grid_info_now["pady"]
        )
        self.assertEqual(
            self.app.input_pane.grid_info_now["padx"], self.app.output_pane.grid_info_now["padx"]
        )
        # header and footer rows on both sides must be identical so the two
        # editors end up the same height, edge for edge
        self.assertEqual(left.grid_rowconfigure(0, "minsize"), output_tab.grid_rowconfigure(0, "minsize"))
        self.assertEqual(left.grid_rowconfigure(2, "minsize"), output_tab.grid_rowconfigure(2, "minsize"))

    def test_both_editor_panes_share_one_panel_grey(self) -> None:
        # The results deck nests a page frame per view, and customtkinter paints a
        # nested frame one grey darker than a bare one. The input panel asks for that
        # inner grey explicitly, otherwise the two panes sit on different greys.
        self.assertEqual(self.app.left_column.cget("fg_color"), theme.nested_panel_bg())

    def test_panel_grey_is_a_light_dark_pair(self) -> None:
        # customtkinter tuples are (light-mode, dark-mode); under the stubs there is
        # no live theme to read, so this checks the hex fallback is ordered right.
        light, dark = theme.nested_panel_bg()
        self.assertTrue(theme_is_darker(dark, light), (light, dark))

    def test_editor_columns_stay_centred_in_every_view(self) -> None:
        body = self.app.left_column.master
        for column in (0, 1):
            self.assertEqual(body.grid_columnconfigure(column, "weight"), "1")
            self.assertEqual(body.grid_columnconfigure(column, "uniform"), "panes")
        # One uniform group means no view - not even the wide Batch toolbar -
        # can move the divider between the two text panes.
        for view in VIEWS:
            self.app.show_view(view)
            self.assertEqual(self.app.tabs.get(), view)
            self.assertEqual(self.app.tabs.tab(view).grid_info_now["row"], 0)

    def test_view_switch_lives_in_the_banner_and_drives_the_deck(self) -> None:
        # Right-aligned in the banner, above the Detection summary panel.
        self.assertEqual(self.app.view_switch.values, list(VIEWS))
        self.assertEqual(self.app.view_switch.grid_info_now["sticky"], "e")
        toolbar = self.app.engine_switch.master
        captions = [
            child.cget("text")
            for child in toolbar.winfo_children()
            if child.grid_info_now.get("row") == 0
        ]
        self.assertEqual(captions[-1], "Results view")
        # The deck has no strip of its own: its page row is the whole frame.
        self.assertEqual(self.app.tabs.grid_rowconfigure(0, "weight"), "1")
        self.assertNotIn("Results view", widget_texts(self.app.tabs))

        # a click on the switch swaps pages and only one page stays mapped
        self.app.view_switch.choose("JSON")
        self.assertEqual(self.app.tabs.get(), "JSON")
        self.assertEqual(self.app.tabs.tab("JSON").grid_info_now["sticky"], "nsew")
        self.assertEqual(self.app.tabs.tab("Output").calls[-1][0], "grid_forget")
        # and a programmatic jump (span click, menu, multi-file drop) keeps the
        # switch in step
        self.app.show_view("Log")
        self.assertEqual(self.app.view_switch.get(), "Log")

    def test_the_banner_switch_opens_highlighted_on_the_view_that_is_showing(self) -> None:
        # A CTkSegmentedButton selects nothing on its own, so an app that opens on
        # a page has to point the switch at it - otherwise "Output" reads as
        # unselected while the Output page is on screen.
        self.assertEqual(self.app.tabs.get(), "Output")
        self.assertEqual(self.app.view_switch.get(), self.app.tabs.get())
        for view in VIEWS:
            self.app.show_view(view)
            self.assertEqual(self.app.view_switch.get(), view)

    def test_unknown_view_is_an_error(self) -> None:
        from opf_gui.widgets import TabDeck

        with self.assertRaises(KeyError):
            self.app.tabs.tab("Nope")
        with self.assertRaises(KeyError):
            TabDeck(self.app.left_column, ("A",)).set("B")


class TestToolbarAndButtonStyling(unittest.TestCase):
    def test_toolbar_switches_are_segmented_and_decode_is_in_settings(self) -> None:
        from opf_gui.app import SettingsDialog

        app = make_app(decode_mode="argmax")
        for name, values in (
            ("engine_switch", ["model", "demo"]),
            ("model_switch", ["load", "unload"]),
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
        app.model_warm = True  # a warm model is what ghosts the warm-up button
        app.input_pane.set("")  # an empty editor is what ghosts Clear
        app._style_warmup_button()  # noqa: SLF001
        app._style_clear_button()  # noqa: SLF001
        buttons = {
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


class TestButtonAvailability(unittest.TestCase):
    """`Clear` and `Copy log` track what they can act on: accent face while there
    is text to clear / copy, ghosted while there is not."""

    def setUp(self) -> None:
        self.app = make_app()

    def face(self, button: Any) -> str:
        return "ghost" if button.options.get("fg_color") == "transparent" else "active"

    def type_into_editor(self, text: str) -> None:
        """A real edit fires the pane's change callback; set() deliberately does not."""
        self.app.input_pane.text.insert("insert", text)
        self.app._on_input_change()  # noqa: SLF001

    def test_clear_is_active_while_the_editor_holds_text(self) -> None:
        self.assertEqual(self.face(self.app.clear_button), "active")

    def test_clear_starts_ghosted_on_an_empty_editor(self) -> None:
        app = make_app(start_text="")
        self.assertEqual(self.face(app.clear_button), "ghost")
        app.input_pane.text.insert("1.0", "a name and an email")
        app._on_input_change()  # noqa: SLF001
        self.assertEqual(self.face(app.clear_button), "active")

    def test_clear_ghosts_when_the_editor_is_emptied(self) -> None:
        self.app.clear_all()
        self.assertEqual(self.face(self.app.clear_button), "ghost")
        self.assertEqual(self.app.count_label.cget("text"), "0 chars")
        self.app.load_sample()
        self.assertEqual(self.face(self.app.clear_button), "active")
        self.type_into_editor(" more text")
        self.assertEqual(self.face(self.app.clear_button), "active")
        self.app.input_pane.text.delete("1.0", "end")
        self.app._on_input_change()  # noqa: SLF001
        self.assertEqual(self.face(self.app.clear_button), "ghost")

    def test_copy_log_is_ghosted_on_an_empty_log(self) -> None:
        self.app._clear_log()  # noqa: SLF001 - the startup lines are log text too
        self.assertEqual(self.app.console.text(), "")
        self.assertEqual(self.face(self.app.copy_log_button), "ghost")

    def test_copy_log_is_active_while_the_log_has_text(self) -> None:
        self.app._clear_log()  # noqa: SLF001
        self.assertEqual(self.face(self.app.copy_log_button), "ghost")
        self.app.log("ticket 4111 redacted")
        self.assertEqual(self.face(self.app.copy_log_button), "active")
        self.app._copy_log()  # noqa: SLF001 - copying leaves the feed (and the face) alone
        self.assertEqual(self.face(self.app.copy_log_button), "active")
        self.app._clear_log()  # noqa: SLF001
        self.assertEqual(self.face(self.app.copy_log_button), "ghost")

    def test_redaction_makes_copy_log_usable(self) -> None:
        self.app._clear_log()  # noqa: SLF001
        self.app.run_redact()
        self.assertEqual(self.face(self.app.copy_log_button), "active")

    def test_the_faces_survive_a_theme_switch(self) -> None:
        self.app._clear_log()  # noqa: SLF001
        self.app.theme_switch.choose("light")
        self.assertEqual(self.face(self.app.clear_button), "active")
        self.assertEqual(self.face(self.app.copy_log_button), "ghost")
        self.app.theme_switch.choose("dark")
        self.assertEqual(self.face(self.app.clear_button), "active")

    def test_an_appearance_refresh_repaints_both_faces(self) -> None:
        # A repaint re-reads the palette, so the buttons must be re-faced and not
        # left holding colours (or a ghost) from before the theme changed.
        app = make_app(start_text="")
        app.log("checkpoint downloaded")  # noqa: SLF001 - makes Copy log usable
        app._clear_log()  # noqa: SLF001 - then it has nothing to copy again
        before = (len(app.clear_button.calls), len(app.copy_log_button.calls))
        app._apply_appearance()  # noqa: SLF001
        self.assertGreater(len(app.clear_button.calls), before[0])
        self.assertGreater(len(app.copy_log_button.calls), before[1])
        self.assertEqual(self.face(app.clear_button), "ghost")
        self.assertEqual(self.face(app.copy_log_button), "ghost")


class TestRedactionFlow(unittest.TestCase):
    def setUp(self) -> None:
        self.app = make_app()

    def test_the_summary_panel_wraps_over_long_labels(self) -> None:
        # The span counts above "Warm up model" share that panel's narrow column,
        # so nothing in them may be a single unbreakable run of characters.
        self.app.show_outcome(
            Outcome(
                text="x",
                spans=[Span("CustomerTaxIdentificationNumber", 0, 1, "x", "<PRIVATE_SECRET>")],
                redacted_text="<PRIVATE_SECRET>",
                engine="model",
                latency_ms=2050.0,
            )
        )
        text = self.app.summary_label.cget("text")
        self.assertIn("1 span(s) in", text)
        counts = [line for line in text.splitlines() if line.startswith("1 x")]
        self.assertEqual(len(counts), 1)
        # the 29-character label name did not fit, so it ran onto a second line
        self.assertNotIn("Customertaxidentificationnumber", counts[0])
        for token in text.replace("\n", " ").split(" "):
            self.assertLessEqual(len(token), formatting.LABEL_MAX_RUN, text)
        self.assertIn("Customertaxidentificationnumber", text.replace("\n", ""))

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

    def test_a_fresh_log_opens_with_the_app_version(self) -> None:
        # `Copy log` is how a feed reaches a support ticket, so the very first
        # line has to name the build that produced it.
        lines = self.app.console.text().splitlines()
        self.assertIn(f"{APP_TITLE} v{__version__}", lines[0])

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


class LongPathBackend:
    """A model backend reporting a checkpoint path with no spaces in it."""

    name = "opf"

    CHECKPOINT = "/home/ana/.opf/privacy_filter"

    def describe(self) -> dict[str, str]:
        return {
            "Engine": "OpenAI Privacy Filter",
            "Checkpoint": self.CHECKPOINT,
            "Device": "cuda",
            "Context window": "model default",
        }


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
        for removed in ("engine_badge", "cancel_button", "decode_switch", "load_button", "unload_button"):
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

    def test_the_checkpoint_path_wraps_inside_the_panel(self) -> None:
        # A label's wraplength only breaks lines at whitespace, so the model's
        # space-free checkpoint path ran off the edge of the Detection summary
        # panel while the Demo engine's wording wrapped neatly. Above the
        # "Warm up model" button, both engines have to fit.
        self._use_backend(LongPathBackend())
        self.app._refresh_engine_info()  # noqa: SLF001
        text = self.app.engine_info_label.cget("text")
        self.assertIn("Checkpoint:", text)
        path_lines = [line for line in text.splitlines() if LongPathBackend.CHECKPOINT in line]
        self.assertEqual(path_lines, [])  # the path did not fit on any single line
        for token in text.replace("\n", " ").split(" "):
            self.assertLessEqual(len(token), formatting.LABEL_MAX_RUN, text)
        # wrapped, never truncated
        self.assertIn(LongPathBackend.CHECKPOINT, text.replace("\n", ""))

    def test_the_demo_panel_still_wraps_its_warning(self) -> None:
        text = self.app.engine_info_label.cget("text")
        self.assertIn("Warning:", text)
        for token in text.replace("\n", " ").split(" "):
            self.assertLessEqual(len(token), formatting.LABEL_MAX_RUN, text)


class StubLoadableBackend:
    """Model backend double that remembers whether it currently holds weights."""

    name = "opf"

    def __init__(self) -> None:
        self.loaded = False

    def describe(self) -> dict[str, str]:
        return {"Engine": "stub", "Loaded": "yes" if self.loaded else "no"}

    def load(self) -> None:
        self.loaded = True

    def warmup(self) -> None:
        self.loaded = True

    def close(self) -> None:
        self.loaded = False


class EnginePatchMixin:
    """Swap in a stub backend and fake the `opf` environment probe."""

    def use_backend(self, backend: Any) -> None:
        original = self.app.engine.backend  # type: ignore[attr-defined]
        self.app.engine.backend = backend  # type: ignore[attr-defined]
        self.addCleanup(setattr, self.app.engine, "backend", original)  # type: ignore[attr-defined]

    def fake_status(self, *, installed: bool = True, present: bool = True) -> None:
        """Pretend `opf` (and optionally the checkpoint) is available."""
        from opf_gui import app as app_module
        from opf_gui.backends import ModelStatus

        self.addCleanup(setattr, app_module, "model_status", app_module.model_status)
        app_module.model_status = lambda _checkpoint: ModelStatus(
            installed=installed, checkpoint_present=present, detail="stubbed probe"
        )


class TestModelToggle(EnginePatchMixin, unittest.TestCase):
    """The toolbar 'Model' toggle owns load/unload; the old buttons are gone."""

    def setUp(self) -> None:
        self.app = make_app()

    def toolbar_row(self) -> dict[int, str]:
        """Caption of every toolbar switch, keyed by its grid column."""
        row: dict[int, str] = {}
        for child in self.app.engine_switch.master.winfo_children():
            info = child.grid_info_now
            if str(info.get("row")) == "0":
                row[int(info["column"])] = str(child.cget("text"))
        return row

    def menu_labels(self, name: str) -> list[str]:
        cascade = next(
            options for _kind, options in self.app.menu_bar.entries if options.get("label") == name
        )
        return [str(options.get("label")) for _kind, options in cascade["menu"].entries]

    def test_toggle_sits_between_engine_and_labels(self) -> None:
        self.assertEqual(self.app.model_switch.values, ["load", "unload"])
        row = self.toolbar_row()
        self.assertEqual([row[column] for column in sorted(row)],
                         ["Engine", "Model", "Labels", "Device", "Theme", "Results view"])
        columns = [
            int(widget.grid_info_now["column"])
            for widget in (self.app.engine_switch, self.app.model_switch, self.app.output_switch)
        ]
        self.assertEqual(columns, [1, 2, 3])

    def test_replaced_buttons_are_gone_but_the_paths_remain(self) -> None:
        self.assertEqual(self.app.model_switch.get(), "unload")  # nothing loaded at startup
        toolbar = self.app.engine_switch.master.master  # switch -> inner -> toolbar
        texts = [text for text in widget_texts(toolbar) if text]
        for gone in ("Settings", "Load model", "Unload model (free RAM)"):
            self.assertNotIn(gone, texts)
        # settings stay reachable from the menu, warm-up from the sidebar
        self.assertIn("Advanced settings...", self.menu_labels("View"))
        self.assertIn("Load model", self.menu_labels("Run"))
        self.assertIn("Unload model (free memory)", self.menu_labels("Run"))
        self.assertEqual(self.app.warmup_button.text, "Warm up model")

    def test_toggle_loads_then_unloads(self) -> None:
        app = self.app
        backend = StubLoadableBackend()
        self.use_backend(backend)
        app.settings.engine = "model"
        self.fake_status()

        app.model_switch.choose("load")
        self.assertTrue(backend.loaded)
        self.assertTrue(app.model_loaded)
        self.assertEqual(app.model_switch.get(), "load")
        self.assertIn("Loaded: yes", app.engine_info_label.cget("text"))

        app.model_switch.choose("unload")
        self.assertFalse(backend.loaded)
        self.assertFalse(app.model_loaded)
        self.assertEqual(app.model_switch.get(), "unload")

    def test_refused_load_snaps_back_and_leaves_the_engine_alone(self) -> None:
        app = self.app
        stub_gui.reset()
        # `opf` is not installed here, so the toggle must not pretend otherwise
        app.model_switch.choose("load")
        self.assertEqual(app.model_switch.get(), "unload")
        self.assertFalse(app.model_loaded)
        self.assertEqual(app.settings.engine, "demo")
        self.assertTrue(MESSAGEBOX_CALLS and MESSAGEBOX_CALLS[-1][0] == "showwarning")

    def test_declined_download_leaves_the_engine_alone(self) -> None:
        app = self.app
        self.fake_status(present=False)
        stub_gui.DIALOG_ANSWERS["askyesno"] = False
        app.model_switch.choose("load")
        self.assertEqual(app.model_switch.get(), "unload")
        self.assertEqual(app.settings.engine, "demo")
        self.assertIn("cancelled", app.status_label.cget("text"))

    def test_unload_without_a_loaded_model_does_nothing(self) -> None:
        self.app.model_switch.choose("unload")
        self.assertFalse(self.app.model_loaded)
        self.assertEqual(self.app.model_switch.get(), "unload")

    def test_clicks_while_a_model_job_runs_defer_to_the_worker(self) -> None:
        app = self.app
        app._model_pending = True  # noqa: SLF001 - pretend a load job is in flight
        app.model_switch.choose("unload")
        self.assertEqual(app.model_switch.get(), "load")  # still shows the job's target
        self.assertIn("Model job already running", app.status_label.cget("text"))
        self.assertFalse(app.model_loaded)  # nothing has actually landed yet
        app._model_pending = None  # noqa: SLF001 - job finished without loading
        app._sync_model_switch()  # noqa: SLF001
        self.assertEqual(app.model_switch.get(), "unload")

    def test_warm_up_counts_as_loaded(self) -> None:
        app = self.app
        backend = StubLoadableBackend()
        self.use_backend(backend)
        app.settings.engine = "model"
        app.warmup_model()
        self.assertTrue(backend.loaded)
        self.assertEqual(app.model_switch.get(), "load")

    def test_backend_rebuild_forgets_the_loaded_model(self) -> None:
        app = self.app
        backend = StubLoadableBackend()
        self.use_backend(backend)
        app.settings.engine = "model"
        self.fake_status()
        app.model_switch.choose("load")
        self.assertEqual(app.model_switch.get(), "load")
        app._set_engine("demo")  # noqa: SLF001 - a rebuild throws the weights away
        self.assertEqual(app.model_switch.get(), "unload")
        self.assertFalse(app.model_loaded)


class TestWarmUpButton(EnginePatchMixin, unittest.TestCase):
    """`Warm up model` doubles as the cold/warm indicator: solid while cold,
    ghosted (like the secondary controls) once the model has been warmed."""

    def setUp(self) -> None:
        self.app = make_app()

    def ghosted(self) -> bool:
        return self.app.warmup_button.options.get("fg_color") == "transparent"

    def test_a_cold_model_gets_the_active_button_face(self) -> None:
        app = self.app
        app._set_engine("model")  # noqa: SLF001 - the regex engine has no model to warm
        self.assertFalse(app.model_warm)
        face = app.warmup_button.options
        self.assertNotEqual(face.get("fg_color"), "transparent")
        self.assertEqual(face.get("fg_color"), theme.ACTIVE_BUTTON["fg_color"])
        self.assertEqual(face.get("border_width"), 0)

    def test_the_demo_engine_has_nothing_to_warm(self) -> None:
        app = self.app  # Demo engine: `opf` is not installed in this environment
        self.assertEqual(app.settings.engine, "demo")
        self.assertFalse(app.model_warm)
        self.assertTrue(self.ghosted())

    def test_warming_up_ghosts_the_button(self) -> None:
        app = self.app
        backend = StubLoadableBackend()
        self.use_backend(backend)
        app.settings.engine = "model"
        self.assertFalse(app.model_warm)
        app.warmup_model()
        self.assertTrue(app.model_warm)
        self.assertTrue(self.ghosted())

    def test_loading_without_a_pass_is_not_warm(self) -> None:
        app = self.app
        self.use_backend(StubLoadableBackend())
        app.settings.engine = "model"
        self.fake_status()
        app.model_switch.choose("load")
        self.assertTrue(app.model_loaded)
        self.assertFalse(app.model_warm)
        self.assertFalse(self.ghosted())

    def test_unload_makes_the_model_cold_again(self) -> None:
        app = self.app
        self.use_backend(StubLoadableBackend())
        app.settings.engine = "model"
        app.warmup_model()
        self.assertTrue(self.ghosted())
        app.model_switch.choose("unload")
        self.assertFalse(app.model_warm)
        self.assertFalse(self.ghosted())

    def test_a_finished_redaction_counts_as_warm(self) -> None:
        from opf_gui.engine import MSG_STATE

        app = self.app
        app._set_engine("model")  # noqa: SLF001
        app._on_engine_message(MSG_STATE, {"loaded": True, "warm": True})  # noqa: SLF001
        self.assertTrue(self.ghosted())
        app._on_engine_message(MSG_STATE, {"loaded": True, "warm": False})  # noqa: SLF001
        self.assertFalse(self.ghosted())

    def test_switching_engine_resets_the_warm_face(self) -> None:
        app = self.app
        self.use_backend(StubLoadableBackend())
        app.settings.engine = "model"
        app.warmup_model()
        self.assertTrue(self.ghosted())
        app._set_engine("demo")  # noqa: SLF001 - cold, and nothing to warm under Demo
        self.assertFalse(app.model_warm)
        self.assertTrue(self.ghosted())
        app._set_engine("model")  # noqa: SLF001 - a cold model again, so active
        self.assertFalse(self.ghosted())


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

    def test_about_names_the_version(self) -> None:
        app = make_app()
        app.show_about()  # noqa: SLF001 - Help -> About OPF GUI, and F1
        title, body = MESSAGEBOX_CALLS[-1][1][:2]
        self.assertEqual(title, APP_TITLE)
        self.assertTrue(body.startswith(f"{APP_TITLE} v{__version__}"), body)

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
