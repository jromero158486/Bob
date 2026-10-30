"""Read the private synthetic IBM data from directories OR the supplied ZIP.

Never saves records on disk and never imports diagnoses.json etc as ground truth.
"""
import hashlib
import json
from pathlib import Path
from collections.abc import Iterator
from zipfile import ZipFile
from backend.app.layer1_ingestion.adapters.base import SourceAdapter
from backend.app.shared.contracts.evidence import SourceDocument


def _from_bytes(content: bytes, path: str) -> SourceDocument:
    obj = json.loads(content.decode("utf-8-sig"))
    if not isinstance(obj, dict) or not isinstance(obj.get("text"), str):
        raise ValueError(f"Invalid original source document at {path}: missing text string")
    metadata = obj.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"Invalid metadata at {path}")
    parts = Path(path.replace("\\", "/")).parts
    parent = next((p for p in reversed(parts) if p.startswith("patient-") and p != "documents"), None)
    patient_id = parent or metadata.get("patientId")
    if not patient_id:
        raise ValueError(f"Missing patient identity in {path}; refusing ambiguous patient assignment")
    patient_id = str(patient_id)
    document_id = str(metadata.get("id") or Path(path).stem)
    original = obj["text"]
    admission = metadata.get("admission") or {}
    encounter_id = str(admission["id"]) if isinstance(admission, dict) and admission.get("id") else None
    return SourceDocument(
        patient_id=patient_id,
        document_id=document_id,
        original_text=original,
        source_hash=hashlib.sha256(original.encode("utf-8")).hexdigest(),
        source_name=path,
        source_format="ibm-json",
        document_title=str(metadata.get("title") or "Untitled clinical document"),
        document_date=str(metadata["date"]) if metadata.get("date") is not None else None,
        document_version=str(metadata.get("version", "1")),
        document_type=str(metadata["type"]) if metadata.get("type") else None,
        hospital=str(metadata["hospital"]) if metadata.get("hospital") else None,
        encounter_id=encounter_id,
        metadata=metadata,
        source_namespace="ibm-json",
    )


def _is_clinical_json(name: str) -> bool:
    x = name.replace("\\", "/")
    return "/documents/" in "/" + x and x.endswith(".json")


class IBMJsonAdapter(SourceAdapter):
    def __init__(self, location: str | Path):
        self.location = Path(location)

    def load(self) -> Iterator[SourceDocument]:
        source = self.location
        if source.is_file() and source.suffix.casefold() == ".zip":
            with ZipFile(source) as archive:
                paths = sorted(n for n in archive.namelist() if _is_clinical_json(n) and not n.startswith("__MACOSX/"))
                if not paths:
                    raise ValueError(f"No patient documents in ZIP: {source}")
                for name in paths:
                    yield _from_bytes(archive.read(name), name)
        elif source.is_dir():
            if source.name == "documents":
                paths = sorted(source.glob("*.json"))
            else:
                paths = sorted(source.rglob("documents/*.json"))
            if not paths:
                raise ValueError(f"No patient documents in directory: {source}")
            for path in paths:
                yield _from_bytes(path.read_bytes(), str(path))
        else:
            raise FileNotFoundError(f"Clinical input not found: {source}")
