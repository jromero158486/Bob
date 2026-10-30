"""Generate frontend/src/api/schema.ts (TypeScript types) from the FastAPI OpenAPI schema.

python -m backend.app.tools.gen_ts_types   (writes docs/openapi.json and frontend/src/api/schema.ts)
"""
import json
import os
from pathlib import Path

os.environ.setdefault("CLINICAL_API_NO_AUTOSTART", "1")


def ts(s: dict) -> str:
    if "$ref" in s:
        return s["$ref"].split("/")[-1]
    if "const" in s:
        return json.dumps(s["const"])
    if "enum" in s:
        return " | ".join(json.dumps(v) for v in s["enum"])
    for k in ("anyOf", "oneOf", "allOf"):
        if k in s:
            return " | ".join(dict.fromkeys(ts(x) for x in s[k]))
    t = s.get("type")
    if t == "array":
        inner = ts(s.get("items", {}))
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if t == "object" or "properties" in s:
        props = s.get("properties")
        if not props:
            extra = s.get("additionalProperties")
            return f"Record<string, {ts(extra) if isinstance(extra, dict) else 'unknown'}>"
        req = set(s.get("required", []))
        body = "".join(f"  {k}{'' if k in req else '?'}: {ts(v)};\n" for k, v in props.items())
        return "{\n" + body + "}"
    return {"string": "string", "integer": "number", "number": "number", "boolean": "boolean", "null": "null"}.get(t, "unknown")


def main():
    from backend.app.api.main import create_app
    from backend.app.layer3_store.db import make_engine
    from backend.app.layer3_store.repository import ClinicalStore
    spec = create_app(store=ClinicalStore(make_engine("sqlite:///:memory:")), run_migrations=False).openapi()
    root = Path(__file__).resolve().parents[3]
    (root / "docs" / "openapi.json").write_text(json.dumps(spec, indent=1))
    out = ["// AUTO-GENERATED from docs/openapi.json by backend/app/tools/gen_ts_types.py. Do not edit.\n"]
    for name, s in sorted(spec["components"]["schemas"].items()):
        out.append(f"export type {name} = {ts(s)};\n")
    (root / "frontend" / "src" / "api" / "schema.ts").write_text("\n".join(out))
    print(f"{len(spec['components']['schemas'])} types written")


if __name__ == "__main__":
    main()
