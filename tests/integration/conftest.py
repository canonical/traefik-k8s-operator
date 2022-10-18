# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import functools
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from subprocess import PIPE, Popen

import pytest
import yaml
from pytest_operator.plugin import OpsTest

charm_root = Path(__file__).parent.parent.parent
trfk_meta = yaml.safe_load((charm_root / "metadata.yaml").read_text())
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


@pytest.fixture(scope="module")
@timed_memoizer
async def traefik_charm(ops_test: OpsTest):
    charm = await ops_test.build_charm(".")
    return charm


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

    proc = Popen(cmd, stdout=PIPE)
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
    application_data: dict
    unit_data: dict


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


def assert_can_ping(ip, port):
    response = os.system(f"ping -c 1 {ip} -p {port}")
    assert response == 0, f"{ip}:{port} is down/unreachable"


async def get_address(ops_test: OpsTest, app_name: str, unit=0):
    status = await ops_test.model.get_status()  # noqa: F821
    addr = list(status.applications[app_name].units.values())[unit].address
    return addr


async def deploy_traefik_if_not_deployed(ops_test: OpsTest, traefik_charm):
    if not ops_test.model.applications.get("traefik-k8s"):
        await ops_test.model.deploy(
            traefik_charm, application_name="traefik-k8s", resources=trfk_resources, series="focal"
        )
        # if we're running this locally, we need to wait for "waiting"
        # CI however deploys all in a single model, so traefik is active already
        # if a previous test has already set it up.
        wait_for = "waiting"
    else:
        wait_for = "active"

    # block until traefik goes to...
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s"], status=wait_for, timeout=1000)

    # we set the external hostname to traefik-k8s's own ip
    traefik_address = await get_address(ops_test, "traefik-k8s")
    await ops_test.model.applications["traefik-k8s"].set_config(
        {"external_hostname": traefik_address}
    )

    # now we're most definitely active.
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(["traefik-k8s"], status="active", timeout=1000)


async def deploy_charm_if_not_deployed(ops_test: OpsTest, charm, app_name: str, resources=None):
    if not ops_test.model.applications.get(app_name):
        await ops_test.model.deploy(
            charm, resources=resources, application_name=app_name, series="focal"
        )

    # block until app goes to active/idle
    async with ops_test.fast_forward():
        # if we're running this locally, we need to wait for "waiting"
        # CI however deploys all in a single model, so traefik is active already.
        await ops_test.model.wait_for_idle([app_name], status="active", timeout=1000)
