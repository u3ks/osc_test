from zipfile import ZipFile
from collections import defaultdict
import requests
from io import BytesIO

from fsspec.asyn import AsyncFileSystem
import asyncio
import posixpath
from typing import List, Optional
import fsspec
import zarr
import xarray as xr
import pandas as pd



import pystac
from pystac.extensions.scientific import ScientificExtension, FileExtension
from datetime import datetime

def create_compliant_collection(
    product_collection: pystac.Collection, 
    project_collection: pystac.Collection,
    contract_number: str
) -> pystac.Collection:
    """
    Merges a Product and Project STAC collection into a new Collection 
    adhering to the specific OSC/EarthCODE requirements.
    """
    
    # 1. Basic STAC attributes
    new_id = product_collection.id
    new_title = product_collection.title
    new_description = product_collection.description
    new_license = product_collection.license
    
    # Extents are taken from the product
    new_extent = product_collection.extent
    
    # Keywords
    new_keywords = product_collection.keywords or []

    # 2. Create the new Collection Object
    new_coll = pystac.Collection(
        id=new_id,
        title=new_title,
        description=new_description,
        extent=new_extent,
        license=new_license,
        keywords=new_keywords,
        stac_extensions=[] # We will populate this explicitly below
    )
    
    # 3. Mandatory STAC Extensions
    required_extensions = [
        "https://stac-extensions.github.io/osc/v1.0.0/schema.json",
        "https://stac-extensions.github.io/scientific/v1.0.0/schema.json",
        "https://stac-extensions.github.io/processing/v1.2.0/schema.json",
        "https://stac-extensions.github.io/themes/v1.0.0/schema.json",
        "https://stac-extensions.github.io/cf/v1.0.0/schema.json"
    ]
    new_coll.stac_extensions = required_extensions

    # 4. Map 'Extra Fields'  or custom Metadata)
    proc_dt = product_collection.extra_fields.get("created")
    if proc_dt:
        new_coll.extra_fields["processing:datetime"] = proc_dt
    # Region
    if "osc:region" in product_collection.extra_fields:
        new_coll.extra_fields["osc:region"] = product_collection.extra_fields["osc:region"]
    
    # --- OSC Extension Fields ---
    new_coll.extra_fields["osc:project"] = project_collection.id
    new_coll.extra_fields["osc:project_description"] = project_collection.description
    # (Required: 'apex' or 'earthcode') - Defaulting to EarthCODE
    new_coll.extra_fields["osc:initiative"] = "earthcode"
    # Variables & Missions
    if "osc:variables" in product_collection.extra_fields:
        new_coll.extra_fields["osc:variables"] = product_collection.extra_fields["osc:variables"]
        
    if "osc:missions" in product_collection.extra_fields:
        new_coll.extra_fields["osc:missions"] = product_collection.extra_fields["osc:missions"]
    themes = product_collection.extra_fields.get("themes") or project_collection.extra_fields.get("themes")
    if themes:
        new_coll.extra_fields["themes"] = themes

    # Project Website (Required)
    # Attempt to find a link in project or default to a placeholder
    # In the input JSON, links are empty, so we look for a placeholder or extract from description
    website = "https://placeholder-project-website.com" 
    # (Optional logic: extract URL from description text if needed)
    new_coll.extra_fields["osc:project_website"] = website

    # Contract Number (Required)
    new_coll.extra_fields["osc:contract-number"] = contract_number
        
    # --- Scientific Extension ---
    # DOI
    if "sci:doi" in product_collection.extra_fields:
        new_coll.extra_fields["sci:doi"] = product_collection.extra_fields["sci:doi"]        
        new_coll.extra_fields["sci:citation"] = f"{new_title}. {new_coll.extra_fields.get('sci:doi', '')}"

    # --- CF Extension ---
    if "cf:parameter" in product_collection.extra_fields:
        new_coll.extra_fields["cf:parameter"] = product_collection.extra_fields["cf:parameter"]

    return new_coll


def add_assets(prr_collection):
    pass



def transform_item_to_spec(item: pystac.Item) -> pystac.Item:
    """
    Transforms a STAC Item to meet the new Project specification.
    
    Key changes:
    1. Ensures 'datetime' is populated (falls back to start_datetime).
    2. Adds the 'File' STAC extension.
    3. Enforces 'file:size' on all assets (sets a placeholder if unknown).
    """
    
    # 1. Create a clone to avoid mutating the original object
    new_item = item.clone()
    
    # 2. Update STAC Version (Recommended 1.0.0)
    # Note: Pystac handles versioning internally, but we set the explicit structure if exporting to dict
    # We leave it as is or allow Pystac to default to supported version.
    
    # 3. Handle Datetime (Spec: If null, set to start_datetime)
    if new_item.datetime is None:
        # Pystac stores start/end in common_metadata or extra_fields
        start_dt = new_item.common_metadata.start_datetime
        if start_dt:
            new_item.datetime = start_dt
    
    # 4. Mandatory Extensions
    # The spec requires the File extension.
    file_schema_uri = "https://stac-extensions.github.io/file/v2.1.0/schema.json"
    if file_schema_uri not in new_item.stac_extensions:
        new_item.stac_extensions.append(file_schema_uri)

    # 5. Process Assets (File Extension & Roles)
    for asset_key, asset in new_item.assets.items():
        # A. Ensure 'roles' exists (Spec: REQUIRED)
        if not asset.roles:
            # Default to 'data' if ambiguous, as per spec requirement for at least one data/doc
            asset.roles = ["data"]

        # B. Handle File Extension properties
        # We use the pystac FileExtension helper to manage fields safely
        file_ext = FileExtension.ext(asset, add_if_missing=True)
        
        # Spec: file:size is REQUIRED. 
        # Since we cannot measure a remote Zarr file's size in a metadata script without downloading it,
        # we check if it exists. If not, we set a placeholder.
        if file_ext.size is None:
            # PLACEHOLDER: You must replace 0 with the actual size in bytes if known.
            # For Zarr (directories), this is often the sum of all chunk sizes.
            file_ext.size = 0 
            
        # Optional: file:checksum is recommended but not required. 
        # We leave it empty if not present.

    return new_item


