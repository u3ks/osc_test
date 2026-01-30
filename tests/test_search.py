import pytest

from earthcode.search import search

def test_search_by_collection_id_returns_collection():
    results = search(collection_ids="seasfire-cube", limit=1)
    assert results, "no results returned"
    first = results[0]
    assert getattr(first, "id", None) == "seasfire-cube"

def test_basic_semantic_search_returns_items():
    results = search("forest fires", limit=3)
    assert len(results) > 0
    assert all(getattr(r, "id", None) for r in results)

def test_bbox_intersects_hits_expected_product():
    alps_bbox = [5.95591129, 45.81799493, 10.49229402, 47.80846475]
    results = search("snow data", limit=10, bbox=alps_bbox)
    ids = [r.id for r in results]
    assert "binary-wet-snow-s14science-snow" in ids

    # Test that containment differs from intersects
    results_containment = search(
        "snow data", limit=10, bbox=alps_bbox, intersects=False
    )
    ids_containment = [r.id for r in results_containment]
    assert len(ids_containment) > 0
    assert "binary-wet-snow-s14science-snow" not in ids_containment

def test_variable_search_returns_results():
    results = search("chlorophyll", type="variables", limit=2)
    assert len(results) > 0
