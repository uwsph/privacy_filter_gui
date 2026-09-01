# OPF GUI — desktop front-end for OpenAI Privacy Filter

A local, offline desktop app around [`openai/privacy-filter`](https://github.com/openai/privacy-filter)
(`opf`): paste or drop in text, get PII-tagged output, review every detected span,
and export redacted text or schema-shaped JSON. Built with Python +
[customtkinter](https://github.com/TomSchimansky/CustomTkinter); nothing leaves your machine.

```
opf_gui/
  app.py          main window, tabs, toolbar, dialogs
  backends.py     real `opf` backend + offline regex demo backend
  dnd.py          optional drag & drop (tkinterdnd2), degrades silently
  engine.py       worker thread, cancel, progress messages
  formatting.py   span maths, JSON/JSONL/Markdown exports
  models.py       settings, spans, label metadata
  theme.py        PII colour palettes, light/dark colours, ghost buttons
  widgets.py      highlighted text panes, span table, legend, log console
```

## Install

Requires a Python build that includes Tk (`python3-tk` on Debian/Ubuntu,
included in the python.org macOS/Windows installers).

```bash
cd tools/privacy_filter_gui
pip install -r requirements.txt          # customtkinter only -> Demo mode works

# optional: the real model (pulls torch, tiktoken, huggingface_hub, ...)
pip install "opf @ git+https://github.com/openai/privacy-filter"

# optional: drag & drop of text files
pip install tkinterdnd2
```

Or with the project metadata: `pip install -e .[model,dnd]`.

The first Model run downloads the OPF checkpoint from Hugging Face to
`~/.opf/privacy_filter` (override with `OPF_CHECKPOINT=/path/to/checkpoint`).

## Run

```bash
python run_gui.py                 # or: python -m opf_gui
python -m opf_gui --demo          # force the offline regex engine
python -m opf_gui --check         # environment report, no GUI
python -m opf_gui -f notes.txt    # load a file at startup
python -m opf_gui --help
```

## Using it

1. **Get text in** — the input buttons run in workflow order:
   `Sample` · `Paste` · `Open` · `Redact` · `Clear` · `Cancel`.
   `Open` accepts multiple files; folders can also be **dropped onto the editor**
   (needs `tkinterdnd2`; the app logs a note and carries on without it).
2. **Redact** — `Redact` (or `Ctrl+Return`). The model runs in a worker thread,
   so the window stays responsive; `Cancel` (`Esc`) abandons a long job.
3. **Review** — the `Review` tab lists every span (label, text, offsets, score,
   action). Click a row to jump to it in both panes; click a highlighted span in
   the input pane to select it in the table.
4. **Export** — `Copy`/`Save` for redacted text, plus JSON (OPF schema), JSONL
   for batches, and a Markdown report on the `Batch` tab.

Tabs: **Output** · **Review** · **JSON** · **Batch** · **Log**. The Log tab is the running
activity feed (engine loads, redaction timings, file and export actions); warnings and
errors are colour-coded, `Copy log` puts the whole feed on the clipboard for support tickets,
and it trims itself to the last ~1000 lines.
Toolbar: engine (`model`/`demo`), labels (`typed`/`redacted`), decode
(`viterbi`/`argmax`), device (`auto`/`cpu`/`cuda`), theme (`dark`/`light`),
`Settings…`. The sidebar shows engine status, span counts and the colour legend.

Status text (the `engine: …` badge) is repainted whenever the theme changes: dark mode keeps
the bright orange/green, light mode swaps to deep shades - every combination is
contrast-tested to at least 4.5:1 (WCAG AA) by the test suite.

### Shortcuts

| Keys | Action |
| --- | --- |
| `Ctrl+Return` / numpad `Enter` | Redact |
| `Ctrl+O` / `Ctrl+S` | Open file / save redacted text |
| `Ctrl+Shift+C` | Copy redacted text |
| `Ctrl++` / `Ctrl+-` | Font size |
| `Esc` | Cancel running job |
| `F1` | About |
| `Ctrl+Q` | Quit |

### Demo mode

Without `opf` installed the app uses a regex heuristic engine so the UI is still
usable for triage and demos. **It is not a privacy control**: the sidebar says
so, and JSON exports carry a `warning` field naming the demo engine (the batch
Markdown report names the engine too). Plain-text saves carry no metadata, so
check the badge before you share redacted text. Use the `model` engine for
anything real.

## Tests

```bash
python tests/test_logic.py      # engine/formatting/settings logic (no GUI needed)
python tests/test_gui_smoke.py  # GUI wiring, via a tkinter/customtkinter stub
```

The GUI tests run headless: `tests/stub_gui.py` supplies just enough of Tk and
customtkinter to build the window and drive the workflows, so layout regressions
(button order, pane alignment, drag & drop, theme switching) fail loudly even on
a machine with no display.

## License

Released under the **Apache License 2.0** - see [LICENSE.txt](LICENSE.txt). Use, modify and
redistribute freely (including commercially) as long as you keep the copyright and license
notices and mark changed files.

What the license does **not** cover:

- The OPF model weights: a separate Hugging Face download under OpenAI's own terms -
  read them before deploying (source: opf_gui/app.py, `MODEL_URL`).
- Dependencies keep their own licenses: `customtkinter` (MIT), `tkinterdnd2` (BSD-style).

Nothing here is legal advice - check with whoever owns privacy sign-off before redacted
output leaves the building.

## Troubleshooting

- **`ModuleNotFoundError: customtkinter`** → `pip install customtkinter`.
- **`No module named tkinter`** → install Tk for your interpreter (`sudo apt install python3-tk`,
  or reinstall python.org Python with Tcl/Tk ticked).
- **`Unable to load tkdnd library` / drag-drop does nothing** → `pip install tkinterdnd2`;
  the app keeps working with `Open` when it is missing. Toggle it in `Settings…`.
- **Model will not load** → `python -m opf_gui --check` reports whether `opf`,
  the checkpoint and enough RAM look available; `Settings…` lets you point at a
  local checkpoint directory.
- **First run is slow** → the checkpoint download plus model warm-up; use
  `Warm up model` in the sidebar, and `Unload model (free RAM)` when done.
