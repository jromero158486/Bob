"""Run the 5 official IBM Track 1 situations (and optional extra tasks) against a live /api/v1 deployment.

Input to the system is only each situation's title + description (cases/situations.md) and a role noun; expected.json
is never sent. Saves the raw screen payloads, wall-clock latency and an automatic citation-integrity check of every
evidence link (quote == document section text at the given offsets, and quote present in the original document).
Clinical correctness of the 15 answers is graded manually from the saved screens (see docs/JUDGING_RESULTS.md).

  CLINICAL_API_TOKEN=... python -m evaluation.judging.hosted_ibm_audit --base https://<host>/api/v1 \
      --cases <ibm>/cases --data <ibm>/data --out artifacts/judging [--extra tasks.json]
"""
import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from backend.app.tools.run_benchmark import situations

ROLES = ["Anaesthetist", "Surgeon", "General practitioner", "Emergency physician", "General practitioner"]
PATIENT = "patient-0000-0001"


def call(base: str, path: str, token: str, body: dict | None = None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body else None, method="POST" if body else "GET",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                                          "User-Agent": "lumen-judging-audit"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.loads(r.read())
    return data, (time.perf_counter() - t0) * 1000


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", " ", s, flags=re.I)).strip().casefold()


def integrity(screen: dict, sections: dict, originals: dict) -> dict:
    links = bad = 0
    problems = []
    for f in screen["facts"].values():
        for ev in f.get("evidence", []):
            links += 1
            sec = sections.get(ev["sectionId"], "")
            ok_offsets = sec[ev["start"]:ev["end"]] == ev["quote"] and ev["quote"].strip()
            ok_source = _norm(ev["quote"]) in originals.get(ev["documentId"], "")
            if not (ok_offsets and ok_source):
                bad += 1
                problems.append({"fact": f["statement"][:80], "doc": ev["documentId"], "offsets": bool(ok_offsets),
                                 "in_original": ok_source})
    facts_with = sum(bool(f.get("evidence")) for f in screen["facts"].values())
    return {"facts": len(screen["facts"]), "facts_with_evidence": facts_with, "links": links, "bad_links": bad,
            "problems": problems}


def condensed(screen: dict) -> str:
    out = [f"INTENT: {screen.get('interpretedIntent')}"]
    for b in screen["blocks"]:
        out.append(f"## [{b['kind']}] {b['title']} (priority={b.get('priority')}, relevance={b.get('taskRelevance')})")
        for s in b.get("sentences", []):
            out.append(f"  * {s['text']}")
        for fid in b.get("factIds", []):
            f = screen["facts"][fid]
            docs = sorted({e["documentId"] for e in f.get("evidence", [])})
            out.append(f"  - {f['statement']} [{f['verification']}] {f.get('eventDate') or f.get('documentDate') or ''} {docs}")
        for i in b.get("items", []):
            out.append(f"  ? {i['label']}: {i['detail']}")
        for c in b.get("conflicts", []):
            q = [(screen['facts'][x]['statement'][:70], [e['documentId'] for e in screen['facts'][x].get('evidence', [])])
                 for x in c["factIds"] if ":ev" in x]
            out.append(f"  ! {c['topic']}: {c['explanation']} {q}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--cases", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="artifacts/judging")
    ap.add_argument("--extra", help="JSON list of {role, task} (new tasks, not from the benchmark)")
    a = ap.parse_args()
    token = os.environ["CLINICAL_API_TOKEN"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    docs, _ = call(a.base, f"/patients/{PATIENT}/documents", token)
    sections = {s["id"]: s["text"] for d in docs for s in d["sections"]}
    originals = {}
    for p in Path(a.data, PATIENT, "documents").glob("*.json"):
        rec = json.loads(p.read_text())
        originals[str((rec.get("metadata") or {}).get("id") or p.stem)] = _norm(rec["text"])
    tasks = [{"id": f"S{i + 1}", "role": ROLES[i], "task": f"{s['title']}. {s['description']}"}
             for i, s in enumerate(situations(Path(a.cases, "situations.md").read_text()))]
    if a.extra:
        tasks += [{"id": f"N{i + 1}", **t} for i, t in enumerate(json.loads(Path(a.extra).read_text()))]
    summary = []
    for t in tasks:
        screen, ms = call(a.base, "/clinical-tasks", token, {"patientId": PATIENT, "role": t["role"], "task": t["task"]})
        (out / f"{t['id']}.json").write_text(json.dumps(screen, ensure_ascii=False, indent=1))
        (out / f"{t['id']}.txt").write_text(f"ROLE: {t['role']}\nTASK: {t['task']}\nLATENCY_MS: {ms:.0f}\n" + condensed(screen))
        row = {**t, "latency_ms": round(ms), **integrity(screen, sections, originals)}
        summary.append(row)
        print(f"{t['id']} {ms:6.0f} ms facts={row['facts']} links={row['links']} bad={row['bad_links']}")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
