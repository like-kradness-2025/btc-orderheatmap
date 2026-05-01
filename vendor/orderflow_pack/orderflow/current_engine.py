"""Stable internal alias for the current renderer engine."""
from __future__ import annotations

import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from engine_v330 import base, run_once

__all__ = ["base", "run_once"]
