#!/usr/bin/env python3
"""Worker entrypoint for the packaged TOMAS pipeline."""

from __future__ import annotations

from tomas_pipeline import main


if __name__ == "__main__":
    raise SystemExit(main())
