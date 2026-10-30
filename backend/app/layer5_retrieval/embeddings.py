"""BGE-M3 passage encoding and BGE cross-encoder reranking via the official FlagEmbedding package.

Paper: Chen et al., 2024, "BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings
Through Self-Knowledge Distillation" (arXiv:2402.03216). One forward pass yields a normalized dense vector, sparse
lexical token weights and per-token ColBERT vectors; scores use the model's own scoring functions.
Optional: requires `pip install -e '.[retrieval]'` and locally cached weights. EMBEDDINGS=none disables it.
"""
from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

EMBED_MODEL = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"


class EmbeddingsUnavailable(RuntimeError):
    pass


@dataclass
class Encoded:
    dense: np.ndarray
    sparse: dict[str, float]
    colbert: np.ndarray


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _revision(repo: str) -> str:
    try:
        from huggingface_hub import snapshot_download
        return os.path.basename(snapshot_download(repo, local_files_only=True))[:12]
    except Exception:
        return "unknown"


def _threads() -> None:
    import torch
    torch.set_num_threads(int(os.environ.get("EMBED_THREADS", os.cpu_count() or 1)))


class BGEM3Encoder:
    def __init__(self, model: str | None = None, max_length: int = 512):
        if os.environ.get("EMBEDDINGS", "bge-m3").lower() in ("none", "off", "0"):
            raise EmbeddingsUnavailable("EMBEDDINGS disabled by configuration")
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise EmbeddingsUnavailable(f"FlagEmbedding not installed: {exc}") from exc
        self.name = model or os.environ.get("EMBEDDING_MODEL", EMBED_MODEL)
        self.revision = _revision(self.name)
        self.max_length = max_length
        _threads()
        t = time.perf_counter()
        self.model = BGEM3FlagModel(self.name, use_fp16=False, devices="cpu")
        self.load_seconds = round(time.perf_counter() - t, 2)

    def encode(self, texts: list[str], batch_size: int = 16) -> list[Encoded]:
        if not texts:
            return []
        o = self.model.encode(texts, batch_size=batch_size, max_length=self.max_length,
                              return_dense=True, return_sparse=True, return_colbert_vecs=True)
        return [Encoded(np.asarray(o["dense_vecs"][i], dtype=np.float32),
                        {str(k): float(v) for k, v in o["lexical_weights"][i].items()},
                        np.asarray(o["colbert_vecs"][i], dtype=np.float32)) for i in range(len(texts))]

    @staticmethod
    def sparse_score(q: dict[str, float], d: dict[str, float]) -> float:
        return float(sum(w * d[t] for t, w in q.items() if t in d))

    @staticmethod
    def colbert_score(q: np.ndarray, d: np.ndarray) -> float:
        # Late interaction (MaxSim averaged over query tokens), as in FlagEmbedding's colbert_score.
        return float((q @ d.T).max(axis=1).mean())


class BGEReranker:
    def __init__(self, model: str | None = None):
        if os.environ.get("RERANKER", "bge-reranker-v2-m3").lower() in ("none", "off", "0"):
            raise EmbeddingsUnavailable("RERANKER disabled by configuration")
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise EmbeddingsUnavailable(f"FlagEmbedding not installed: {exc}") from exc
        self.name = model or os.environ.get("RERANKER_MODEL", RERANK_MODEL)
        self.revision = _revision(self.name)
        _threads()
        self.model = FlagReranker(self.name, use_fp16=False, devices="cpu")

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        s = self.model.compute_score([[query, p] for p in passages], normalize=True, max_length=512)
        return [float(x) for x in (s if isinstance(s, list) else [s])]


@lru_cache(maxsize=1)
def shared_encoder() -> BGEM3Encoder:
    return BGEM3Encoder()


@lru_cache(maxsize=1)
def shared_reranker() -> BGEReranker:
    return BGEReranker()


def colbert_to_bytes(v: np.ndarray) -> bytes:
    return v.astype(np.float16).tobytes()


def colbert_from_bytes(b: bytes, tokens: int) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float16).astype(np.float32).reshape(tokens, -1)
