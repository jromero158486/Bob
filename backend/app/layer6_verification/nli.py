"""Multilingual natural-language inference judge for claim verification (Phase 3).

Default model: MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 (MIT; XNLI + multilingual NLI incl. German).
Runs locally (transformers, CPU) or through the model service (`POST /nli`) when EMBEDDING_SERVICE_URL is set, so the
API never reloads weights per request. Output: P(entailment), P(neutral), P(contradiction) per (premise, hypothesis).
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from functools import lru_cache

NLI_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"


class NLIUnavailable(RuntimeError):
    pass


def configured_nli() -> str:
    return os.environ.get("NLI_MODEL", NLI_MODEL)


class LocalNLI:
    def __init__(self, model: str | None = None):
        try:
            import torch
            from huggingface_hub import model_info  # noqa: F401
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:  # optional [retrieval] extra
            raise NLIUnavailable(f"transformers/torch not installed: {exc}") from exc
        self.name = model or configured_nli()
        t = time.perf_counter()
        try:
            self._tok = AutoTokenizer.from_pretrained(self.name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.name).eval()
        except OSError as exc:
            raise NLIUnavailable(str(exc)) from exc
        self.load_seconds = round(time.perf_counter() - t, 2)
        self.revision = str(getattr(self._model.config, "_commit_hash", "") or "unknown")[:12]
        labels = {v.lower(): k for k, v in self._model.config.id2label.items()}
        self._idx = [labels["entailment"], labels["neutral"], labels["contradiction"]]
        self._torch = torch
        self._lock = threading.Lock()

    def score(self, pairs: list[tuple[str, str]], batch_size: int = 16) -> list[tuple[float, float, float]]:
        out = []
        for i in range(0, len(pairs), batch_size):
            chunk = pairs[i:i + batch_size]
            x = self._tok([p for p, _ in chunk], [h for _, h in chunk], return_tensors="pt", padding=True,
                          truncation=True, max_length=512)
            with self._lock, self._torch.no_grad():
                pr = self._torch.softmax(self._model(**x).logits, -1).tolist()
            out += [tuple(round(r[j], 4) for j in self._idx) for r in pr]
        return out


class RemoteNLI:
    def __init__(self, url: str):
        self.url = url.rstrip("/")
        self.timeout = float(os.environ.get("EMBEDDING_TIMEOUT", "60"))
        info = self._call("GET", "/health").get("nli")
        if not info:
            raise NLIUnavailable(f"model service at {self.url} has no NLI model loaded")
        self.name, self.revision = info["name"], info["revision"]

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(self.url + path, method=method, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise NLIUnavailable(f"model service unavailable: {exc}") from exc

    def score(self, pairs: list[tuple[str, str]], batch_size: int = 16) -> list[tuple[float, float, float]]:
        if not pairs:
            return []
        res = self._call("POST", "/nli", {"pairs": [list(p) for p in pairs], "batch_size": batch_size})
        return [tuple(x) for x in res["scores"]]


@lru_cache(maxsize=1)
def _cached():
    if os.environ.get("NLI", "on").lower() in ("none", "off", "0"):
        raise NLIUnavailable("NLI disabled by configuration")
    url = os.environ.get("EMBEDDING_SERVICE_URL")
    return RemoteNLI(url) if url else LocalNLI()


def shared_nli():
    """Process-wide NLI judge; failures are not cached (lru_cache does not store exceptions)."""
    return _cached()
