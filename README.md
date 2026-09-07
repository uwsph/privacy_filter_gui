# Open Privacy Filter GUI — Desktop Front-End for OpenAI Privacy Filter

A local, offline desktop app for the [`openai/privacy-filter`](https://github.com/openai/privacy-filter) (`opf`). Paste or drop in text, review detected PII spans, and export redacted text or schema-shaped JSON. Built with Python and [customtkinter](https://github.com/TomSchimansky/CustomTkinter)—all processing happens locally, and no data leaves your machine.

## Features

* **Redact & Review:** Process text and immediately review every tagged span (label, text, offsets, score) in a sortable table. Click a span to highlight it in the text pane.
* **Flexible Export:** Save output as redacted plain text, OPF-schema JSON, JSONL for batches, or Markdown reports.
* **Responsive UI:** Background worker threads keep the interface snappy. Switch smoothly between Output, Review, JSON, Batch, and Log views.
* **Demo Mode:** Runs a lightweight regex heuristic engine out-of-the-box if the full model isn't installed. *(Note: Demo mode is for testing the UI, not a secure privacy control).*

## Installation

Requires Python with Tkinter support (e.g., `python3-tk` on Debian/Ubuntu, or included in macOS/Windows python.org installers).

**1. Basic Install (Demo Mode Only)**

```bash
cd privacy_filter_gui
pip install -r requirements.txt 

```

**2. Full Install (Recommended)**
Installs the actual AI model dependencies and enables drag-and-drop support.

```bash
pip install -e .[model,dnd]

```

*Note: The first time you run the model, it will download the OPF checkpoint from Hugging Face to `~/.opf/privacy_filter`.*

## Usage

Launch the GUI or run environment checks directly from your terminal:

```bash
python -m opf_gui               # Launch the standard GUI
python -m opf_gui -f notes.txt  # Launch and load a specific file at startup
python -m opf_gui --demo        # Force the offline regex engine
python -m opf_gui --check       # Print an environment and dependency report

```

### Keyboard Shortcuts

| Keys | Action |
| --- | --- |
| `Ctrl+Return` / `Enter` | Run Redaction |
| `Ctrl+O` / `Ctrl+S` | Open file / Save redacted text |
| `Ctrl+Shift+C` | Copy redacted text |
| `Ctrl++` / `Ctrl+-` | Increase / Decrease font size |
| `Esc` | Cancel running job or close popups |
| `F1` | Open About / Info |

## Project Structure

* **`app.py` / `engine.py**`: Main window layout, views, and background worker threads.
* **`backends.py` / `formatting.py**`: OPF/regex backend logic and JSON/Markdown export math.
* **`models.py` / `widgets.py` / `theme.py**`: Settings schemas, custom highlighted panes, and UI color palettes.
* **`dnd.py`**: Optional `tkinterdnd2` drag-and-drop routing.

## Development & Testing

The GUI tests run headless via a custom Tkinter stub, ensuring layout and workflow regressions fail loudly even on display-less environments.

```bash
python tests/test_logic.py      # Test core engine and formatting logic
python tests/test_gui_smoke.py  # Test GUI wiring headless

```

## Troubleshooting

* **`ModuleNotFoundError: customtkinter`**: Run `pip install customtkinter`.
* **`No module named tkinter`**: Install Tk for your OS (`sudo apt install python3-tk` or reinstall Python with Tcl/Tk enabled).
* **Drag & Drop isn't working**: Ensure `tkinterdnd2` is installed. Run `python -m opf_gui --check` to verify. The app will still function using the `Open` button.
* **Model won't load / First run is slow**: The initial run downloads the checkpoint and warms up the model. Use the `Warm up model` sidebar button, and check `--check` to ensure you have sufficient RAM.

## License & Colophon

Released under the **Apache License 2.0** (see `LICENSE.txt`).
*Note: The OPF model weights are a separate Hugging Face download governed by OpenAI's terms. External dependencies maintain their own licenses.*

Built using `prompt.md` with `unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q4_K_XL` in Pi (pi.dev) on a Strix Halo (Max+ 395) system running CachyOS with 128 GB shared RAM.