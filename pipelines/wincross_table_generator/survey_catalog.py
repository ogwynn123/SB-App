#!/usr/bin/env python3
"""Compatibility shim that forwards to pipelines/catalogger/survey_catalog.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_CATALOG_IMPL = Path(__file__).resolve().parent.parent / "catalogger" / "survey_catalog.py"
if not _CATALOG_IMPL.exists():
    raise ImportError(f"Catalog module not found at {_CATALOG_IMPL}")

_spec = importlib.util.spec_from_file_location("_catalogger_impl", _CATALOG_IMPL)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Failed to load catalog module spec from {_CATALOG_IMPL}")

_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name in dir(_module):
    if _name.startswith("__") and _name not in {"__doc__", "__all__"}:
        continue
    globals()[_name] = getattr(_module, _name)
