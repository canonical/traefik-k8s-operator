# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
import shutil
from datetime import datetime
from hashlib import md5
from pathlib import Path
from subprocess import getoutput
from typing import List, Union

charm_cache = Path(__file__).parent

USE_CACHE = True  # you can flip this to true when testing locally. Do not commit!
if USE_CACHE:
    logging.warning(
        "USE_CACHE:: charms will be packed once and stored in "
        "./tests/integration/charms. Clear them manually if you "
        "have made changes to the charm code."
    )


def build_charm_or_fetch_cached(
    charm_name: str,
    build_root: Union[str, Path],
    pull_libs: List[Path] = None,
    use_cache=USE_CACHE,
):
    # caching or not, we need to ensure the libs the charm depends on are up to date.

    if pull_libs:
        for lib in pull_libs:
            lib_source = Path(lib)
            lib_path = build_root

            for part in lib_source.parent.parts[:-5:-1]:
                lib_path /= part

            lib_path = lib_path.absolute()
            # ensure it exists
            lib_path.mkdir(parents=True, exist_ok=True)
            shutil.copy(lib_source, lib_path)
            logging.info(f"copying {lib_source} -> {lib_path}")

    def do_build():
        pack_out = getoutput(f"charmcraft pack -p {build_root}")
        return (Path(os.getcwd()) / pack_out.split("\n")[-1].strip()).absolute()

    if not use_cache:
        logging.info("not using cache")
        return do_build()

    logging.info(f"hashing {build_root}")
    root_md5 = getoutput(f'find {build_root} -type f -exec md5sum "{{}}" +')
    # builtins.hash() is unpredictable on str
    charm_tree_sum = md5(root_md5.encode("utf-8")).hexdigest()

    logging.info(f"hash: {charm_tree_sum}")

    cached_charm_path = charm_cache / f"{charm_name}.{charm_tree_sum}.charm"
    # in case someone deletes it after deploy, we make a copy.
    charm_copy = (charm_cache / f"{charm_name}.unfrozen.charm").absolute()

    # clear any dirty cache
    dirty_cache_found = False
    for fname in charm_cache.glob(f"{charm_name}.*"):
        if fname != cached_charm_path:
            dirty_cache_found = True
            logging.info(f"deleting dirty cache: {fname}")
            fname.unlink()

    if cached_charm_path.exists():
        tstamp = datetime.fromtimestamp(os.path.getmtime(cached_charm_path))
        logging.info(f"Found cached charm {charm_name} timestamp={tstamp}.")
        shutil.copyfile(cached_charm_path, charm_copy)
        return charm_copy

    if dirty_cache_found:
        logging.info(f"Cache for {charm_name} is dirty. Repacking...")
    else:
        logging.info(f"Cache not found for charm {charm_name}. Packing...")

    charm = do_build()
    shutil.copyfile(charm, cached_charm_path)
    shutil.copyfile(charm, charm_copy)
    return charm_copy
