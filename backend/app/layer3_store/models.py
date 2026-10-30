"""Layer 3 relational model (SQLAlchemy 2.0). PostgreSQL in deployment, SQLite for tests.

Patient isolation is enforced by composite foreign keys: a fact, passage or evidence row
must reference a document *of the same patient* (patient_id, source_id), so cross-patient
links are rejected by the database itself, not only by application code.
Dates: event_date (clinical), document_date (source), ingested_at/created_at (processing) are separate.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Patient(Base):
    __tablename__ = "patients"
    patient_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_namespace: Mapped[str] = mapped_column(String(64), default="local")
    display_name: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Encounter(Base):
    __tablename__ = "encounters"
    encounter_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    source_encounter_id: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str | None] = mapped_column(String(32))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("patient_id", "source_encounter_id"),)


class Document(Base):
    __tablename__ = "documents"
    source_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    document_id: Mapped[str] = mapped_column(String(128))
    document_version: Mapped[str] = mapped_column(String(32))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_format: Mapped[str] = mapped_column(String(32))
    source_namespace: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(256))
    document_date: Mapped[str | None] = mapped_column(String(10), index=True)
    document_type: Mapped[str | None] = mapped_column(String(128))
    hospital: Mapped[str | None] = mapped_column(String(256))
    encounter_key: Mapped[str | None] = mapped_column(ForeignKey("encounters.encounter_key"))
    original_text: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    section_engine: Mapped[str] = mapped_column(String(32))
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    superseded_by: Mapped[str | None] = mapped_column(String(256))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    passages: Mapped[list["Passage"]] = relationship(back_populates="document", order_by="Passage.original_start",
                                                      overlaps="facts")
    __table_args__ = (UniqueConstraint("patient_id", "source_id", name="uq_documents_patient_source"),
                      Index("ix_documents_patient_doc", "patient_id", "document_id"))


class Passage(Base):
    __tablename__ = "passages"
    passage_id: Mapped[str] = mapped_column(String(320), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(128), index=True)
    source_id: Mapped[str] = mapped_column(String(256))
    passage_type: Mapped[str] = mapped_column(String(32))
    section: Mapped[str | None] = mapped_column(String(64))
    section_title: Mapped[str | None] = mapped_column(String(256))
    original_start: Mapped[int] = mapped_column(Integer)
    original_end: Mapped[int] = mapped_column(Integer)
    normalized_start: Mapped[int] = mapped_column(Integer)
    normalized_end: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text)
    display_text: Mapped[str] = mapped_column(Text)
    document: Mapped[Document] = relationship(back_populates="passages", overlaps="passages")
    __table_args__ = (
        ForeignKeyConstraint(["patient_id", "source_id"], ["documents.patient_id", "documents.source_id"],
                             ondelete="CASCADE", name="fk_passages_patient_document"),
        UniqueConstraint("patient_id", "passage_id", name="uq_passages_patient_passage"),
    )


class ExtractionRunRow(Base):
    __tablename__ = "extraction_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSON)


class Fact(Base):
    __tablename__ = "facts"
    fact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    patient_id: Mapped[str] = mapped_column(String(128), index=True)
    source_id: Mapped[str] = mapped_column(String(256))
    document_id: Mapped[str] = mapped_column(String(128))
    fact_type: Mapped[str] = mapped_column(String(32), index=True)
    label: Mapped[str] = mapped_column(Text)
    concept: Mapped[str | None] = mapped_column(String(128), index=True)
    primary_code: Mapped[str | None] = mapped_column(String(32), index=True)
    details: Mapped[dict] = mapped_column(JSON)
    codings: Mapped[list] = mapped_column(JSON, default=list)
    assertion: Mapped[dict] = mapped_column(JSON)
    negated: Mapped[bool] = mapped_column(Boolean, default=False)
    certainty: Mapped[str] = mapped_column(String(16))
    temporality: Mapped[str] = mapped_column(String(16))
    experiencer: Mapped[str] = mapped_column(String(16))
    question: Mapped[bool] = mapped_column(Boolean, default=False)
    event_date: Mapped[str | None] = mapped_column(String(10), index=True)
    event_date_precision: Mapped[str | None] = mapped_column(String(8))
    event_date_source: Mapped[str | None] = mapped_column(String(32))
    document_date: Mapped[str | None] = mapped_column(String(10))
    section: Mapped[str | None] = mapped_column(String(64))
    extractor_name: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(128))
    review_status: Mapped[str] = mapped_column(String(32))
    notes: Mapped[list] = mapped_column(JSON, default=list)
    run_id: Mapped[str] = mapped_column(ForeignKey("extraction_runs.run_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    evidence: Mapped[list["EvidenceRow"]] = relationship(back_populates="fact", cascade="all, delete-orphan",
                                                         order_by="EvidenceRow.id")
    __table_args__ = (
        ForeignKeyConstraint(["patient_id", "source_id"], ["documents.patient_id", "documents.source_id"],
                             ondelete="CASCADE", name="fk_facts_patient_document"),
        Index("ix_facts_patient_type", "patient_id", "fact_type"),
    )


class EvidenceRow(Base):
    __tablename__ = "evidence_spans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fact_id: Mapped[str] = mapped_column(ForeignKey("facts.fact_id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[str] = mapped_column(String(128))
    source_id: Mapped[str] = mapped_column(String(256))
    passage_id: Mapped[str] = mapped_column(String(320))
    source_sha256: Mapped[str] = mapped_column(String(64))
    original_start: Mapped[int] = mapped_column(Integer)
    original_end: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text)
    display_text: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32))
    fact: Mapped[Fact] = relationship(back_populates="evidence")
    __table_args__ = (
        ForeignKeyConstraint(["patient_id", "source_id"], ["documents.patient_id", "documents.source_id"],
                             ondelete="CASCADE", name="fk_evidence_patient_document"),
        ForeignKeyConstraint(["patient_id", "passage_id"], ["passages.patient_id", "passages.passage_id"],
                             ondelete="CASCADE", name="fk_evidence_patient_passage"),
    )


class ReviewItem(Base):
    """Human review queue entry for a displayed claim or conflict (auditable via ReviewEvent)."""
    __tablename__ = "review_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patient_id: Mapped[str] = mapped_column(ForeignKey("patients.patient_id"), index=True)
    item_key: Mapped[str] = mapped_column(String(128))
    item_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    events: Mapped[list["ReviewEvent"]] = relationship(back_populates="item", order_by="ReviewEvent.id",
                                                       cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("patient_id", "item_key"),)


class ReviewEvent(Base):
    __tablename__ = "review_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("review_items.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    reviewer: Mapped[str] = mapped_column(String(128))
    comment: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    item: Mapped[ReviewItem] = relationship(back_populates="events")
