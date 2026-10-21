#!/usr/bin/env python3
"""Optional platform features, all off unless turned on.

Turn a feature on in the machine-local ``survey_tool_config.json``:

    {"features": {"tomas": true}}

or for one session with an environment variable (``SURVEYPLATFORM_TOMAS=1``).
Turning TOMAS on shows it in the Survey Launcher and dashboard, adds it to the
packaged-app launch check, and includes it in the health check.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "survey_tool_config.json"
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def feature_enabled(name: str, config_path: Path = CONFIG_PATH) -> bool:
    env = os.environ.get(f"SURVEYPLATFORM_{name.upper()}", "").strip().casefold()
    if env in TRUE_VALUES:
        return True
    if env in FALSE_VALUES:
        return False
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    features = config.get("features") if isinstance(config, dict) else None
    return isinstance(features, dict) and features.get(name) is True


def tomas_enabled(config_path: Path = CONFIG_PATH) -> bool:
    return feature_enabled("tomas", config_path)
