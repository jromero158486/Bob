# Lumen Clinical

**The right patient information, for the right clinician, with evidence you can check.**

**Healthcare Hackathon Vienna 2026 · Track 1: Clinical Documentation**  
**[Open the live demo](https://screenshot-stitchery-studio.lovable.app)** (live FastAPI backend on Exoscale, Vienna) · [IBM judging results](docs/JUDGING_RESULTS.md) · [Scientific report](docs/SCIENTIFIC_REPORT.md)

## The problem

A patient's story is scattered across clinical letters, medication lists and reports. Finding what matters for a specific clinical task takes time. Records may disagree, and missing information can be mistaken for a documented negative finding.

## Our solution

**Lumen Clinical** turns German medical documents into a task-focused, evidence-linked clinical workspace. A clinician can describe **any role and question** in German or English. Lumen retrieves relevant information, brings together the patient's history, flags conflicting or missing details, and links findings to the **exact passages in the original documents**.

**It supports clinical review; it does not replace clinical judgment.**

## Try it in the demo

To reproduce the five official IBM scenarios, follow [docs/DEMO_SCRIPT_IBM.md](docs/DEMO_SCRIPT_IBM.md). A two-minute walkthrough script is in [docs/DEMO_VIDEO_SCRIPT.md](docs/DEMO_VIDEO_SCRIPT.md).


1. **Preoperative review (German):** Role: `Anästhesistin` · Task: `Präoperative Abklärung: Allergien, Antikoagulation, Raucherstatus und relevante Herzbefunde?`
2. **Cancer treatment (English):** `What is the planned breast cancer treatment and when, and what are the receptor status and Ki-67?`
3. **Check the evidence:** Click any citation to see the original German text and highlighted source span; explore medication changes and record conflicts.
4. **Optional claim checker:** Open **Verify clinical statement** to check whether a statement is supported, contradicted or not addressed by the record.

## What it can do

- **Task-adaptive summaries:** Different clinical roles and questions surface different information.
- **Source-linked answers:** Click citations to inspect the original record, not just an AI-generated summary.
- **Longitudinal overview:** Explore diagnoses, events and medication lists across documents.
- **Discrepancy detection:** See conflicting values, dates and medication instructions.
- **Missing-information alerts:** Distinguish *not documented* from *documented absent*.
- **Human-in-the-loop review:** Review flagged findings; optionally verify a statement with multilingual NLI.

## How it works — seven layers

```mermaid
flowchart TD
    D["IBM synthetic patient documents<br/>(German clinical records)"] --> L1["L1 · Document ingestion & provenance<br/>Sections · exact source offsets"]
    L1 --> L2["L2 · Clinical information extraction<br/>Diagnoses · medications · negation"]
    L2 --> L3["L3 · Longitudinal knowledge store<br/>PostgreSQL · pgvector · dates"]

    U["Clinician: role + open-ended task<br/>(German or English)"] --> L4["L4 · Task interpretation<br/>Rule-based planner · optional LLM"]
    L4 --> L5["L5 · Relevant evidence retrieval<br/>Structured facts · BGE-M3 search"]
    L3 -->|Patient facts and source passages| L5
    L5 --> L6["L6 · Evidence and consistency checks<br/>Citations · conflicts · optional NLI"]
    L6 --> L7["L7 · Adaptive clinical interface<br/>Summaries · timelines · evidence inspector"]
    L7 --> O["Clinician reviews the result<br/>and opens original source evidence"]
```

**Technology actually running in the demo:**
- **Backend:** Python 3.11 / FastAPI.
- **Extraction:** rule-based German extraction with medSpaCy and German NegEx/ConText rules; local ATC/ICD-10/LOINC lexicons.
- **Storage:** PostgreSQL 16 + pgvector.
- **Retrieval:** BGE-M3 (`BAAI/bge-m3`) dense retrieval, plus structured fact queries.
- **Planning:** a rule-based task planner. An LLM planner exists but is off in the demo.
- **Verification:** deterministic citation-integrity checks in every response; optional multilingual NLI (`mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`) on request.
- **Frontend:** React / TypeScript built with Lovable.
- **Hosting:** Docker Compose on one Exoscale VM, with Caddy HTTPS and a demo token.

Deferred and **not** in the demo: FHIR export, temporal knowledge graph, autonomous (ReAct) agent.

## IBM Track 1 audit (official 5 situations, 15 questions)

Run on the published app and hosted backend; full details in [docs/JUDGING_RESULTS.md](docs/JUDGING_RESULTS.md).

| Metric | Result |
|---|---|
| Correct answers, visible without clicking | **12/15**: 2 partial (ED cause link, follow-up interval), 1 failed (kidney function not flagged as undocumented) |
| Traceability | **100%**: 456/456 displayed facts linked; 747/747 links reproduce the exact original passage |
| Invented facts | **0 found** in manual review of the answer facts |
| Contradictions | 8 flagged: 7 real, 1 false alarm (net +6); changes over time are not flagged |
| Slowest screen | **1.9 s** (target < 10 s) |

## Early evaluation

On **one synthetic IBM patient (8 documents)**, our internal evaluation found:

- **Passage fact recall@10:** BGE-M3 dense retrieval **57%** versus **9%** for keyword-only retrieval (28 bilingual queries).
- **Claim checking:** **0 false-supported claims** in a small 34-claim evaluation with deterministic checks plus multilingual NLI; contradiction recall was **55%**.
- **English ↔ German:** 5 new task pairs and 6 statement pairs, checked by hand. Results and the fixes (on a branch) are in [docs/MULTILINGUAL_RESULTS.md](docs/MULTILINGUAL_RESULTS.md).

These are **preliminary, small-sample engineering results**, not evidence of clinical safety or generalization. See the [scientific report](docs/SCIENTIFIC_REPORT.md) for methods, baselines and limitations.

## Scope and limitations

This is a **research prototype using synthetic hackathon data**, not a medical device. A *supported* claim means that it matches the cited record, **not that it has been clinically verified**. Advanced NLI verification is optional; the main response prioritizes speed and strict source integrity. The demo does not implement hospital-grade authentication or patient authorization; the demo token is visible in the public web app and only keeps out casual traffic.

**Known gaps from the IBM audit:**
- Implicit contrast-imaging context does not trigger the kidney-function check.
- Causal links and follow-up intervals stay in the cited passages instead of the answer line.
- Conflicts show explanations with source buttons rather than side-by-side passages.
- Some screens include extra, older facts.
- Claim verification does not map English generic drug names ("aspirin").
- Everything was evaluated on **one synthetic patient**, and the 15 questions informed the rule vocabulary.

**Project resources:** [IBM judging results](docs/JUDGING_RESULTS.md) · [IBM demo script](docs/DEMO_SCRIPT_IBM.md) · [Video script](docs/DEMO_VIDEO_SCRIPT.md) · [Scientific report](docs/SCIENTIFIC_REPORT.md) · [Demo runbook](docs/DEMO_RUNBOOK.md) · [Windows backup setup](docs/WINDOWS_SETUP.md) · [Security limitations](docs/SECURITY_AND_AUTH.md)
