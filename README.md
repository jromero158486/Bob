# Clinical AI Platform — Step 1: Document Processing & Provenance

**Working milestone:** Layer 1 only. This is not a medical device and does not verify clinical truth. Layer 2–7 remain next steps.

This package intentionally **does not distribute IBM's original `data/` folder** or generated copies of it. Use the private hackathon ZIP on your machine. All offsets are Unicode codepoint positions in the *original JSON `text` string*, not UTF-8 byte offsets.

## 1. Run immediately (no model keys, no downloads required)

From the project root:

```bash
python -m backend.app.tools.ingest_layer1 --input '/private/AIM-hack-track1-shipit-main.zip' --engine rules
python -m pytest -q
```

- Accepts the original ZIP directly, a `patient-*` folder, a `documents/` folder, or a parent directory containing multiple patients.
- Ingests `documents/*.json`, **not** IBM's `diagnoses.json`, `medication.json` and other pre-extracted structures as clinical truth.
- Every original source substring is preserved and addressable by `passage_id`, checksum and offsets.
- A complete visible-text coverage check runs for every document.

To inspect a source citation explicitly:

```bash
python -m backend.app.tools.ingest_layer1 --input '/private/AIM-hack-track1-shipit-main.zip' --query 'Medikation'
```

To export a private BioC JSON file with passages and original offsets (**contains clinical source text**; never commit this output):

```bash
python -m backend.app.tools.ingest_layer1 --input '/private/AIM-hack-track1-shipit-main.zip' --export-bioc private_data/evidence.bioc.json
```

## 2. Use the published medSpaCy Sectionizer and BioC Python library

With a package index available:

```bash
python -m pip install -e '.[clinical,dev]'
python -m backend.app.tools.ingest_layer1 --input '/private/AIM-hack-track1-shipit-main.zip' --engine medspacy
```

`--engine auto` (the default) prefers the **actual** medSpaCy Sectionizer when installed; otherwise it uses the same explicit German heading rules with the built-in fallback. `--engine medspacy` fails loudly when the library isn't installed, so fallback can never be mistaken for medSpaCy. The `bioc` package is used for JSON serialization/validation when present. The equivalent BioC-JSON structure is exported using standard Python otherwise. **Neither library could be installed in the artifact-building environment because its package registry was unreachable; library-integrated execution therefore remains unverified here.**

## 3. Algorithm and scope

1. **IBM source adapter:** original JSON + full metadata, admission ID, hospital, namespaced patient ID, SHA-256. Ambiguous patient identity fails closed.
2. **Reversible projection:** HTML-ish `<BR>`, entities and CRLF to readable text with one original source span per displayed character. Original text is never overwritten.
3. **German sectionizer:** versionable dictionary of broad German clinical headings, optionally passed through the real medSpaCy Sectionizer (inspired by SecTag). Unknown colon headings retained as `unclassified`.
4. **Conservative segmenter:** preserve clinical medication rows, table headers and measurement rows; split narrative with punctuation heuristics, merging lowercase continuations.
5. **Evidence records:** immutable `EvidencePassage` objects with raw/document IDs, source checksum, original text offsets, section and type.
6. **Integrity verifier:** raw slice equals source, checksum matches, no duplicate passage IDs, no uncovered non-whitespace normalized characters.
7. **Optional BioC export:** passage-level offsets for annotation tools and future interoperability.

The parser does **not** infer diagnoses, ingredient codes, dosage meaning, normal ranges or clinical correctness; Layer 2 will do extraction. It does not currently parse arbitrary PDFs, OCR or production HL7 CDA/FHIR documents. Its adapters interface makes those additions possible, but they still require implementation and evaluation.

## Papers and references

- [medSpaCy / Sectionizer](https://github.com/medspacy/medspacy) — reusable clinical document sectioning.
- [BioC interchange format](https://github.com/bionlplab/bioc) — offset-linked passages and annotations.
- [CARDIO:DE (2023)](https://www.nature.com/articles/s41597-023-02128-9) — German clinical document classification reference; **not bundled or trained on**.
- [ELGA technical guides](https://www.elga.gv.at/technischer-hintergrund/technische-elga-leitfaeden/) — design reference for future CDA adapter, **not yet integrated**.

## Evaluation honesty

A valid character offset proves a passage appears in the given source document, **not** that it was clinically extracted correctly. The unit tests exercise unknown headings, multi-patient isolation, source integrity, Unicode/HTML entities, medication-row preservation, and BioC output. Further manual evaluation of section accuracy, sentence splitting, completeness and new hospital templates is required before deployment.

See `docs/IMPLEMENTATION_PLAN.md` for the remaining layers.
