#!/usr/bin/env python3
"""Root launcher for the Survey Platform dashboard."""

from __future__ import annotations

import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
GUI_DIR = BASE_DIR / "pipelines" / "catalogger"
if str(GUI_DIR) not in sys.path:
    sys.path.insert(0, str(GUI_DIR))

import repository_dashboard_gui as dashboard_gui  # type: ignore  # noqa: E402


if __name__ == "__main__":
    dashboard_gui.main()
