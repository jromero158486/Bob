"""FastAPI app. Run: uvicorn backend.app.api.main:app --port 8000"""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.schemas import (API_VERSION, DocumentOut, PassageOut, PatientSummary, ReviewUpdate, TaskRequest,
                                     TaskResponse)
from backend.app.api.service import UnknownPatient, patient_conflicts, run_task
from backend.app.layer3_store.db import make_engine, migrate
from backend.app.layer3_store.repository import ClinicalStore


def _llm():
    try:
        from backend.app.layer2_extraction.llm.provider import provider_from_env
        return provider_from_env()
    except Exception:  # noqa: BLE001 - no provider configured is a normal state
        return None


DEMO_HEADER = "synthetic-data-only; no authentication; not for real patient data"


def create_app(store: ClinicalStore | None = None, llm=None, run_migrations: bool = True) -> FastAPI:
    # There is no user authentication or patient-level authorisation. Refuse to run unless explicitly in demo mode.
    if os.environ.get("CLINICAL_DEMO_ONLY", "1") != "1":
        raise RuntimeError("Authentication/authorisation is not implemented (see docs/SECURITY_AND_AUTH.md). "
                           "Only CLINICAL_DEMO_ONLY=1 with synthetic data is supported.")
    demo_token = os.environ.get("DEMO_API_TOKEN")
    if store is None:
        if run_migrations:
            migrate()
        store = ClinicalStore(make_engine())
    llm = llm if llm is not None else _llm()
    app = FastAPI(title="Clinical evidence platform API", version=API_VERSION)
    app.add_middleware(CORSMiddleware,
                       allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:8080").split(","),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"])

    @app.middleware("http")
    async def demo_guard(request, call_next):
        # Optional shared demo token: a gate against accidental exposure, NOT user authentication.
        if demo_token and request.url.path.startswith("/api") and request.url.path != "/api/health" \
                and request.method != "OPTIONS" and request.headers.get("authorization") != f"Bearer {demo_token}":
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "demo token required"}, status_code=401)
        response = await call_next(request)
        response.headers["X-Clinical-Demo"] = DEMO_HEADER
        return response
    app.state.store, app.state.llm = store, llm

    def _known(pid: str):
        if not store.documents(pid):
            raise HTTPException(404, f"Unknown patient {pid}")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "api_version": API_VERSION, "database": store.engine.dialect.name,
                "llm_configured": llm is not None, "mode": DEMO_HEADER, "demo_token_required": bool(demo_token)}

    @app.get("/api/patients", response_model=list[PatientSummary])
    def patients():
        return store.patients()

    @app.get("/api/patients/{pid}/documents", response_model=list[DocumentOut])
    def documents(pid: str):
        _known(pid)
        return [DocumentOut(document_id=d.document_id, title=d.title, document_date=d.document_date,
                            document_type=d.document_type, hospital=d.hospital, source_sha256=d.source_sha256)
                for d in store.documents(pid)]

    @app.get("/api/patients/{pid}/documents/{doc_id}", response_model=DocumentOut)
    def document(pid: str, doc_id: str):
        found = store.document(pid, doc_id)
        if not found:
            raise HTTPException(404, "Unknown document for this patient")
        d, ps = found
        return DocumentOut(document_id=d.document_id, title=d.title, document_date=d.document_date,
                           document_type=d.document_type, hospital=d.hospital, source_sha256=d.source_sha256,
                           normalized_text=d.normalized_text,
                           passages=[PassageOut(passage_id=p.passage_id, passage_type=p.passage_type, section=p.section,
                                                section_title=p.section_title, normalized_start=p.normalized_start,
                                                normalized_end=p.normalized_end, original_start=p.original_start,
                                                original_end=p.original_end, display_text=p.display_text) for p in ps])

    @app.get("/api/patients/{pid}/facts")
    def facts(pid: str, fact_type: str | None = None):
        _known(pid)
        return [f.model_dump(mode="json") for f in store.facts(pid, types=[fact_type] if fact_type else None)]

    @app.get("/api/patients/{pid}/conflicts")
    def conflicts(pid: str):
        _known(pid)
        return [c.model_dump() for c in patient_conflicts(store, pid)]

    @app.post("/api/tasks", response_model=TaskResponse)
    def task(req: TaskRequest):
        try:
            return run_task(store, req.patient_id, req.request, llm)
        except UnknownPatient:
            raise HTTPException(404, f"Unknown patient {req.patient_id}")
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.get("/api/patients/{pid}/review")
    def review_list(pid: str):
        _known(pid)
        return store.review_items(pid)

    @app.post("/api/patients/{pid}/review")
    def review_update(pid: str, upd: ReviewUpdate):
        _known(pid)
        store.upsert_review_item(pid, upd.item_key, upd.item_type, upd.summary, {})
        return store.set_review_status(pid, upd.item_key, upd.status, upd.reviewer, upd.comment)

    return app


app = create_app() if os.environ.get("CLINICAL_API_NO_AUTOSTART") != "1" else None
