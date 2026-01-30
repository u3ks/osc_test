"""Search interface for Lance vector store of Open Science Catalog items.

Provides semantic search across products, variables, missions, and projects using sentence transformer embeddings.

Returns:
    list[pystac.Collection | pystac.Catalog]: Search results as PySTAC objects.
"""

# todo:
# - consider using FastEmbed instead

import json
import lance
import numpy as np
import pystac
from sentence_transformers import SentenceTransformer

LANCE_URI = "s3://pangeo-test-fires/vector_store_v5/"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_ds = None
_model = None


def search(
    query=None,
    *,
    limit=10,
    bbox=None,
    intersects=True,
    collection_ids=None,
    type="products",
    lance_uri=LANCE_URI,
):
    # dataset / model caches
    global _ds, _model
    if _ds is None or getattr(_ds, "uri", None) != lance_uri.rstrip("/") + "/":
        _ds = lance.dataset(lance_uri.rstrip("/") + "/")
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)

    # build filter string
    parts = []
    parts.append(f"`group` = '{type}'")
    if collection_ids:
        if isinstance(collection_ids, str):
            collection_ids = [collection_ids]
        parts.append("id IN (" + ",".join(f"'{c}'" for c in collection_ids) + ")")

    if bbox and len(bbox) >= 4:
        minx, miny, maxx, maxy = bbox[:4]
        if intersects:
            parts.append(
                f"bbox_minx <= {maxx} AND bbox_maxx >= {minx} AND bbox_miny <= {maxy} AND bbox_maxy >= {miny}"
            )
        else:
            parts.append(
                f"bbox_minx >= {minx} AND bbox_maxx <= {maxx} AND bbox_miny >= {miny} AND bbox_maxy <= {maxy}"
            )

    filt = " AND ".join(parts) if parts else None

    cols = [
        "id",
        "group",
        "title",
        "description",
        "bbox_minx",
        "bbox_miny",
        "bbox_maxx",
        "bbox_maxy",
        "item_json",
    ]

    if query and query.strip():
        vec = _model.encode(
            [query],
            normalize_embeddings=False,
            convert_to_numpy=True,
            show_progress_bar=False,
        )[0]

        tbl = _ds.scanner(
            columns=cols,
            filter=filt,
            nearest={
                "column": "embedding",
                "q": np.asarray(vec, dtype=np.float32),
                "k": limit,
            },
            prefilter=True,
            limit=limit,
        ).to_table()

    else:
        tbl = _ds.to_table(columns=cols, filter=filt, limit=limit)

    results = []

    for row in tbl.to_pylist():
        item = json.loads(row["item_json"])
        results.append(
            pystac.Collection.from_dict(item)
            if item.get("type") == "Collection"
            else pystac.Catalog.from_dict(item)
        )
    return results


# if __name__ == "__main__":
#     for grp in ["products", "variables", "eo-missions", "projects"]:
#         print(grp, [c.title for c in search("forest fires", type=grp, limit=2)])
