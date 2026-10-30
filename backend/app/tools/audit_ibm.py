"""Audit the original IBM synthetic patient archive without exporting source text.

Pure Python stdlib; does not need API keys, external models or database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


def audit_ibm_zip(zip_path: str | Path) -> dict:
    """Validate that the archive has coherent documents and benchmark citations.

    This audit does not assert that any extracted clinical content is correct.
    """
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)
    with ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith('/')]
        doc_paths = sorted(n for n in names if '/documents/' in n and n.endswith('.json'))
        benchmark_paths = [n for n in names if n.endswith('/cases/expected.json')]
        if not doc_paths or len(benchmark_paths) != 1:
            raise ValueError('Expected clinical JSON documents and one cases/expected.json')
        doc_ids: set[str] = set()
        docs: list[dict] = []
        warnings: list[str] = []
        for name in doc_paths:
            record = json.loads(z.read(name))
            metadata = record.get('metadata') or {}
            content = record.get('text')
            if not isinstance(content, str):
                raise ValueError(f'Missing source text: {name}')
            doc_id = str(metadata.get('id') or Path(name).stem)
            if doc_id in doc_ids:
                raise ValueError(f'Duplicate document ID: {doc_id}')
            if Path(name).stem != doc_id:
                warnings.append(f'Filename and metadata ID differ: {name}')
            doc_ids.add(doc_id)
            docs.append({
                'document_id': doc_id,
                'title': metadata.get('title'),
                'date': metadata.get('date'),
                'characters': len(content),
                'sha256_text': hashlib.sha256(content.encode('utf-8')).hexdigest(),
            })
        questions = json.loads(z.read(benchmark_paths[0]))
        if not isinstance(questions, list):
            raise ValueError('Expected benchmark list')
        referenced_ids = [doc_id for q in questions for doc_id in q.get('sources', [])]
        missing = sorted(set(referenced_ids) - doc_ids)
        if missing:
            warnings.append(f'Benchmark references unknown documents: {missing}')
        return {
            'document_count': len(docs),
            'document_characters': sum(d['characters'] for d in docs),
            'benchmark_question_count': len(questions),
            'benchmark_situation_count': len(set(q.get('situation') for q in questions)),
            'source_references_checked': len(referenced_ids),
            'invalid_source_references': len([n for n in referenced_ids if n not in doc_ids]),
            'documents': docs,
            'warnings': warnings,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description='Audit original IBM archive without exporting clinical text')
    parser.add_argument('--zip', required=True, help='Private original IBM zip path')
    args = parser.parse_args()
    print(json.dumps(audit_ibm_zip(args.zip), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
