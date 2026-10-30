"""Standalone GERNERMED++ worker. Runs inside its own Python env (spaCy 3.2.x).

stdin: {"model": "<package or path>", "texts": [...]}  stdout: JSON with entities + model metadata.
Only depends on spaCy so it can run in an interpreter isolated from the main app.
"""
import json
import sys


def main() -> None:
    req = json.loads(sys.stdin.read())
    import spacy
    nlp = spacy.load(req["model"])
    results = []
    for doc in nlp.pipe(req["texts"], batch_size=32):
        results.append([{"label": e.label_, "start": e.start_char, "end": e.end_char, "text": e.text} for e in doc.ents])
    meta = nlp.meta
    json.dump({"model": meta.get("name"), "model_version": meta.get("version"), "spacy_version": spacy.__version__,
               "labels": meta.get("labels", {}).get("ner", []), "license": meta.get("license") or "unspecified",
               "results": results}, sys.stdout)


if __name__ == "__main__":
    main()
