# Layer 1 — Implementation choices and known limitations

- **Source of truth**: original `documents/*.json` text; extracted JSON from IBM is never promoted to clinical ground truth by this layer.
- **Character coordinates**: offsets refer to Python codepoint indices in the `text` field after JSON decoding, not JSON-file byte coordinates, DOM nodes or HTML-decoded text. `source_sha256` version-locks offsets.
- **Interchange**: `EvidencePassage` is the canonical internal model, BioC JSON is an optional projection; in BioC, passage text is the *raw* source slice and `offset` is its raw character start.
- **Section engine**: `medspacy` attempts its actual Sectionizer via spaCy German; `rules` is deterministic fallback; `auto` chooses based on installed dependencies. Both apply the same curated versioned heading list. Unrecognized headings are retained rather than discarded.
- **Conservative splitting**: physical row boundaries take precedence over sentence segmentation. Fragments separated by lower-case continuation can be grouped into one passage. German prose with capitalized continuation, nested heading structures and complex HTML tables still require stronger parsing and clinical validation.
- **Coverage**: every non-whitespace displayed character must be contained in a passage. This is a structural property, not clinical completeness.
- **Privacy**: no IBM content bundled, generated index contains document text; store it privately.
- **Proposed next module**: Layer 2 should consume `EvidencePassage` (patient_id, source_id, raw span, type, section) and create *candidates* rather than guaranteed diagnoses.
- **Future integrations**: ELGA CDA, FHIR R4 and OCR are new adapters; structured FHIR data should be retained as typed resources rather than passed through arbitrary sentence segmentation.
