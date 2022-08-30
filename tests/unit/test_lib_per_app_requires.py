# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import unittest
from textwrap import dedent

import pytest
import yaml
from charms.harness_extensions.v0.capture_events import capture
from charms.traefik_k8s.v1.ingress import (
    DataValidationError,
    IngressPerAppReadyEvent,
    IngressPerAppRequirer,
    IngressPerAppRevokedEvent,
)
from ops.charm import CharmBase
from ops.testing import Harness


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


@pytest.mark.parametrize(
    "auto_data, ok",
    (
        ((True, 42), False),
        ((10, False), False),
        ((10, None), False),
        (("foo", 12), True),
    ),
)
def test_validator(requirer: IngressPerAppRequirer, harness, auto_data, ok):
    harness.set_leader(True)
    harness.add_relation("ingress", "remote")
    if not ok:
        with pytest.raises(DataValidationError):
            host, port = auto_data
            requirer.provide_ingress_requirements(host=host, port=port)
    else:
        host, port = auto_data
        requirer.provide_ingress_requirements(host=host, port=port)


class TestIPAEventsEmission(unittest.TestCase):
    class _RequirerCharm(CharmBase):
        META = dedent(
            """\
            name: ipa-requirer
            requires:
              ingress:
                interface: ingress
                limit: 1
            """
        )

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.ipa = IngressPerAppRequirer(self, relation_name="ingress", port=80)

    def setUp(self):
        self.harness = Harness(self._RequirerCharm, meta=self._RequirerCharm.META)
        self.addCleanup(self.harness.cleanup)

        self.harness.set_model_name(self.__class__.__name__)
        self.harness.begin_with_initial_hooks()

    def test_ipa_events(self):
        # WHEN an ingress relation is formed
        # THEN the ready event is emitted
        with capture(self.harness.charm, IngressPerAppReadyEvent):
            self.rel_id = self.harness.add_relation("ingress", "traefik-app")
            self.harness.add_relation_unit(self.rel_id, "traefik-app/0")

            # AND an ingress is in effect
            data = {"url": "http://a.b/c"}
            self.harness.update_relation_data(
                self.rel_id, "traefik-app", {"ingress": yaml.safe_dump(data)}
            )
            self.assertEqual(self.harness.charm.ipa.url, "http://a.b/c")

        # WHEN a relation with traefik is removed
        # THEN a revoked event fires
        with capture(self.harness.charm, IngressPerAppRevokedEvent):
            self.harness.remove_relation_unit(self.rel_id, "traefik-app/0")
            self.harness.remove_relation(self.rel_id)
            # NOTE intentionally not emptying out relation data manually

        # AND ingress.url returns a false-y value
        self.assertFalse(self.harness.charm.ipa.url)
