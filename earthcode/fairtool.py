#!/usr/bin/env python3
"""
STAC Link Auditor

- Loads a STAC catalog and inspects product links
- Validates link responsiveness (HTTP HEAD)
- Checks whether links live on approved domains
- Samples assets from product children and attempts to open them
  using appropriate readers (xarray/rioxarray/zipfile/etc.)


"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys

import fnmatch
from urllib.parse import urlparse
import requests
import pystac

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from fsspec.implementations.http import HTTPFileSystem
from zarr.storage import ZipStore
from xarray import open_datatree
import rioxarray
import xarray
import geopandas as gpd
import pandas as pd
import zipfile
import csv


READERS = {
    # xarray
    "application/x-netcdf": xarray.open_dataset,
    "application/vnd+zarr": xarray.open_zarr,

    # rioxarray
    "image/tiff": rioxarray.open_rasterio,
    "image/cog": rioxarray.open_rasterio,  # Cloud Optimized GeoTIFF (COG)

    # Python standard libs
    "application/zip": zipfile.ZipFile,
    "application/pdf": open,   # placeholder, real PDF parsing needs pdfplumber/PyPDF2
    "text/plain": open,

    # pandas
    "text/csv": pd.read_csv,
    "application/vnd.apache.parquet": pd.read_parquet,

    # geopandas
    "application/x-shapefile": gpd.read_file,
    "application/vnd.apache.geoparquet": gpd.read_parquet,
    "application/geo+json": gpd.read_file,
}

APPROVED_DATA_HOSTING_DOMAINS = [
    "*.esa.int",
    "s3.waw4-1.cloudferro.com",
    "zenodo.org",
    "doi.org",
    "*.pangaea.de",
    "*.copernicus.eu",
    "*.ac.uk",
]

APPROVED_METADATA_HOSTING_DOMAINS = [
    "*.esa.int",
    "s3.waw4-1.cloudferro.com",
    "*.github.org",  # keep as provided; adjust if you meant github.com
]

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:140.0) Gecko/20100101 Firefox/140.0"



CLOUD_NATIVE_FORMATS = set([
    "application/vnd.apache.geoparquet",
    "image/cog",
    "application/vnd+zarr"
])

# ----------------------------- Data classes -----------------------------------

@dataclass(frozen=True)
class ProductLinkAnalysis:
    via: Dict[str, str]
    children_data: Dict[str, str]
    has_documentation: Dict[str, bool]
    has_workflow: Dict[str, bool]
    has_doi: Dict[str, bool]


# ----------------------------- Core logic -------------------------------------

def check_product_doi(product, timeout: int = 5) -> bool:
    """
    Check whether a STAC product item has a DOI (in the "sci:doi" field)
    and whether it resolves successfully via doi.org.

    Returns True if present and resolves (status 200), False otherwise.
    """
    try:
        product_dict = product.to_dict()
        doi_value = product_dict.get("sci:doi")
        if doi_value:
            doi_url = f"https://doi.org/{doi_value}"
            response = try_response(doi_url, timeout=timeout)
            return response.status_code == 200
    except Exception:
        return False
    return False

    

def analyse_product_links(products_catalog: pystac.Catalog) -> ProductLinkAnalysis:
    """
    Extracts selected links from each product (child) in the given products catalog.

    Returns:
        ProductLinkAnalysis with dicts keyed by product.id
    """
    via: Dict[str, str] = {}
    children_data: Dict[str, str] = {}
    has_doc: Dict[str, bool] = {}
    has_workflow: Dict[str, bool] = {}
    has_doi: Dict[str, bool] = {}

    for product in products_catalog.get_children():
        via_link = product.get_single_link("via")
        if via_link:
            via[product.id] = via_link.href

        child_link = product.get_single_link("child")
        if child_link:
            children_data[product.id] = child_link.href

        # scan for documentation + related(Experiment: ...)
        has_doc[product.id] = False
        has_workflow[product.id] = False
        for link in product.get_links():
            if getattr(link, "title", None) == "Documentation":
                has_doc[product.id] = True
            if link.rel == "related" and isinstance(link.title, str) and "Experiment: " in link.title:
                has_workflow[product.id] = True
        has_doi[product.id] = check_product_doi(product)

    return ProductLinkAnalysis(via, children_data, has_doc, has_workflow, has_doi)


def try_response(url: str, allow_redirects: bool = True, timeout: int = 5) -> requests.Response:
    """
    HEAD a URL (optionally retry with UA) and return the Response.
    Raises requests.RequestException on failure.
    TODO: Some DOIs do not resolve.
    """
    
    headers = {}
    resp = requests.head(url, allow_redirects=allow_redirects, timeout=timeout)
    if resp.status_code != 200:
        if _is_prr(url):
            resp = requests.get(url, headers=headers, allow_redirects=allow_redirects, timeout=timeout)
        else:
            headers = {"User-Agent": DEFAULT_USER_AGENT}
            resp = requests.head(url, headers=headers, allow_redirects=allow_redirects, timeout=timeout)
            
    return resp


def get_response_status(link_dict: Mapping[str, str], timeout: int = 5) -> Dict[str, bool]:
    """
    For each id->url, return True if HEAD returns 200 (on retry strategy), else False.
    """
    out: Dict[str, bool] = {}
    for id_, link in link_dict.items():
        try:
            out[id_] = try_response(link, timeout=timeout).status_code == 200
        except requests.RequestException:
            out[id_] = False
    return out


def approved_domains(link_dict: Mapping[str, str], approved_hosting_domains: Sequence[str]) -> Dict[str, bool]:
    """
    Check hostname of each link against wildcard domain allowlist patterns using fnmatch.
    """
    result: Dict[str, bool] = {}

    for id_, url in link_dict.items():
        hostname = urlparse(url).hostname or ""
        ok = False
        for pattern in approved_hosting_domains:
            if fnmatch.fnmatch(hostname, pattern):
                ok = True
                break
        result[id_] = ok

    return result


def _is_prr(link: str) -> bool:
    return "https://eoresults.esa.int" in link


def _is_creodias(link: str) -> bool:
    return "https://s3.waw4-1.cloudferro.com/" in link


def _load_zip_zarr(url: str, **kwargs):
    """
    Read a zipped Zarr over HTTP using fsspec + zarr + xarray.open_datatree.
    """

    class HttpZipStore(ZipStore):  # type: ignore
        def __init__(self, path) -> None:
            super().__init__(path="", mode="r")
            self.path = path

    fs = HTTPFileSystem(asynchronous=False, block_size=10000)  # type: ignore
    zf = fs.open(url)
    store = HttpZipStore(zf)
    return open_datatree(store, engine="zarr", **kwargs)


def get_resolve_href(feat, asset):
    
    if asset['href'][0] != '/':
            return asset['href']
    else:
        root_href = feat['links'][0]['href']
        scheme = root_href.index('//') + 2
        root_url = root_href[0: root_href[scheme:].index('/') + scheme]
        return root_url + asset['href']

def load_items_from_child_link(link: str) -> Tuple[bool, List[Tuple[str, Optional[str]]]]:
    """
    Given a product 'child' link to a catalog.json (or PRR endpoint), load items and
    return (is_prr, list_of_(asset_href, asset_type)) for assets with role ['data'].

    Falls back to type=None when absent; caller may assume types if desired.
    """
    prr = _is_prr(link)
    
    if prr:
        # PRR supports API /items?limit=...
        items = pystac.ItemCollection.from_file(link + "/items?limit=10000")
    else:
        items = pystac.ItemCollection(pystac.Catalog.from_file(link).get_all_items())
    
    items_dict = items.to_dict()
    out: List[Tuple[str, Optional[str]]] = []
    
    for feat in items_dict.get("features", []):
        assets = feat.get("assets", {})
        for _name, a in assets.items():
            if a.get("roles") == ["data"]:
                out.append((get_resolve_href(feat, a), a.get("type")))

    return prr, out


def sample_assets(
    assets: Sequence[Tuple[str, Optional[str]]],
    max_checks: int,
    seed: Optional[int] = None,
) -> List[Tuple[str, Optional[str]]]:
    """
    Deterministically (given seed) sample up to max_checks asset tuples.
    """
    if seed is not None:
        random.seed(seed)
    if len(assets) <= max_checks:
        return list(assets)
    return random.sample(list(assets), k=max_checks)


def check_asset_readable(
    href: str,
    mime_type: Optional[str],
    is_prr: bool,
) -> bool:
    """
    Attempts to open a single asset based on its MIME type using the reader map.

    - For PRR (eoresults.esa.int):
        - 'application/vnd+zarr': try _load_zip_zarr(href)
        - 'application/x-netcdf': try xarray.open_dataset(href + '#mode=bytes')
    - Otherwise:
        - For NetCDF, append '#mode=bytes' for streaming
        - For others, call the mapped reader directly.

    Returns True on success; False on any exception or if reader is unavailable.
    """
    mtype = mime_type or ""
    reader = READERS.get(mtype)

    try:
        test_href = href

        if is_prr:
            if not href.startswith("https://eoresults.esa.int/"):
                test_href = "https://eoresults.esa.int/" + href.lstrip("/")
            if mtype == "application/vnd+zarr":
                _load_zip_zarr(test_href)
                return True
            if mtype == "application/x-netcdf":
                xarray.open_dataset(test_href + "#mode=bytes")  # type: ignore
                return True
            # fallback for other types if a reader exists
            if reader:
                reader(test_href)  # type: ignore
                return True
            return False

        # non-PRR
        if mtype == "application/x-netcdf":
            test_href = href + "#mode=bytes"
        if reader is None:
            return False
        reader(test_href)  # type: ignore
        return True

    except Exception as e:  # pragma: no cover (I/O dependent)
        logging.debug("Asset read failed for %s (%s): %s", href, mtype, e)
        return False


def check_cloud_assets(product_assets):

    score = {}
    for product_id, adict in product_assets.items():
        
        cloud_native_format = [1 if asset['type'] in CLOUD_NATIVE_FORMATS else 0 for asset in adict['checked']]
        if len(cloud_native_format) == 0:
            score[product_id] = 0
        else:
            score[product_id] = sum(cloud_native_format) / len(cloud_native_format)
    return score

# ----------------------------- CLI orchestration ------------------------------

def run_audit(
    catalog_path: str,
    max_checks: int = 10,
    seed: Optional[int] = None,
    timeout: int = 5,
) -> Dict[str, object]:
    """
    High-level orchestration:
      1) Load catalog
      2) Extract products and analyse links
      3) HEAD-check access + child links
      4) Domain allowlist checks
      5) For each child link, sample up to max_checks data assets and attempt reads

    Returns a serializable dict summary.
    """
    catalog = pystac.Catalog.from_file(catalog_path)
    products = catalog.get_child("products")
    if products is None:
        raise ValueError("Catalog has no child named 'products'.")

    analysis = analyse_product_links(products)

    access_responses = get_response_status(analysis.via, timeout=timeout)
    child_responses = get_response_status(analysis.children_data, timeout=timeout)
    
    data_domain_ok = approved_domains(analysis.via, APPROVED_DATA_HOSTING_DOMAINS)
    meta_domain_ok = approved_domains(analysis.children_data, APPROVED_METADATA_HOSTING_DOMAINS)

    per_child_asset_checks: Dict[str, Dict[str, object]] = {}

    for pid, link in analysis.children_data.items():
        try:
            is_prr, assets = load_items_from_child_link(link)
        except Exception as e:  # pragma: no cover (I/O dependent)
            per_child_asset_checks[pid] = {
                "child_link": link,
                "error": f"Failed to load items: {e}",
                "checked": [],
                "success_flags": [],
            }
            continue

        # Default assumption from original notebook: assume NetCDF when missing
        assets_norm: List[Tuple[str, Optional[str]]] = [
            (href, mtype if mtype is not None else "application/x-netcdf")
            for (href, mtype) in assets
        ]

        subset = sample_assets(assets_norm, max_checks=max_checks, seed=seed)
        successes = [check_asset_readable(h, t, is_prr) for (h, t) in subset]

        per_child_asset_checks[pid] = {
            "child_link": link,
            "is_prr": is_prr,
            "checked": [{"href": h, "type": t} for (h, t) in subset],
            "success_flags": successes,
            "success_rate": (sum(successes) / len(successes)) if subset else None,
        }

    return {
        "summary": {
            "num_products_with_via": len(analysis.via),
            "num_products_with_child": len(analysis.children_data),
        },
        "access_ok": access_responses,
        "child_ok": child_responses,
        "data_domain_ok": data_domain_ok,
        "metadata_domain_ok": meta_domain_ok,
        "has_documentation": analysis.has_documentation,
        "has_workflow": analysis.has_workflow,
        "has_doi": analysis.has_doi,
        "per_child_asset_checks": per_child_asset_checks,
        "cloud_assets": check_cloud_assets(per_child_asset_checks),
    }

def save_report_to_csv(report: Dict[str, object], output_path: str) -> None:
    """
    Save the audit report into a CSV file.

    Each row corresponds to a product/child id.
    Columns include access checks, domain checks, and asset success flags.
    True/False values are written as 1/0.
    """
    fieldnames: List[str] = [
        "id",
        "access_ok",
        "child_ok",
        "has_doi",
        "data_domain_ok",
        "metadata_domain_ok",
        "has_documentation",
        "has_workflow",
        "asset_success_rate",
        "cloud_assets",
    ]

    rows = []

    all_ids = set(report["access_ok"].keys()) | set(report["child_ok"].keys()) | set(report["has_doi"].keys())
    all_ids |= set(report["data_domain_ok"].keys()) | set(report["metadata_domain_ok"].keys())
    all_ids |= set(report["has_documentation"].keys()) | set(report["has_workflow"].keys())
    all_ids |= set(report["per_child_asset_checks"].keys())

    for pid in sorted(all_ids):
        row = {
            "id": pid,
            "access_ok": int(report["access_ok"].get(pid, False)),
            "child_ok": int(report["child_ok"].get(pid, False)),
            "has_doi": int(report["has_doi"].get(pid, False)),
            "data_domain_ok": int(report["data_domain_ok"].get(pid, False)),
            "metadata_domain_ok": int(report["metadata_domain_ok"].get(pid, False)),
            "has_documentation": int(report["has_documentation"].get(pid, False)),
            "has_workflow": int(report["has_workflow"].get(pid, False)),
            "asset_success_rate": report["per_child_asset_checks"].get(pid, {}).get("success_rate"),
            "cloud_assets": report["cloud_assets"].get(pid, {}),
        }
        rows.append(row)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    

def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Audit STAC product links and asset readability.")
    p.add_argument(
        "--catalog",
        required=True,
        help="Path/URL to root STAC catalog.json (expects a child named 'products').",
    )
    p.add_argument("--max-checks", type=int, default=10, help="Max assets to sample per child.")
    p.add_argument("--seed", type=int, default=123, help="Random seed for sampling.")
    p.add_argument("--timeout", type=int, default=5, help="HTTP HEAD timeout in seconds.")
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging verbosity.",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))

    try:
        report = run_audit(
            catalog_path=args.catalog,
            max_checks=args.max_checks,
            seed=args.seed,
            timeout=args.timeout,
        )
    except Exception as e:
        logging.error("Audit failed: %s", e)
        return 1

    save_report_to_csv(report, './report.csv')
    
    with open('report.json', 'w') as fp:
        json.dump(report, fp)


if __name__ == "__main__":
    sys.exit(main())