def build_zip_info(zf: ZipFile, content_size, original_file_size):
    info_dict = {}
    children = defaultdict(list)

    # Collect file info
    for info in zf.infolist():
        name = info.filename.rstrip('/')
        # Skip directories for now; we'll handle them after
        if not name:
            continue

        # File entry
        info_dict[name] = {
            "size": info.file_size,
            # 30 is fixed, then len(name), then the length of the file because its not the full zip
            "offset": (content_size + 30 - original_file_size) + info.header_offset  + len(name)  
        }
        # Build parent-child relationships
        if '/' in name:
            parent = name.rsplit('/', 1)[0]
        else:
            parent = ''
        children[parent].append(name)

    # Add directory entries
    for parent, child_list in children.items():
        info_dict.setdefault(parent, {})["children"] = child_list

    return info_dict


# the _cat methods are from https://github.com/zarr-developers/zarr-python/discussions/1613
# I replaced the whole zip mapping logic with a more straightfoward herustic - just get a mb from the end of the zip
# The original did not work with normal zips, like the PRR examples, and has some issues with directories in the zip
# doesnt work with compressed zips.
# the code is limited though, it doesnt work with zenodo, for examplem, because the zarr is actually inside another folder and the .zarrattr is not at the root.
class ReadOnlyZipFileSystem(AsyncFileSystem):   

    def __init__(self, fs: AsyncFileSystem, path: str, end_mb:int=1024*1024, **kwargs):
        """Initialize the ReadOnlyZipFileSystem.

        Args:
            fs: The underlying AsyncFileSystem containing the zip file.
            path: Path to the zip file in the underlying file system.
            **kwargs: Additional arguments passed to AsyncFileSystem.
        """
        super().__init__(**kwargs)
        self.asynchronous = True
        self.fs = fs
        self.path = path
        self._files = None
        self._lock = asyncio.Lock()
        
        # initialise the zip paths manually
        r = requests.get(path, headers={"Range": f"bytes=-{end_mb}"})
        r.raise_for_status()
        
        # read the file locations
        tail = r.content
        
        # get the full content size
        content_size = int(r.headers['Content-Range'].split('/')[-1])
        
        # extract the files structure
        with ZipFile(BytesIO(tail), mode='r') as zf:
            self._files = build_zip_info(zf, content_size, len(tail))


    async def _cat_file(self, path: str, start: Optional[int] = None, end: Optional[int] = None, **kwargs) -> bytes:
        """Read the contents of a file in the zip."""

        # Internally we don't use a root slash, so strip it. Also strip any trailing slash.
        path = posixpath.normpath(path).lstrip('/').rstrip('/')

        # Check if the file is available
        if path not in self._files:
            raise FileNotFoundError(f"File {path} not found")
        elif 'children' in self._files[path]:
            raise FileNotFoundError(f"{path} is a directory")
        
        # Get offset and size of the file in the zip file
        info = self._files[path]
        offset = info['offset']
        size = info['size']

        # Set start to beginning of file if not specified
        start = start or 0

        # Convert negative start (relative to end of file) to positive start
        if start < 0:
            start = max(0, size + start)  # Clamp too large negative start to the beginning of file

        # Set end to end of file if not specified
        end = end or size

        # Convert negative start (relative to end of file) to positive start
        if end < 0:
            end = max(0, size + end)  # Clamp too large negative start to the beginning of file

        # For start beyond the end of the file or the end, return empty data
        if start >= size or end <= start:
            return b''

        # Calculate zip file read start and read size
        read_start = offset + start
        read_size = min(end, size) - start  # Clamp too large end at size

        # Read data
        data = await self.fs._cat_file(self.path, start=read_start, end=read_start+read_size)
        return data
    

def load_zipzarr(url, end_mb, path='',**kwargs):
    fs = fsspec.filesystem('http', asynchronous=True)
    zipfs = ReadOnlyZipFileSystem(fs, url, end_mb)
    zarr_store = zarr.storage.FsspecStore(fs=zipfs, read_only=True, path=path)
    return xr.open_zarr(zarr_store, **kwargs)


