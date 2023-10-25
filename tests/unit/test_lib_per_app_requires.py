# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import json
import unittest
import unittest.mock
from textwrap import dedent

import pytest
from charms.harness_extensions.v0.capture_events import capture
from charms.traefik_k8s.v2.ingress import (
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


@pytest.mark.parametrize("strip_prefix", (True, False))
def test_ingress_app_requirer_related(requirer: IngressPerAppRequirer, harness, strip_prefix):
    harness.set_leader(True)
    url = "http://foo.bar"

    assert not requirer.is_ready()
    # provider goes to ready immediately because we inited ipa with port=80.
    # auto-data feature...
    harness.add_network("10.0.0.1")
    relation_id = harness.add_relation("ingress", "remote")
    # usually one would provide this via the initializer, but here...
    requirer._strip_prefix = strip_prefix

    requirer.provide_ingress_requirements(host="foo", ip="10.0.0.1", port=42)
    assert not requirer.is_ready()

    with capture(harness.charm, IngressPerAppReadyEvent) as captured:
        harness.update_relation_data(relation_id, "remote", {"ingress": json.dumps({"url": url})})
    event = captured.event
    assert event.url == url
    assert requirer.url == url
    assert requirer.is_ready()


@pytest.mark.parametrize(
    "auto_data, ok",
    (
        ((True, "example.com", 42), False),
        ((10, "example.com", False), False),
        ((10, "example.com", None), False),
        (("foo", "10.0.0.1", 12), True),
        (("foo", "not.an.ip", 12), False),
    ),
)
@pytest.mark.parametrize("strip_prefix", (True, False))
@pytest.mark.parametrize("scheme", ("http", "https"))
def test_validator(requirer: IngressPerAppRequirer, harness, auto_data, ok, strip_prefix, scheme):
    harness.set_leader(True)
    harness.add_network("10.0.0.10")
    harness.add_relation("ingress", "remote")
    requirer._strip_prefix = strip_prefix
    requirer._scheme = scheme

    if not ok:
        with pytest.raises(DataValidationError):
            host, ip, port = auto_data
            requirer.provide_ingress_requirements(host=host, ip=ip, port=port)
    else:
        host, ip, port = auto_data
        requirer.provide_ingress_requirements(host=host, ip=ip, port=port)


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

    def test_ipa_events(self):
        self.harness.begin_with_initial_hooks()

        # WHEN an ingress relation is formed
        # THEN the ready event is emitted
        with capture(self.harness.charm, IngressPerAppReadyEvent):
            self.harness.add_network("10.0.0.10")
            self.rel_id = self.harness.add_relation("ingress", "traefik-app")
            self.harness.add_relation_unit(self.rel_id, "traefik-app/0")

            # AND an ingress is in effect
            data = {"url": "http://a.b/c"}
            self.harness.update_relation_data(
                self.rel_id, "traefik-app", {"ingress": json.dumps(data)}
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

    def test_ipa_events_juju_binding_failure(self):
        with unittest.mock.patch("ops.Model.get_binding", return_value=None):
            self.harness.begin_with_initial_hooks()
            self.rel_id = self.harness.add_relation("ingress", "traefik-app")
            self.harness.add_relation_unit(self.rel_id, "traefik-app/0")
            self.harness.charm.ipa.provide_ingress_requirements(port=80)

            self.assertEqual(
                self.harness.get_relation_data(self.rel_id, "ipa-requirer/0")["ip"], "null"
            )
