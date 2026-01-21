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