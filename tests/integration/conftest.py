# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import functools
import logging
import os
import shutil
import socket
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict

import juju
import pytest
import yaml
from juju.errors import JujuError
from pytest_operator.plugin import OpsTest

trfk_root = Path(__file__).parent.parent.parent
trfk_meta = yaml.safe_load((trfk_root / "metadata.yaml").read_text())
trfk_resources = {name: val["upstream-source"] for name, val in trfk_meta["resources"].items()}

_JUJU_DATA_CACHE = {}
_JUJU_KEYS = ("egress-subnets", "ingress-address", "private-address")

logger = logging.getLogger(__name__)


class Store(defaultdict):
    def __init__(self):
        super(Store, self).__init__(Store)

    def __getattr__(self, key):
        """Override __getattr__ so dot syntax works on keys."""
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        """Override __setattr__ so dot syntax works on keys."""
        self[key] = value


store = Store()


def timed_memoizer(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fname = func.__qualname__
        logger.info("Started: %s" % fname)
        start_time = datetime.now()
        if fname in store.keys():
            ret = store[fname]
        else:
            logger.info("Return for {} not cached".format(fname))
            ret = await func(*args, **kwargs)
            store[fname] = ret
        logger.info("Finished: {} in: {} seconds".format(fname, datetime.now() - start_time))
        return ret

    return wrapper


@pytest.fixture(scope="module", autouse=True)
def copy_traefik_library_into_tester_charms(ops_test):
    """Ensure the tester charms have the requisite libraries."""
    libraries = [
        "traefik_k8s/v2/ingress.py",
        "traefik_k8s/v1/ingress_per_unit.py",
        "observability_libs/v1/kubernetes_service_patch.py",
        "traefik_route_k8s/v0/traefik_route.py",
    ]
    for tester in ["forward-auth", "ipa", "ipu", "tcp", "route"]:
        for lib in libraries:
            install_path = f"tests/integration/testers/{tester}/lib/charms/{lib}"
            os.makedirs(os.path.dirname(install_path), exist_ok=True)
            shutil.copyfile(f"lib/charms/{lib}", install_path)


@pytest.fixture(scope="module")
@timed_memoizer
async def traefik_charm(ops_test):
    count = 0
    while True:
        try:
            charm = await ops_test.build_charm(".", verbosity="debug")
            return charm
        except RuntimeError:
            logger.warning("Failed to build traefik. Trying again!")
            count += 1

            if count == 3:
                raise


@pytest.fixture(scope="module")
@timed_memoizer
async def forward_auth_tester_charm(ops_test):
    charm_path = (Path(__file__).parent / "testers" / "forward-auth").absolute()
    charm = await ops_test.build_charm(charm_path, verbosity="debug")
    return charm


@pytest.fixture(scope="module")
@timed_memoizer
async def ipa_tester_charm(ops_test):
    charm_path = (Path(__file__).parent / "testers" / "ipa").absolute()
    charm = await ops_test.build_charm(charm_path, verbosity="debug")
    return charm


@pytest.fixture(scope="module")
@timed_memoizer
async def ipu_tester_charm(ops_test):
    charm_path = (Path(__file__).parent / "testers" / "ipu").absolute()
    charm = await ops_test.build_charm(charm_path, verbosity="debug")
    return charm


@pytest.fixture(scope="module")
@timed_memoizer
async def tcp_tester_charm(ops_test):
    charm_path = (Path(__file__).parent / "testers" / "tcp").absolute()
    charm = await ops_test.build_charm(charm_path, verbosity="debug")
    return charm


@pytest.fixture(scope="module")
@timed_memoizer
async def route_tester_charm(ops_test):
    charm_path = (Path(__file__).parent / "testers" / "route").absolute()
    charm = await ops_test.build_charm(charm_path, verbosity="debug")
    return charm


@pytest.fixture(scope="module")
def temp_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("data")


def purge(data: dict):
    for key in _JUJU_KEYS:
        if key in data:
            del data[key]


def get_unit_info(unit_name: str, model: str = None) -> dict:
    """Returns unit-info data structure.

     for example:

    traefik-k8s/0:
      opened-ports: []
      charm: local:focal/traefik-k8s-1
      leader: true
      relation-info:
      - endpoint: ingress-per-unit
        related-endpoint: ingress
        application-data:
          _supported_versions: '- v1'
        related-units:
          prometheus-k8s/0:
            in-scope: true
            data:
              egress-subnets: 10.152.183.150/32
              ingress-address: 10.152.183.150
              private-address: 10.152.183.150
      provider-id: traefik-k8s-0
      address: 10.1.232.144
    """
    cmd = f"juju show-unit {unit_name}".split(" ")
    if model:
        cmd.insert(2, "-m")
        cmd.insert(3, model)

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    raw_data = proc.stdout.read().decode("utf-8").strip()

    data = yaml.safe_load(raw_data) if raw_data else None

    if not data:
        raise ValueError(
            f"no unit info could be grabbed for {unit_name}; "
            f"are you sure it's a valid unit name?"
            f"cmd={' '.join(proc.args)}"
        )

    if unit_name not in data:
        raise KeyError(unit_name, f"not in {data!r}")

    unit_data = data[unit_name]
    _JUJU_DATA_CACHE[unit_name] = unit_data
    return unit_data


def get_relation_by_endpoint(relations, local_endpoint, remote_endpoint, remote_obj):
    matches = [
        r
        for r in relations
        if (
            (r["endpoint"] == local_endpoint and r["related-endpoint"] == remote_endpoint)
            or (r["endpoint"] == remote_endpoint and r["related-endpoint"] == local_endpoint)
        )
        and remote_obj in r["related-units"]
    ]
    if not matches:
        raise ValueError(
            f"no matches found with endpoint=="
            f"{local_endpoint} "
            f"in {remote_obj} (matches={matches})"
        )
    if len(matches) > 1:
        raise ValueError(
            "multiple matches found with endpoint=="
            f"{local_endpoint} "
            f"in {remote_obj} (matches={matches})"
        )
    return matches[0]


@dataclass
class UnitRelationData:
    unit_name: str
    endpoint: str
    leader: bool
    application_data: Dict[str, str]
    unit_data: Dict[str, str]


def get_content(
    obj: str, other_obj, include_default_juju_keys: bool = False, model: str = None
) -> UnitRelationData:
    """Get the content of the databag of `obj`, as seen from `other_obj`."""
    unit_name, endpoint = obj.split(":")
    other_unit_name, other_endpoint = other_obj.split(":")

    unit_data, app_data, leader = get_databags(
        unit_name, endpoint, other_unit_name, other_endpoint, model
    )

    if not include_default_juju_keys:
        purge(unit_data)

    return UnitRelationData(unit_name, endpoint, leader, app_data, unit_data)


def get_databags(local_unit, local_endpoint, remote_unit, remote_endpoint, model):
    """Gets the databags of local unit and its leadership status.

    Given a remote unit and the remote endpoint name.
    """
    local_data = get_unit_info(local_unit, model)
    leader = local_data["leader"]

    data = get_unit_info(remote_unit, model)
    relation_info = data.get("relation-info")
    if not relation_info:
        raise RuntimeError(f"{remote_unit} has no relations")

    raw_data = get_relation_by_endpoint(relation_info, local_endpoint, remote_endpoint, local_unit)
    unit_data = raw_data["related-units"][local_unit]["data"]
    app_data = raw_data["application-data"]
    return unit_data, app_data, leader


@dataclass
class RelationData:
    provider: UnitRelationData
    requirer: UnitRelationData


def get_relation_data(
    *,
    provider_endpoint: str,
    requirer_endpoint: str,
    include_default_juju_keys: bool = False,
    model: str = None,
):
    """Get relation databags for a juju relation.

    >>> get_relation_data('prometheus/0:ingress', 'traefik/1:ingress-per-unit')
    """
    provider_data = get_content(
        provider_endpoint, requirer_endpoint, include_default_juju_keys, model
    )
    requirer_data = get_content(
        requirer_endpoint, provider_endpoint, include_default_juju_keys, model
    )
    return RelationData(provider=provider_data, requirer=requirer_data)


def _can_connect(ip, port) -> bool:
    target = (ip, int(port))
    logger.info("Attempting to connect %s", target)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(target)
        return True
    except:  # noqa: E722
        return False
    finally:
        s.close()


def assert_can_connect(ip, port):
    assert _can_connect(ip, port), f"{ip}:{port} is down/unreachable"


async def deploy_traefik_if_not_deployed(ops_test: OpsTest, traefik_charm):
    try:
        await ops_test.model.deploy(
            traefik_charm, application_name="traefik-k8s", resources=trfk_resources
        )
    except JujuError as e:
        if 'cannot add application "traefik-k8s": application already exists' not in str(e):
            raise e

    # now we're most definitely active.
    await ops_test.model.wait_for_idle(["traefik-k8s"], timeout=1000)


async def deploy_charm_if_not_deployed(ops_test: OpsTest, charm, app_name: str, resources=None):
    if not ops_test.model.applications.get(app_name):
        await ops_test.model.deploy(charm, resources=resources, application_name=app_name)

    # block until app goes to active/idle
    # if we're running this locally, we need to wait for "waiting"
    # CI however deploys all in a single model, so traefik is active already.
    await ops_test.model.wait_for_idle([app_name], status="active", timeout=1000)


async def safe_relate(ops_test: OpsTest, ep1, ep2):
    # in pytest-operator CI, we deploy all tests in the same model.
    # Therefore, it might be that by the time we run this module, the two endpoints
    # are already related.
    try:
        await ops_test.model.add_relation(ep1, ep2)
    except juju.errors.JujuAPIError as e:
        # relation already exists? skip
        logging.error(e)
        pass


@pytest.fixture(autouse=True, scope="module")
async def setup_env(ops_test: OpsTest):
    # Prevent "update-status" from interfering with the test:
    # - if fired "too quickly", traefik will flip between active/idle and maintenance;
    # - make sure charm code does not rely on update-status for correct operation.
    await ops_test.model.set_config(
        {"update-status-hook-interval": "60m", "logging-config": "<root>=WARNING; unit=DEBUG"}
    )
