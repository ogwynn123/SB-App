#!/usr/bin/env python3
"""Local sentence embeddings for open-end responses (nothing leaves this PC).

Uses a small open model through fastembed (ONNX runtime). The model is
downloaded once into SurveyPlatform/.models (git-ignored). The same models run
in a browser through transformers.js, so the drafting logic can move there.

Vectors are cached per text in corpus/oe/embeddings (git-ignored, client data).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

PLATFORM = Path(__file__).resolve().parents[2]
MODEL_DIR = PLATFORM / ".models"
CACHE_DIR = PLATFORM / "corpus" / "oe" / "embeddings"
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
_models: dict[str, object] = {}
_stores: dict[str, dict[str, np.ndarray]] = {}


def _model(name: str):
    if name not in _models:
        from fastembed import TextEmbedding

        _models[name] = TextEmbedding(model_name=name, cache_dir=str(MODEL_DIR))
    return _models[name]


def _store_path(model: str) -> Path:
    return CACHE_DIR / f"{model.replace('/', '_')}.npz"


def _store(model: str) -> dict[str, np.ndarray]:
    if model not in _stores:
        path = _store_path(model)
        store: dict[str, np.ndarray] = {}
        if path.exists():
            data = np.load(path)
            store = dict(zip(data["keys"].tolist(), data["vectors"]))
        _stores[model] = store
    return _stores[model]


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _normalise(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True).clip(min=1e-9)


def embed(texts: list[str], model: str = DEFAULT_MODEL, *, cache: bool = False) -> np.ndarray:
    """Unit-length vectors, one row per text; optionally cached on disk per text."""
    clean = [t if t.strip() else "(blank)" for t in texts]
    if not cache:
        return _normalise(np.array(list(_model(model).embed(clean)), dtype=np.float32))
    store = _store(model)
    keys = [_key(t) for t in clean]
    missing = sorted({k: t for k, t in zip(keys, clean) if k not in store}.items())
    if missing:
        vectors = _normalise(np.array(list(_model(model).embed([t for _k, t in missing])), dtype=np.float32))
        store.update(zip((k for k, _t in missing), vectors))
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        np.savez(_store_path(model), keys=np.array(list(store)), vectors=np.stack(list(store.values())))
    return np.stack([store[k] for k in keys]) if keys else np.zeros((0, 384), dtype=np.float32)
