from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os


def default_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / "NormingtonPetts" / "sample_quota_checker"
    else:
        base = Path.home() / ".sample_quota_checker"
    return base / "column_mappings.json"


def normalized_path(path: Path | str) -> str:
    return str(Path(path).expanduser().resolve(strict=False)).casefold()


def mapping_key(quota_path: Path | str, sample_path: Path | str) -> str:
    payload = f"{normalized_path(quota_path)}\n{normalized_path(sample_path)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sample_key(sample_path: Path | str) -> str:
    return hashlib.sha256(normalized_path(sample_path).encode("utf-8")).hexdigest()


def quota_key(quota_path: Path | str) -> str:
    return hashlib.sha256(normalized_path(quota_path).encode("utf-8")).hexdigest()


def load_store(store_path: Path | str | None = None) -> dict:
    path = Path(store_path) if store_path else default_settings_path()
    if not path.exists():
        return {"version": 1, "pairs": {}, "sample_quota_pairs": {}, "quota_overrides": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "pairs": {}, "sample_quota_pairs": {}, "quota_overrides": {}}
    if not isinstance(data, dict):
        return {"version": 1, "pairs": {}, "sample_quota_pairs": {}, "quota_overrides": {}}
    pairs = data.get("pairs")
    if not isinstance(pairs, dict):
        data["pairs"] = {}
    sample_quota_pairs = data.get("sample_quota_pairs")
    if not isinstance(sample_quota_pairs, dict):
        data["sample_quota_pairs"] = {}
    quota_overrides = data.get("quota_overrides")
    if not isinstance(quota_overrides, dict):
        data["quota_overrides"] = {}
    data.setdefault("version", 1)
    return data


def load_saved_mapping(
    quota_path: Path | str,
    sample_path: Path | str,
    store_path: Path | str | None = None,
) -> dict[str, str]:
    store = load_store(store_path)
    entry = store.get("pairs", {}).get(mapping_key(quota_path, sample_path), {})
    mapping = entry.get("mapping", {}) if isinstance(entry, dict) else {}
    if not isinstance(mapping, dict):
        return {}
    return {str(key): str(value) for key, value in mapping.items()}


def save_mapping(
    quota_path: Path | str,
    sample_path: Path | str,
    mapping: dict[str, str],
    store_path: Path | str | None = None,
) -> Path:
    path = Path(store_path) if store_path else default_settings_path()
    store = load_store(path)
    store.setdefault("pairs", {})
    store["pairs"][mapping_key(quota_path, sample_path)] = {
        "quota_path": str(Path(quota_path).expanduser().resolve(strict=False)),
        "sample_path": str(Path(sample_path).expanduser().resolve(strict=False)),
        "mapping": {str(key): str(value) for key, value in mapping.items()},
    }
    _set_sample_quota_pair(store, quota_path, sample_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")
    return path


def _set_sample_quota_pair(store: dict, quota_path: Path | str, sample_path: Path | str) -> None:
    store.setdefault("sample_quota_pairs", {})
    store["sample_quota_pairs"][sample_key(sample_path)] = {
        "quota_path": str(Path(quota_path).expanduser().resolve(strict=False)),
        "sample_path": str(Path(sample_path).expanduser().resolve(strict=False)),
    }


def save_sample_quota_pair(
    quota_path: Path | str,
    sample_path: Path | str,
    store_path: Path | str | None = None,
) -> Path:
    path = Path(store_path) if store_path else default_settings_path()
    store = load_store(path)
    _set_sample_quota_pair(store, quota_path, sample_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")
    return path


def load_saved_quota_for_sample(
    sample_path: Path | str,
    store_path: Path | str | None = None,
) -> str:
    store = load_store(store_path)
    entry = store.get("sample_quota_pairs", {}).get(sample_key(sample_path), {})
    if not isinstance(entry, dict):
        return ""
    quota_path = entry.get("quota_path", "")
    return str(quota_path) if quota_path else ""


def load_quota_override(
    quota_path: Path | str,
    store_path: Path | str | None = None,
) -> dict:
    store = load_store(store_path)
    entry = store.get("quota_overrides", {}).get(quota_key(quota_path), {})
    if not isinstance(entry, dict):
        return {}
    definition = entry.get("definition", {})
    return definition if isinstance(definition, dict) else {}


def save_quota_override(
    quota_path: Path | str,
    definition: dict,
    store_path: Path | str | None = None,
) -> Path:
    path = Path(store_path) if store_path else default_settings_path()
    store = load_store(path)
    store.setdefault("quota_overrides", {})
    store["quota_overrides"][quota_key(quota_path)] = {
        "quota_path": str(Path(quota_path).expanduser().resolve(strict=False)),
        "definition": definition,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")
    return path


def clear_quota_override(
    quota_path: Path | str,
    store_path: Path | str | None = None,
) -> bool:
    path = Path(store_path) if store_path else default_settings_path()
    store = load_store(path)
    removed = store.get("quota_overrides", {}).pop(quota_key(quota_path), None) is not None
    if removed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, indent=2), encoding="utf-8")
    return removed
