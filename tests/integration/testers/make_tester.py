# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import os
import stat
import tempfile
from os import mkdir
from pathlib import Path
from shutil import copy
from subprocess import Popen

import yaml


def build_tester_charm(source: str) -> str:
    testers_folder = Path(__file__).parent
    source_file = (testers_folder / (source + ".py")).absolute()
    meta_file = (testers_folder / (source + "_meta" + ".yaml")).absolute()
    charmcraft_file = (testers_folder / "charmcraft.yaml").absolute()

    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir).absolute()
        mkdir(tempdir / "src")

        charm_py = tempdir / "src" / "charm.py"
        copy(source_file, charm_py)
        # chmod +x
        st = os.stat(charm_py)
        os.chmod(charm_py, st.st_mode | stat.S_IEXEC)

        meta_clone = tempdir / "metadata.yaml"
        copy(meta_file, meta_clone)

        # add required fields to metadata file:
        data = yaml.safe_load(meta_clone.read_text())
        for field in {'description', 'summary', 'display-name'}:
            if field not in data:
                data[field] = 'tester'
        meta_clone.write_text(yaml.safe_dump(data))

        copy(charmcraft_file, tempdir / "charmcraft.yaml")

        proc = Popen("charmcraft pack".split(" "), cwd=tempdir)
        proc.wait()
        charm_path = next(tempdir.glob("*.charm"))
        charm_out = testers_folder / charm_path.name
        copy(charm_path, charm_out)

    return str(charm_out.absolute())


if __name__ == "__main__":
    print(build_tester_charm("ipa"))
