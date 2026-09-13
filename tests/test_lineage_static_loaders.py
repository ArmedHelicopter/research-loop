import json

import pytest

from evaluation.modular.canonical_lineage import normalize_reference
from evaluation.modular.fresh_airs_custodian import CustodyError
from evaluation.modular.lineage_static_loaders import extract_fixed_slots, validate_factors

SECRET = "PRIVATE_CODE_DYNAMIC_KEY_GOLD"


def extract(code):
    return extract_fixed_slots({"prepare.py": code})


def test_alias_and_unshadowed_closure_are_syntax_references_without_execution():
    out = extract("from datasets import load_dataset as ld\ndef f():\n    return ld('owner/corpus', revision='aabb')\nraise RuntimeError('" + SECRET + "')")
    assert out["counts"]["resolved_call_count"] == 1
    assert out["counts"]["literal_revision_count"] == 1
    assert out["canonical_fingerprints"]["hf_dataset"] == [normalize_reference("owner/corpus", "hf_dataset")[1]]
    assert SECRET not in json.dumps(out)


@pytest.mark.parametrize("code", [
    "from datasets import load_dataset\ndef f(load_dataset):\n return load_dataset('owner/corpus')",
    "import datasets as ds\ndef f():\n ds = object()\n return ds.load_dataset('owner/corpus')",
    "from datasets import load_dataset\nload_dataset = fake\nload_dataset('owner/corpus')",
    "import datasets as ds\nds.load_dataset = fake\nds.load_dataset('owner/corpus')",
    "import datasets as ds\nmutate(ds)\nds.load_dataset('owner/corpus')",
    "from datasets import load_dataset\nf = lambda load_dataset: load_dataset('owner/corpus')",
    "from datasets import load_dataset\nglobals()['load_dataset'] = fake\nload_dataset('owner/corpus')",
    "from datasets import load_dataset\nload_dataset(NAME)",
    "from datasets import load_dataset\nload_dataset('owner/corpus', revision=REVISION)",
    "from datasets import load_dataset\nload_dataset('owner/corpus', data_files=FILES)",
    "from datasets import load_dataset\nload_dataset('owner/corpus', **kw)",
    "from datasets import load_dataset\nload_dataset(f'owner/{name}')",
    "from datasets import load_dataset\nload_dataset('legacy_label')",
])
def test_shadowed_dynamic_or_ambiguous_references_stay_unresolved(code):
    out = extract(code)
    assert out["counts"]["resolved_call_count"] == 0
    assert out["counts"]["unresolved_call_count"] == 1
    assert not any(out["canonical_fingerprints"].values())


def test_literal_data_url_mapping_ignores_dynamic_keys_and_local_filenames():
    out = extract("import datasets as ds\nds.load_dataset('csv', data_files={'" + SECRET + "': ['https://example.org/a.csv', 'local.csv']})")
    assert out["counts"]["resolved_call_count"] == 1
    assert out["counts"]["literal_data_url_count"] == 1
    assert out["counts"]["unresolved_data_file_count"] == 1
    assert SECRET not in json.dumps(out)
    assert not out["canonical_fingerprints"]["hf_dataset"]


def test_official_openml_and_kaggle_calls_use_literal_identifiers_only():
    out = extract("from sklearn.datasets import fetch_openml as fm\nimport kagglehub as kh\nfm(data_id=123)\nkh.dataset_download('owner/corpus/versions/2')")
    assert out["counts"]["resolved_call_count"] == 2
    assert out["counts"]["literal_revision_count"] == 2
    assert len(out["canonical_fingerprints"]["source_url"]) == 2


def test_fixed_slots_never_visit_evaluator_or_dynamic_file_maps():
    class Bomb:
        def __str__(self):
            raise AssertionError(SECRET)
    out = extract_fixed_slots({"evaluate.py": Bomb(), SECRET: Bomb(), "files": {"prepare.py": Bomb()}, "evaluate_prepare.py": "from datasets import load_dataset\nload_dataset('owner/corpus')"})
    assert out["counts"]["slot_present_count"] == 1
    assert out["counts"]["slot_missing_count"] == 1
    assert out["counts"]["resolved_call_count"] == 1


def test_syntax_errors_and_public_unknown_fields_do_not_export_code(capsys):
    out = extract("import " + SECRET + " !!!")
    assert out["counts"]["syntax_error_count"] == 1
    assert SECRET not in json.dumps(out)
    with pytest.raises(CustodyError) as error:
        validate_factors({**out, SECRET: SECRET})
    assert SECRET not in str(error.value)
    assert capsys.readouterr().out == ""
