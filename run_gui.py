#!/usr/bin/env python3
"""Double-clickable launcher for the Privacy Filter GUI.

Equivalent to ``python -m opf_gui`` and useful on Windows, where a plain
``.py`` file opens an editor rather than running. Any arguments are forwarded,
so ``python run_gui.py --demo`` works.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from opf_gui.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
