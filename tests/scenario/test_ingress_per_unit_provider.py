# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from dataclasses import replace

import pytest
from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitProvider
from ops.charm import CharmBase
from scenario import Context, Model, Relation, State
from scenario.context import CharmEvents

on = CharmEvents()


class MockProviderCharm(CharmBase):
    META = {
        "name": "my-charm",
        "provides": {"ingress-per-unit": {"interface": "ingress_per_unit", "limit": 1}},
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressPerUnitProvider(self)


@pytest.fixture
def model():
    return Model(name="test-model")


@pytest.fixture
def ipu_empty():
    return Relation(
        endpoint="ingress-per-unit",
        interface="ingress_per_unit",
        remote_app_name="remote",
        id=0,
    )


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize(
    "event_source", (on.update_status, on.install, on.start, "RELCHANGED", on.config_changed)
)
def test_ingress_unit_provider_related_is_ready(leader, event_source, ipu_empty, model):
    # patch the state with leadership

    state = State(model=model, relations=[ipu_empty], leader=leader)

    # shouldn't actually matter what event we test.
    # IPU should report ready because in this context
    # we can find remote relation data

    if event_source == "RELCHANGED":
        event = on.relation_changed(ipu_empty)
        # relation events need some extra metadata.
    else:
        event = event_source()

    Context(charm_type=MockProviderCharm, meta=MockProviderCharm.META).run(event, state)

    # todo: write assertions for ready and remote-data


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize("url", ("url.com", "http://foo.bar.baz"))
@pytest.mark.parametrize("mode", ("http", "tcp"))
@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
def test_ingress_unit_provider_request_response(port, host, leader, url, mode, ipu_empty, model):
    mock_data = {
        "port": str(port),
        "host": host,
        "model": "test-model",
        "name": "remote/0",
        "mode": mode,
    }

    test_url = "http://foo.com/babooz"

    ipu_remote_provided = replace(ipu_empty, remote_units_data={0: mock_data})
    state = State(model=model, relations=[ipu_remote_provided], leader=leader)

    with Context(charm_type=MockProviderCharm, meta=MockProviderCharm.META)(
        on.relation_changed(ipu_remote_provided), state
    ) as mgr:
        out = mgr.run()

        charm = mgr.charm
        ingress = charm.model.get_relation("ingress-per-unit")
        remote_unit = list(ingress.units)[0]

        assert charm.ipu.is_ready(ingress)
        assert charm.ipu.is_unit_ready(ingress, remote_unit)

        data = charm.ipu.get_data(ingress, remote_unit)
        assert data["mode"] == mode
        assert data["model"] == "test-model"
        assert data["name"] == "remote/0"
        assert data["host"] == host
        assert data["port"] == port

        if leader:
            charm.ipu.publish_url(ingress, remote_unit.name, test_url)
        else:
            with pytest.raises(AssertionError):
                charm.ipu.publish_url(ingress, remote_unit.name, test_url)

    if leader:
        local_ipa_data = out.get_relation(ipu_empty.id).local_app_data
        assert local_ipa_data["ingress"] == f"remote/0:\n  url: {test_url}\n"
    else:
        assert not out.get_relation(ipu_empty.id).local_app_data
