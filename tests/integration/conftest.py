# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from dataclasses import dataclass
from pathlib import Path
from subprocess import PIPE, Popen
from time import sleep

import pytest
import yaml

_JUJU_DATA_CACHE = {}
_JUJU_KEYS = ("egress-subnets", "ingress-address", "private-address")


@pytest.fixture(autouse=True, scope="session")
@pytest.mark.abort_on_fail
def traefik_charm():
    proc = Popen(["charmcraft", "pack"], stdout=PIPE, stderr=PIPE)
    proc.wait()
    while proc.returncode is None:  # wait() does not quite wait
        print(proc.stdout.read().decode("utf-8"))
        sleep(1)
    if proc.returncode != 0:
        raise ValueError(
            "charmcraft pack failed with code: ",
            proc.returncode,
            proc.stderr.read().decode("utf-8"),
        )

    charms = tuple(map(str, Path().glob("*.charm")))
    assert len(charms) == 1, (
        f"too many charms {charms}" if charms else f"no charm found at {Path().absolute()}"
    )

    charm = charms[0]
    charm_path = Path(charm).absolute()

    assert charm_path.exists()

    yield charm_path

    Popen(["rm", str(charm_path)]).wait()


def purge(data: dict):
    for key in _JUJU_KEYS:
        if key in data:
            del data[key]


def get_unit_info(unit_name: str) -> dict:
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
    # if cached_data := _JUJU_DATA_CACHE.get(unit_name):
    #     return cached_data

    proc = Popen(f"juju show-unit {unit_name}".split(" "), stdout=PIPE)
    raw_data = proc.stdout.read().decode("utf-8").strip()
    if not raw_data:
        raise ValueError(
            f"no unit info could be grabbed for {unit_name}; "
            f"are you sure it's a valid unit name?"
        )

    data = yaml.safe_load(raw_data)
    if unit_name not in data:
        raise KeyError(unit_name, f"not in {data!r}")

    unit_data = data[unit_name]
    _JUJU_DATA_CACHE[unit_name] = unit_data
    return unit_data


def get_relation_by_endpoint(relations, endpoint, remote_obj):
    relations = [
        r for r in relations if r["endpoint"] == endpoint and remote_obj in r["related-units"]
    ]
    if not relations:
        raise ValueError(
            f"no relations found with endpoint=="
            f"{endpoint} "
            f"in {remote_obj} (relations={relations})"
        )
    if len(relations) > 1:
        raise ValueError(
            "multiple relations found with endpoint=="
            f"{endpoint} "
            f"in {remote_obj} (relations={relations})"
        )
    return relations[0]


@dataclass
class UnitRelationData:
    unit_name: str
    endpoint: str
    leader: bool
    application_data: dict
    unit_data: dict


def get_content(obj: str, other_obj, include_default_juju_keys: bool = False) -> UnitRelationData:
    """Get the content of the databag of `obj`, as seen from `other_obj`."""
    unit_name, endpoint = obj.split(":")
    other_unit_name, other_endpoint = other_obj.split(":")

    unit_data, app_data, leader = get_databags(unit_name, other_unit_name, other_endpoint)

    if not include_default_juju_keys:
        purge(unit_data)

    return UnitRelationData(unit_name, endpoint, leader, app_data, unit_data)


def get_databags(local_unit, remote_unit, remote_endpoint):
    """Gets the databags of local unit and its leadership status.

    Given a remote unit and the remote endpoint name.
    """
    local_data = get_unit_info(local_unit)
    leader = local_data["leader"]

    data = get_unit_info(remote_unit)
    relation_info = data.get("relation-info")
    if not relation_info:
        raise RuntimeError(f"{remote_unit} has no relations")

    raw_data = get_relation_by_endpoint(relation_info, remote_endpoint, local_unit)
    unit_data = raw_data["related-units"][local_unit]["data"]
    app_data = raw_data["application-data"]
    return unit_data, app_data, leader


@dataclass
class RelationData:
    provider: UnitRelationData
    requirer: UnitRelationData


def get_relation_data(
    *, provider_endpoint: str, requirer_endpoint: str, include_default_juju_keys: bool = False
):
    """Get relation databags for a juju relation.

    >>> get_relation_data('prometheus/0:ingress', 'traefik/1:ingress-per-unit')
    """
    provider_data = get_content(provider_endpoint, requirer_endpoint, include_default_juju_keys)
    requirer_data = get_content(requirer_endpoint, provider_endpoint, include_default_juju_keys)
    return RelationData(provider=provider_data, requirer=requirer_data)
