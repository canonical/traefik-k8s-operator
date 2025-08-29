# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import logging
import os
import shutil
from datetime import datetime
from hashlib import md5
from pathlib import Path
from subprocess import CalledProcessError, check_output, getoutput
from typing import List, Union

import yaml

charm_cache = Path(__file__).parent / "cache"
charm_shelf = Path(__file__).parent / "shelf"

COPY_TAG = "unfrozen"  # tag for charm copies
USE_CACHE = os.getenv("SPELLBOOK_CACHE", "1") == "1"
if USE_CACHE:
    logging.warning(
        "USE_CACHE:: charms will be packed once and stored in "
        "./tests/integration/charms. Clear them manually if you "
        "have made changes to the charm code."
        "Set the environment var SPELLBOOK_CACHE=0 to disable caching."
    )


def _get_charm_name(metadata: Path):
    if not metadata.exists() or not metadata.is_file():
        raise RuntimeError(f"invalid charm metadata file: {metadata}")
    meta = yaml.safe_load(metadata.read_text())
    if "name" not in meta:
        raise RuntimeError("unable to fetch charm name from metadata")
    return meta["name"]


def _get_libpath(base, source):
    root = Path(base)
    for part in source.parent.parts[-4:]:
        root /= part
    return root.absolute()


def spellbook_fetch(  # noqa: C901
    charm_root: Union[str, Path] = "./",
    charm_name: str = None,
    hash_paths: List[Path] = None,
    pull_libs: List[Path] = None,
    use_cache=USE_CACHE,
    cache_dir=charm_cache,
    shelf_dir=charm_shelf,
):
    """Cache for charmcraft pack.

    Params::
        :param charm_root: Charm tree root.
        :param charm_name: Name of the charm. If not given, will default to whatever
            charm_root/metadata.yaml says.
        :param hash_paths: Specific directories or files to base the hashing on.
            Defaults to 'charm_root/'.
        :param pull_libs: Path to local charm lib files to include in the package.
        :param use_cache: Flag to disable caching entirely.
        :param cache_dir: Directory in which to store the cached charm files. Defaults to ./cache
        :param shelf_dir: Directory in which to store the copies of the cached charm files
            whose paths are returned by this function. Defaults to ./shelf
    """
    # caching or not, we need to ensure the libs the charm depends on are up-to-date.
    if pull_libs:
        for lib in pull_libs:
            lib_source = Path(lib)
            lib_path = _get_libpath(charm_root, lib_source)
            # ensure it exists
            lib_path.mkdir(parents=True, exist_ok=True)
            shutil.copy(lib_source, lib_path)
            logging.info(f"copying {lib_source} -> {lib_path}")

    def do_build():
        logging.info(f"building {charm_root}")
        try:
            pack_out = check_output(("charmcraft", "pack", "--format=json", "-p", str(charm_root)))
        except CalledProcessError as e:
            raise RuntimeError(
                "Charmcraft pack failed. Attempt a `charmcraft clean` or inspect the logs."
            ) from e
        # if everything went OK, `charmcraft pack` returns the packed charm filename
        try:
            charmcraft_pack_out = json.loads(pack_out.decode("utf-8"))
            charm_filename = charmcraft_pack_out["charms"][0]
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            raise RuntimeError(
                (
                    "Could not determine path to packed charm file from charmcraft pack output:"
                    f" {pack_out!r}"
                )
            ) from e

        packed_charm_path = (Path(os.getcwd()) / charm_filename).absolute()
        if not packed_charm_path.exists():
            raise RuntimeError(
                (
                    "Could not determine path to packed charm file from charmcraft pack output:"
                    f" {pack_out!r}"
                )
            )
        return packed_charm_path

    if not use_cache:
        logging.info("Caching disabled. Set the environment var SPELLBOOK_CACHE=1 to enable it.")
        return do_build()

    # ensure cache dirs exist
    cache_dir.mkdir(parents=True, exist_ok=True)
    shelf_dir.mkdir(parents=True, exist_ok=True)

    logging.info(f"hashing {charm_root}")

    # todo check that if a hash path does not exist we don't blow up
    hash_path = charm_root if not hash_paths else " ".join(map(str, hash_paths))
    root_md5 = getoutput(f'find {hash_path} -type f -exec md5sum "{{}}" +')
    # builtins.hash() is unpredictable on str
    charm_tree_sum = md5(root_md5.encode("utf-8")).hexdigest()

    logging.info(f"hash: {charm_tree_sum}")

    charm_tag = charm_name or _get_charm_name(charm_root / "metadata.yaml")

    cached_charm_path = cache_dir / f"{charm_tag}.{charm_tree_sum}.charm"

    # in case someone deletes it after deploy, we make a copy and keep it in the shelf
    shelved_charm_copy = (shelf_dir / f"{charm_tag}.{COPY_TAG}.charm").absolute()

    # clear any dirty cache
    dirty_cache_found = False
    for fname in cache_dir.glob(f"{charm_tag}.*"):
        if fname.name.startswith(f"{charm_tag}.{COPY_TAG}."):
            continue
        if fname != cached_charm_path:
            dirty_cache_found = True
            logging.info(f"deleting dirty cache: {fname}")
            fname.unlink()

    if cached_charm_path.exists():
        tstamp = datetime.fromtimestamp(os.path.getmtime(cached_charm_path))
        logging.info(f"Found cached charm {charm_tag} timestamp={tstamp}.")
        shutil.copyfile(cached_charm_path, shelved_charm_copy)
        return shelved_charm_copy

    if dirty_cache_found:
        logging.info(f"Cache for {charm_tag} is dirty. Repacking...")
    else:
        logging.info(f"Cache not found for charm {charm_tag}. Packing...")

    charm = do_build()
    shutil.copyfile(charm, cached_charm_path)
    shutil.copyfile(charm, shelved_charm_copy)
    charm.unlink()
    return shelved_charm_copy
