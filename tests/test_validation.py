import shutil
from pathlib import Path
from uuid import uuid4
import filecmp
import pytest

from earthcode.validator import validate_catalog
from earthcode.static import generate_OSC_dummy_entries
from earthcode.git_add import (save_product_collection_to_catalog, 
                               save_workflow_record_to_osc, 
                               save_project_collection_to_osc, 
                               save_experiment_record_to_osc)

### asummes a error free catalog
SOURCE_CATALOG = Path("../open-science-catalog-metadata/").resolve()


@pytest.fixture()
def catalog_root(tmp_path: Path) -> Path:

    if not SOURCE_CATALOG.exists():
        pytest.skip(f"Missing source catalog at {SOURCE_CATALOG}")

    target = tmp_path / "open-science-catalog-metadata"
    shutil.copytree(SOURCE_CATALOG, target)
    return target


def test_validation(catalog_root: Path):
    errors, error_files = validate_catalog(catalog_root)
    assert error_files == []
    assert errors == []


def test_creation_and_validation(catalog_root: Path):

    unique_suffix = f"+{uuid4().hex[:8]}"
    
    project, product, workflow, experiment = generate_OSC_dummy_entries(id_extension=unique_suffix)

    # assert that files are created
    assert not (catalog_root / f'projects/{project.id}/collection.json').exists()
    save_project_collection_to_osc(project, catalog_root)
    assert (catalog_root / f'projects/{project.id}/collection.json').exists()

    assert not (catalog_root / f'products/{product.id}/collection.json').exists()
    save_product_collection_to_catalog(product, catalog_root)
    assert (catalog_root / f'products/{product.id}/collection.json').exists()

    assert not (catalog_root / f'workflows/{workflow['id']}/record.json').exists()
    save_workflow_record_to_osc(workflow, catalog_root)
    assert (catalog_root / f'workflows/{workflow['id']}/record.json').exists()

    assert not (catalog_root / f'experiments/{experiment['id']}/record.json').exists()
    save_experiment_record_to_osc(experiment, catalog_root)
    assert (catalog_root / f'experiments/{experiment['id']}/record.json').exists()

    # assert that everything passes validation
    errors, error_files = validate_catalog(catalog_root)
    assert len(error_files) == 0
    assert len(errors) == 0

    # count updated , deleted and created files
    source_files = {f.relative_to(SOURCE_CATALOG) for f in SOURCE_CATALOG.rglob('*') if f.is_file()}
    target_files = {f.relative_to(catalog_root) for f in catalog_root.rglob('*') if f.is_file()}

    created_files = target_files - source_files
    deleted_files = source_files - target_files
    common_files = source_files & target_files
    modified_files = set()

    for rel_path in common_files:
        src_file = SOURCE_CATALOG / rel_path
        tgt_file = catalog_root / rel_path
        
        # Setting shallow=False forces Python to compare the actual file contents 
        # rather than just checking OS metadata like modification times.
        if not filecmp.cmp(src_file, tgt_file, shallow=False):
            modified_files.add(rel_path)

    assert len(created_files) == 4
    assert len(deleted_files) == 0
    assert len(modified_files) == 8
