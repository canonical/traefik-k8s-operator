# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from charms.traefik_k8s.v2.ingress import (
    IngressPerAppRequirer,
    IngressRequirerAppData,
)
from ops import Port
from ops.charm import CharmBase
from scenario import Context, Model, Relation, State


class MockRequirerCharm(CharmBase):
    META = {
        "name": "test-requirer",
        "requires": {"ingress": {"interface": "ingress", "limit": 1}},
    }

    def __init__(self, *args, **kwargs):
        """Initialize the mock charm."""
        super().__init__(*args)
        self.ipa = IngressPerAppRequirer(self, port=80)


@pytest.fixture
def requirer_ctx():
    return Context(MockRequirerCharm, meta=MockRequirerCharm.META)


def test_requirer_sets_is_port_open_true_when_port_is_open(requirer_ctx):
    ingress_rel = Relation("ingress")
    state = State(
        leader=True,
        opened_ports=[Port("tcp", 80)],
        relations=[ingress_rel],
        model=Model(name="test-model"),
    )

    state_out = requirer_ctx.run(ingress_rel.changed_event, state)

    app_data = state_out.get_relations("ingress")[0].local_app_data
    assert app_data["is_port_open"] == "true"
    assert IngressRequirerAppData.load(app_data).is_port_open


def test_requirer_omits_is_port_open_when_port_is_not_open(requirer_ctx):
    ingress_rel = Relation("ingress")
    state = State(
        leader=True,
        opened_ports=frozenset(),
        relations=[ingress_rel],
        model=Model(name="test-model"),
    )

    state_out = requirer_ctx.run(ingress_rel.changed_event, state)

    app_data = state_out.get_relations("ingress")[0].local_app_data
    assert "is_port_open" not in app_data
    assert not IngressRequirerAppData.load(app_data).is_port_open
