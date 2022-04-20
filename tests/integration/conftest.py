#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import grp
import os
import shutil
from os import unlink
from pathlib import Path
from subprocess import Popen

import pytest
import websockets
from pytest_operator.plugin import OpsTest, check_deps

ROOT = Path(os.getcwd())
TRAEFIK_CHARM = ROOT / "traefik-k8s_ubuntu-20.04-amd64.charm"
REQUIRER_MOCK_DIR = ROOT / "tests" / "integration" / "ingress-requirer-mock"
REQUIRER_MOCK_CHARM = REQUIRER_MOCK_DIR / "ingress-requirer-mock_ubuntu-20.04-amd64.charm"


def copy_libs_to_tester_charm():
    install_paths = []
    for lib in ("ingress_per_unit", "ingress"):
        library_path = f"lib/charms/traefik_k8s/v0/{lib}.py"
        install_path = f"tests/integration/ingress-requirer-mock/{library_path}"
        install_paths.append(install_path)
        shutil.copyfile(library_path, install_path)
        print(f"copied {lib}.py lib --> {install_path}")

    return install_paths


def cleanup_libs(install_paths):
    for install_path in install_paths:
        unlink(install_path)


def build_charm_cmd(destructive_mode=False):
    # copied over from OpsTest.plugin
    if destructive_mode:
        # host builder never requires lxd group
        cmd = ["charmcraft", "pack", "--destructive-mode"]
    elif "lxd" in {grp.getgrgid(g).gr_name for g in os.getgroups()}:
        # user already has lxd group active
        cmd = ["charmcraft", "pack"]
    else:
        # building with lxd builder and user doesn't already have lxd group;
        # make sure it's available and if so, try using `sg` to acquire it
        assert "lxd" in {g.gr_name for g in grp.getgrall()}, (
            "Group 'lxd' required but not available; "
            "ensure that lxd is available or use --destructive-mode"
        )
        cmd = ["sg", "lxd", "-c", "charmcraft pack"]
    return cmd


def build_charm_at(root: Path, expected_charm: Path):
    """Temporarily set cwd to root and run 'charmcraft pack' there.

    Also verify that the expected charm file is there.
    """
    previous_cwd = os.getcwd()
    os.chdir(root)

    Popen(build_charm_cmd()).wait()

    os.chdir(previous_cwd)

    assert expected_charm.exists(), f"unsuccessful build: {expected_charm} not found"


# get around ops_test being a module-scoped fixture, allowing us to build
# only once all of our charms while having separate test modules.
@pytest.fixture(autouse=True, scope="session")
@pytest.mark.abort_on_fail
def build_charms():
    libs = copy_libs_to_tester_charm()
    print("packing traefik...")
    build_charm_at(os.getcwd(), TRAEFIK_CHARM)
    print("packing requirer mock...")
    build_charm_at(REQUIRER_MOCK_DIR, REQUIRER_MOCK_CHARM)
    print("done packing charms...")
    cleanup_libs(libs)

    yield

    # cleanup and remove charms
    print("cleaning up charms...")
    unlink(TRAEFIK_CHARM)
    unlink(REQUIRER_MOCK_CHARM)


@pytest.fixture(scope="module")
@pytest.mark.asyncio
async def ops_test(request, tmp_path_factory):
    check_deps("juju", "charmcraft")
    pytest_ops_test = OpsTest(request, tmp_path_factory)
    await pytest_ops_test._setup_model()
    OpsTest._instance = pytest_ops_test
    print("OpsTest ready...")
    yield pytest_ops_test
    print("OpsTest cleaning up...")
    OpsTest._instance = None

    # FIXME: this is necessary because (for some reason) OpsTest raises.
    #  cf: https://github.com/charmed-kubernetes/pytest-operator/issues/71
    try:
        await pytest_ops_test._cleanup_model()
    except (websockets.exceptions.ConnectionClosed, OSError) as e:
        print(f"ignored {e}")
