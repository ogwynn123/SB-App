"""Set Tcl/Tk lookup paths for frozen WinCross GUI builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _set_tk_paths() -> None:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    tcl_path = base / "tcl" / "tcl8.6"
    tk_path = base / "tcl" / "tk8.6"

    if tcl_path.exists():
        os.environ.setdefault("TCL_LIBRARY", str(tcl_path))
    if tk_path.exists():
        os.environ.setdefault("TK_LIBRARY", str(tk_path))


_set_tk_paths()
