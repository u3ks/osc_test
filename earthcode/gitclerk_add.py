from __future__ import annotations

import base64
import json
import webbrowser
from pathlib import Path
from typing import Optional, Union
from urllib.parse import quote

from pystac import Collection

# from .models import ProductMetadata
from .metadata.models import MetadataBundle, ProductMetadata


class Publisher:
    """
    Persists generated metadata into a local OSC-style repository.
    """

    def __init__(self, local_repo: Union[str, Path]) -> None:
        self.local_repo = Path(local_repo)

    def write(self, bundle: MetadataBundle) -> None:
        bundle.save_to_repo(self.local_repo)


def publish(
    bundle: Union[MetadataBundle, ProductMetadata, Collection],
    *,
    repo: Optional[Union[str, Path]] = None,
) -> None:
    """
    Convenience wrapper to persist a bundle using the provided repo path.
    """
    # if repo is None:
    #     raise ValueError("A target repo path must be provided to publish metadata.")
    # Publisher(repo).write(bundle)
    # return bundle
    if isinstance(bundle, ProductMetadata):
        # remove items from collection to make it osc friendly
        product_collection = bundle.collection.clone()
        product_collection.clear_items()
        session_title = quote(product_collection.title, safe="")
        # product_collection to json
        json_product = product_collection.to_dict()
        # Use URL-safe base64 encoding (replaces + with - and / with _)
        base64_content = base64.urlsafe_b64encode(json.dumps(json_product).encode("utf-8")).decode("utf-8")
        url = f"https://workspace.earthcode-staging.earthcode.eox.at/osc-editor?session={session_title}&automation=add-file&&type=product&file={base64_content}"
        print("To publish your product metadata, open the following URL in your browser:")
        print(url)
        # https://workspace.earthcode-staging.earthcode.eox.at/osc-editor?session=<your session title, e.g. "Add File">&automation=add-file&type=<osc type, e.g. "product">&file=<base64encoded content>
        # opens default web browser
        webbrowser.open(url)

    elif isinstance(bundle, Collection):
        raise NotImplementedError("Publishing Pystac Collections directly is not yet supported.")
    elif isinstance(bundle, MetadataBundle):
        raise NotImplementedError("Publishing MetadataBundle directly is not yet supported.")