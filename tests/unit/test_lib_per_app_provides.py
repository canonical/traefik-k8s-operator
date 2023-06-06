# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from textwrap import dedent

import pytest
import yaml
from charms.traefik_k8s.v2.ingress import IngressPerAppProvider
from ops.charm import CharmBase
from ops.testing import Harness


class MockProviderCharm(CharmBase):
    META = dedent(
        """\
        name: test-provider
        provides:
          ingress:
            interface: ingress
            limit: 1
        """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipa = IngressPerAppProvider(self)


@pytest.fixture(scope="function")
def harness():
    harness = Harness(MockProviderCharm, meta=MockProviderCharm.META)
    harness._backend.model_name = "test-model"
    harness.begin_with_initial_hooks()
    return harness


@pytest.fixture(scope="function")
def provider(harness):
    provider = harness.charm.ipa
    return provider


def test_ingress_app_provider_uninitialized(provider: IngressPerAppProvider):
    assert not provider.relations
    assert not provider.is_ready()


def test_ingress_app_provider_related(harness, provider: IngressPerAppProvider):
    relation = harness.add_relation("ingress", "remote")
    assert not provider.is_ready(relation)


@pytest.mark.parametrize("strip_prefix", ("true", "false"))
def test_ingress_app_provider_relate_provide(
    provider: IngressPerAppProvider, harness, strip_prefix
):
    harness.set_leader(True)
    relation_id = harness.add_relation("ingress", "remote")
    harness.add_relation_unit(relation_id, "remote/0")
    remote_app_data = {
        "name": "foo",
        "model": "bar",
        "strip_prefix": strip_prefix,
    }
    remote_unit_data = {
        "host": "host",
        "port": "42",
    }
    harness.update_relation_data(relation_id, "remote", remote_app_data)
    harness.update_relation_data(relation_id, "remote/0", remote_unit_data)

    relation = harness.model.get_relation("ingress", relation_id)
    assert provider.is_ready(relation)

    provider.publish_url(relation, "foo.com")

    ingress = harness.get_relation_data(relation_id, "test-provider")["ingress"]
    assert yaml.safe_load(ingress) == {"url": "foo.com"}
