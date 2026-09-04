"""Desktop GUI for OpenAI Privacy Filter (openai/privacy-filter).

Import of this package must stay headless-safe: tkinter and customtkinter are
only imported by :mod:`opf_gui.app` and :mod:`opf_gui.widgets`.
"""

from .models import (  # noqa: F401
    DECODE_MODES,
    DEVICES,
    ENGINES,
    OUTPUT_MODES,
    PII_LABELS,
    SCHEMA_VERSION,
    Outcome,
    Settings,
    Span,
    config_path,
    display_name,
    placeholder_for,
    redact_manually,
    summarise_outcomes,
)
from .backends import (  # noqa: F401
    BackendError,
    DemoBackend,
    ModelBackend,
    ModelStatus,
    create_backend,
    model_status,
)
from .engine import EngineController  # noqa: F401

__version__ = "1.1.0"
__all__ = ["__version__"]
