"""Model service: keeps BGE-M3 (and the BGE reranker) loaded and serves encode/rerank over HTTP on the internal
Docker network, so the API never loads weights per request. Run:
    uvicorn backend.app.layer5_retrieval.model_service:app --port 8001
RERANKER=none skips the reranker. Weights come from HF_HOME (a persistent volume in docker-compose).
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI
from pydantic import BaseModel, Field

from backend.app.layer5_retrieval.embeddings import BGEM3Encoder, BGEReranker, EmbeddingsUnavailable, _b64

STATE: dict = {}
LOCK = threading.Lock()  # one forward pass at a time; torch already uses all configured threads


@asynccontextmanager
async def lifespan(_app):
    enc = BGEM3Encoder()
    STATE["encoder"] = enc
    STATE["encoder_info"] = {"name": enc.name, "revision": enc.revision, "load_seconds": enc.load_seconds}
    try:
        t = time.perf_counter()
        rr = BGEReranker()
        STATE["reranker"] = rr
        STATE["reranker_info"] = {"name": rr.name, "revision": rr.revision,
                                  "load_seconds": round(time.perf_counter() - t, 2)}
    except EmbeddingsUnavailable as exc:
        STATE["reranker_info"] = None
        STATE["reranker_error"] = str(exc)
    enc.encode(["warm-up"])  # first forward pass is slow; do it before reporting healthy
    yield


app = FastAPI(title="BGE-M3 model service (internal)", lifespan=lifespan)


class EncodeIn(BaseModel):
    texts: list[str] = Field(max_length=256)
    batch_size: int = Field(default=16, ge=1, le=64)


class RerankIn(BaseModel):
    query: str
    passages: list[str] = Field(max_length=100)


@app.get("/health")
def health():
    return {"status": "ok", "encoder": STATE.get("encoder_info"), "reranker": STATE.get("reranker_info"),
            "reranker_error": STATE.get("reranker_error"), "threads": os.environ.get("EMBED_THREADS")}


@app.post("/encode")
def encode(body: EncodeIn):
    with LOCK:
        out = STATE["encoder"].encode(body.texts, body.batch_size)
    return {"items": [{"dense": _b64(e.dense, np.float32), "sparse": e.sparse,
                       "colbert": _b64(e.colbert, np.float16), "tokens": int(len(e.colbert))} for e in out]}


@app.post("/rerank")
def rerank(body: RerankIn):
    if "reranker" not in STATE:
        from fastapi import HTTPException
        raise HTTPException(503, STATE.get("reranker_error", "reranker not loaded"))
    with LOCK:
        return {"scores": STATE["reranker"].score(body.query, body.passages)}
