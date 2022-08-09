# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import socket
from textwrap import dedent

import pytest
import yaml
from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitProvider
from ops.charm import CharmBase
from ops.model import Relation
from ops.testing import Harness


class MockProviderCharm(CharmBase):
    META = dedent(
        """\
        name: test-provider
        provides:
          ingress-per-unit:
            interface: ingress_per_unit
            limit: 1
        """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressPerUnitProvider(self)


@pytest.fixture(scope="function")
def harness():
    harness = Harness(MockProviderCharm, meta=MockProviderCharm.META)
    harness.set_model_name("test-model")
    harness.begin_with_initial_hooks()
    return harness


@pytest.fixture(scope="function")
def provider(harness):
    provider = harness.charm.ipu
    return provider


def relate(harness: Harness[MockProviderCharm]):
    relation_id = harness.add_relation("ingress-per-unit", "remote")
    harness.add_relation_unit(relation_id, "remote/0")
    return harness.model.get_relation("ingress-per-unit", relation_id)


def _requirer_provide_ingress_requirements(
    harness: Harness[MockProviderCharm],
    port: int,
    relation: Relation,
    host=socket.getfqdn(),
    mode: str = "http",
):
    # same as requirer.provide_ingress_requirements(port=port, host=host)s
    harness.update_relation_data(
        relation.id,
        "remote/0",
        {"port": str(port), "host": host, "model": "test-model", "name": "remote/0", "mode": mode},
    )


def test_ingress_unit_provider_uninitialized(provider):
    assert not provider.is_ready()


@pytest.mark.parametrize("leader", (True, False))
def test_ingress_unit_provider_related(provider, harness, leader):
    harness.set_leader(leader)
    relation = relate(harness)

    assert not provider.is_ready(relation)


def test_ingress_unit_provider_request(provider, harness):
    relation = relate(harness)
    _requirer_provide_ingress_requirements(harness, 80, relation)
    assert provider.is_ready(relation)


@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
def test_ingress_unit_provider_request_response_nonleader(provider, harness, port, host):
    provider: IngressPerUnitProvider
    relation = relate(harness)
    _requirer_provide_ingress_requirements(harness, port, relation, host=host)

    unit_data = provider.get_data(relation, relation.units.pop())
    assert unit_data["model"] == "test-model"
    assert unit_data["name"] == "remote/0"
    assert unit_data["host"] == host
    assert unit_data["port"] == port

    # fail because unit isn't leader
    with pytest.raises(AssertionError):
        provider.publish_url(relation, unit_data["name"], "http://url/")


@pytest.mark.parametrize("url", ("http://url/", "http://url2/"))
def test_ingress_unit_provider_request_response(provider, harness, url):
    relation = relate(harness)
    harness.set_leader(True)
    _requirer_provide_ingress_requirements(harness, 80, relation)
    provider.publish_url(relation, "remote/0", url)

    ingress = relation.data[harness.charm.app]["ingress"]
    assert yaml.safe_load(ingress) == {"remote/0": {"url": url}}
