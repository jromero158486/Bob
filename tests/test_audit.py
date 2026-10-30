import json
from zipfile import ZipFile

from backend.app.tools.audit_ibm import audit_ibm_zip


def test_audit_with_minimal_synthetic_fixture(tmp_path):
    archive = tmp_path / 'sample.zip'
    with ZipFile(archive, 'w') as z:
        z.writestr('sample/data/patient-test/documents/1234.json', json.dumps({
            'metadata': {'id': '1234', 'title': 'Example', 'date': '2016-01-01'},
            'text': 'A completely synthetic example.'
        }))
        z.writestr('sample/cases/expected.json', json.dumps([{
            'id': 'A', 'situation': 'Test', 'question': 'Q', 'answer': 'A', 'sources': ['1234']
        }]))
    result = audit_ibm_zip(archive)
    assert result['document_count'] == 1
    assert result['benchmark_question_count'] == 1
    assert result['invalid_source_references'] == 0
    assert result['document_characters'] == len('A completely synthetic example.')
    assert result['warnings'] == []
    # Source text must not appear in the report.
    assert 'A completely synthetic example.' not in json.dumps(result)


def test_audit_flags_missing_reference(tmp_path):
    archive = tmp_path / 'sample.zip'
    with ZipFile(archive, 'w') as z:
        z.writestr('sample/data/patient-test/documents/1234.json', json.dumps({
            'metadata': {'id': '1234'}, 'text': 'Synthetic.'
        }))
        z.writestr('sample/cases/expected.json', json.dumps([{
            'situation': 'Test', 'sources': ['missing-doc']
        }]))
    result = audit_ibm_zip(archive)
    assert result['invalid_source_references'] == 1
