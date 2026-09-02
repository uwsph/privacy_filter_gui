"""Command-line entry point: ``python -m opf_gui`` or ``opf-gui``."""

from __future__ import annotations

import argparse
import sys

from . import __version__, formatting
from .backends import model_status
from .models import DEVICES, ENGINES, Settings, config_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="opf-gui",
        description=(
            "Desktop GUI for OpenAI Privacy Filter (https://github.com/openai/privacy-filter): "
            "detect and redact PII locally, review spans, and batch-sanitise files."
        ),
    )
    parser.add_argument("--demo", action="store_true", help="start with the offline regex demo engine")
    parser.add_argument("--device", choices=DEVICES, help="inference device (default: auto)")
    parser.add_argument("--checkpoint", help="checkpoint directory (default: OPF_CHECKPOINT or ~/.opf/privacy_filter)")
    parser.add_argument("--output-mode", choices=("typed", "redacted"), help="labelled or collapsed placeholders")
    parser.add_argument("--appearance", choices=("dark", "light", "system"), help="UI theme")
    parser.add_argument("-f", "--file", dest="file", help="load a text file into the editor at startup")
    parser.add_argument("--no-config", action="store_true", help="ignore and do not write the saved config file")
    parser.add_argument("--check", action="store_true", help="print an environment report and exit (no GUI)")
    parser.add_argument("--sample", action="store_true", help="print the built-in sample text and exit")
    parser.add_argument("--version", action="version", version=f"opf-gui {__version__}")
    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    settings = Settings() if args.no_config else Settings.load()
    if args.demo:
        settings.engine = "demo"
    if args.device:
        settings.device = args.device
    if args.checkpoint:
        settings.checkpoint = args.checkpoint
    if args.output_mode:
        settings.output_mode = args.output_mode
    if args.appearance:
        settings.appearance = args.appearance
    return settings


def environment_report(settings: Settings) -> str:
    """Human readable startup diagnostics."""
    status = model_status(settings.checkpoint)
    rows = [
        ("version", __version__),
        ("python", f"{sys.version.split()[0]} ({sys.executable})"),
        ("config file", str(config_path())),
        ("engine", settings.engine),
        ("device", settings.device),
        ("output mode", settings.output_mode),
        ("decode mode", settings.decode_mode),
        ("opf package", "installed" if status.installed else "NOT installed"),
        (
            "checkpoint",
            f"{'present' if status.checkpoint_present else 'not found'} ({status.detail})",
        ),
    ]
    for module, purpose in (
        ("tkinter", "GUI toolkit"),
        ("customtkinter", "themed widgets"),
        ("tkinterdnd2", "drag & drop (optional)"),
        ("torch", "model inference"),
        ("huggingface_hub", "checkpoint download"),
    ):
        rows.append((module, f"{_probe(module)} - {purpose}"))
    width = max(len(name) for name, _value in rows)
    lines = ["OpenAI Privacy Filter GUI - environment check"]
    lines += [f"  {name:<{width}} : {value}" for name, value in rows]
    lines.append("")
    if not status.installed:
        lines.append(
            "Next step: git clone https://github.com/openai/privacy-filter && "
            "cd privacy-filter && pip install -e ."
        )
    elif not status.checkpoint_present:
        lines.append("Next step: the first 'Load model' downloads the checkpoint from HuggingFace.")
    else:
        lines.append("Ready: run 'python -m opf_gui'.")
    if settings.engine == "demo":
        lines.append("Demo engine is regex-based - for interface preview only, not a privacy control.")
    return "\n".join(lines)


def _probe(module: str) -> str:
    """Report whether an optional dependency is importable, with its version."""
    import importlib.util

    try:
        if importlib.util.find_spec(module) is None:
            return "missing"
    except (ImportError, ValueError):
        return "missing"
    try:
        return f"available {version_of(module)}"
    except Exception:  # noqa: BLE001 - metadata can be missing for stdlib/venv builds
        return "available"


def version_of(module: str) -> str:
    from importlib.metadata import version

    return version(module)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = _settings_from_args(args)

    if args.sample:
        sys.stdout.write(formatting.sample_text())
        return 0
    if args.check:
        print(environment_report(settings))
        return 0

    start_text = None
    if args.file:
        try:
            start_text = formatting.read_text_file(args.file)
            settings.add_recent(args.file)
        except OSError as exc:
            print(f"Could not read {args.file}: {exc}", file=sys.stderr)
            return 2

    try:
        from .app import PrivacyFilterApp
    except ImportError as exc:  # pragma: no cover - depends on the platform Python build
        print(
            f"GUI dependencies are unavailable: {exc}\n\n"
            "This Python build needs tkinter (and customtkinter):\n"
            "  Debian/Ubuntu: sudo apt install python3-tk\n"
            "  Fedora:        sudo dnf install python3-tkinter\n"
            "  macOS/Windows: reinstall Python from python.org with 'tcl/tk' selected\n"
            "  then:          pip install customtkinter\n\n"
            "Run 'python -m opf_gui --check' for a full environment report.",
            file=sys.stderr,
        )
        return 1

    app = PrivacyFilterApp(
        settings, start_text=start_text, save_config=not args.no_config
    )
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
