# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from textwrap import dedent

import pytest
import yaml
from charms.traefik_k8s.v1.ingress import IngressPerAppReadyEvent, IngressPerAppRequirer
from ops.charm import CharmBase
from ops.testing import Harness

from charms.harness_extensions.v0.capture_events import capture


class MockRequirerCharm(CharmBase):
    META = dedent(
        """\
        name: test-requirer
        requires:
          ingress:
            interface: ingress
            limit: 1
        """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.ipa = IngressPerAppRequirer(self, port=80)


@pytest.fixture(scope="function")
def harness():
    harness = Harness(MockRequirerCharm, meta=MockRequirerCharm.META)
    harness._backend.model_name = "test-model"
    harness.begin_with_initial_hooks()
    return harness


@pytest.fixture(scope="function")
def requirer(harness):
    requirer = harness.charm.ipa
    return requirer


def test_ingress_app_requirer_uninitialized(requirer: IngressPerAppRequirer, harness):
    assert not requirer.is_ready()


# @pytest.mark.parametrize('url', ('foo.bar', 'foo.bar.baz'))
def test_ingress_app_requirer_related(requirer: IngressPerAppRequirer, harness):
    harness.set_leader(True)
    url = "foo.bar"

    assert not requirer.is_ready()
    # provider goes to ready immediately because we inited ipa with port=80.
    # auto-data feature...

    relation_id = harness.add_relation("ingress", "remote")
    requirer.provide_ingress_requirements(host="foo", port=42)
    assert not requirer.is_ready()

    with capture(harness.charm, IngressPerAppReadyEvent) as captured:
        harness.update_relation_data(
            relation_id, "remote", {"ingress": yaml.safe_dump({"url": url})}
        )
    event = captured.event
    assert event.url == url
    assert requirer.url == url
    assert requirer.is_ready()
