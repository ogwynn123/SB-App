#!/usr/bin/env python3
"""Normington Petts look for the platform's windows: colours, ttk theme and a logo header.

Colours come from the logo: Normington blue (#00539B, the lettering), a deeper
blue (#005287, the crosshair lines) and slate grey (#6A737B, the small square).

    import brand
    brand.apply_theme(root)
    brand.add_header(root, "Sheet Merge", "Merge this wave onto the trend file")

Accent buttons (the window's main action) use style "Accent.TButton".
"""

from __future__ import annotations

import sys
from pathlib import Path

BLUE = "#00539B"
DEEP_BLUE = "#005287"
GREY = "#6A737B"
INK = "#1F2A37"
BACKGROUND = "#F4F6F9"
TINT = "#E6EEF7"  # light blue for hover and alternate rows
WHITE = "#FFFFFF"
HEADER_LOGO = "npa_logo_header.png"
FONT = "Segoe UI"


def _asset(name: str) -> Path | None:
    """A file shipped beside this module (or inside a packaged EXE)."""
    for folder in (getattr(sys, "_MEIPASS", None), Path(__file__).resolve().parent):
        if folder:
            path = Path(folder) / name
            if path.exists():
                return path
    return None


def apply_theme(root) -> None:
    """Brand colours on ttk widgets ("clam" lets buttons and headings take colours)."""
    from tkinter import ttk

    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=BACKGROUND)
    style.configure(".", background=BACKGROUND, foreground=INK, font=(FONT, 9))
    style.configure("TFrame", background=BACKGROUND)
    style.configure("TLabel", background=BACKGROUND, foreground=INK)
    style.configure("TCheckbutton", background=BACKGROUND)
    style.configure("TRadiobutton", background=BACKGROUND)
    style.configure("TLabelframe", background=BACKGROUND, bordercolor="#C9D3DE")
    style.configure("TLabelframe.Label", background=BACKGROUND, foreground=BLUE, font=(FONT, 9, "bold"))
    style.configure("TNotebook", background=BACKGROUND, bordercolor="#C9D3DE")
    style.configure("TNotebook.Tab", padding=(10, 4), foreground=INK)
    style.map("TNotebook.Tab", background=[("selected", WHITE)], foreground=[("selected", BLUE)])
    style.configure("TButton", padding=(10, 4), foreground=INK, background="#E9EDF2", bordercolor="#B8C3CF")
    style.map("TButton", background=[("active", TINT), ("pressed", "#D5E2F0")])
    style.configure("Accent.TButton", foreground=WHITE, background=BLUE, bordercolor=DEEP_BLUE)
    style.map("Accent.TButton", background=[("disabled", "#8FA9C6"), ("active", DEEP_BLUE), ("pressed", DEEP_BLUE)],
              foreground=[("disabled", "#EEF2F6")])
    style.configure("Treeview", background=WHITE, fieldbackground=WHITE, foreground=INK, rowheight=20,
                    bordercolor="#C9D3DE")
    style.map("Treeview", background=[("selected", BLUE)], foreground=[("selected", WHITE)])
    style.configure("Treeview.Heading", background=DEEP_BLUE, foreground=WHITE, font=(FONT, 9, "bold"),
                    bordercolor=DEEP_BLUE, relief="flat")
    style.map("Treeview.Heading", background=[("active", BLUE)])
    style.configure("TEntry", fieldbackground=WHITE, bordercolor="#B8C3CF")
    style.configure("TCombobox", fieldbackground=WHITE, bordercolor="#B8C3CF")
    style.map("TCombobox", fieldbackground=[("readonly", WHITE)])
    style.configure("TSpinbox", fieldbackground=WHITE)
    style.configure("Brand.TFrame", background=WHITE)
    style.configure("BrandTitle.TLabel", background=WHITE, foreground=BLUE, font=(FONT, 14, "bold"))
    style.configure("BrandSubtitle.TLabel", background=WHITE, foreground=GREY, font=(FONT, 9))


def add_header(parent, title: str, subtitle: str = "") -> None:
    """Pack a white strip at the top: logo, title, subtitle, and a blue rule under it."""
    import tkinter as tk
    from tkinter import ttk

    strip = ttk.Frame(parent, style="Brand.TFrame", padding=(12, 6))
    strip.pack(side=tk.TOP, fill=tk.X)
    logo_path = _asset(HEADER_LOGO)
    if logo_path is not None:
        try:
            image = tk.PhotoImage(file=str(logo_path))
            label = tk.Label(strip, image=image, background=WHITE, borderwidth=0)
            label.image = image  # keep a reference so Tk does not drop it
            label.pack(side=tk.LEFT, padx=(0, 14))
        except tk.TclError:
            pass
    words = ttk.Frame(strip, style="Brand.TFrame")
    words.pack(side=tk.LEFT, fill=tk.X, expand=True)
    ttk.Label(words, text=title, style="BrandTitle.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(words, text=subtitle, style="BrandSubtitle.TLabel").pack(anchor="w")
    tk.Frame(parent, height=2, background=DEEP_BLUE).pack(side=tk.TOP, fill=tk.X)
