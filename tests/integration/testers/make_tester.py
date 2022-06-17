# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import tempfile
from os import mkdir
from pathlib import Path
from shutil import copy
from subprocess import Popen


def build_tester_charm(source: str) -> str:
    testers_folder = Path(__file__).parent
    source_file = (testers_folder / (source + ".py")).absolute()
    meta_file = (testers_folder / (source + "_meta" + ".yaml")).absolute()
    charmcraft_file = (testers_folder / "charmcraft.yaml").absolute()

    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir).absolute()
        mkdir(tempdir / "src")
        copy(source_file, tempdir / "src" / "charm.py")
        copy(meta_file, tempdir / "metadata.yaml")
        copy(charmcraft_file, tempdir / "charmcraft.yaml")

        proc = Popen("charmcraft pack".split(" "), cwd=tempdir)
        proc.wait()
        charm_path = next(tempdir.glob("*.charm"))
        charm = testers_folder / charm_path.name
        copy(charm_path, charm)

    return str(charm.absolute())


if __name__ == "__main__":
    build_tester_charm("ipa")
