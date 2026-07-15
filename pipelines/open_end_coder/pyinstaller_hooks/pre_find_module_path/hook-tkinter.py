"""Keep tkinter discoverable during PyInstaller analysis.

The upstream pre-find hook currently marks tkinter as unavailable for this
Python 3.14 install even though importing tkinter works at runtime. Leaving
this hook as a no-op allows normal module discovery while the spec file
manually bundles Tcl/Tk binaries and data.
"""


def pre_find_module_path(hook_api):
    return
