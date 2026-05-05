"""Stable internal alias for the current renderer engine."""
from __future__ import annotations

import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from engine import base, main, run_once

__all__ = ["base", "main", "run_once"]


if __name__ == "__main__":
    raise SystemExit(main())
