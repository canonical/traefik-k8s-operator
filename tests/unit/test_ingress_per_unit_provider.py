# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitProvider
from ops.charm import CharmBase
from scenario import Context, Model, Relation, State
from scenario.sequences import check_builtin_sequences


class MockProviderCharm(CharmBase):
    META = {
        "name": "my-charm",
        "provides": {"ingress-per-unit": {"interface": "ingress_per_unit", "limit": 1}},
    }

    def __init__(self, *args, **kwargs):
        """Initialize the mock charm."""
        super().__init__(*args, **kwargs)
        self.ipu = IngressPerUnitProvider(self)


def test_builtin_sequences():
    check_builtin_sequences(
        charm_type=MockProviderCharm,
        meta={
            "name": "test-provider",
            "provides": {"ingress-per-unit": {"interface": "ingress_per_unit", "limit": 1}},
        },
    )


@pytest.fixture
def model():
    return Model(name="test-model")


@pytest.fixture
def ipu_empty():
    return Relation(
        endpoint="ingress-per-unit",
        interface="ingress_per_unit",
        remote_app_name="remote",
        relation_id=0,
    )


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize(
    "event_name",
    ("update-status", "install", "start", "RELCHANGED", "config-changed"),
)
def test_ingress_unit_provider_related_is_ready(leader, event_name, ipu_empty, model):
    # patch the state with leadership

    state = State(model=model, relations=[ipu_empty], leader=leader)

    # shouldn't actually matter what event we test.
    # IPU should report ready because in this context
    # we can find remote relation data

    if event_name == "RELCHANGED":
        event = ipu_empty.changed_event
        # relation events need some extra metadata.
    else:
        event = event_name

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

    def callback(charm: MockProviderCharm):
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

    ipu_remote_provided = ipu_empty.replace(remote_units_data={0: mock_data})
    state = State(model=model, relations=[ipu_remote_provided], leader=leader)

    out = Context(charm_type=MockProviderCharm, meta=MockProviderCharm.META).run(
        ipu_remote_provided.changed_event, state, post_event=callback
    )

    if leader:
        local_ipa_data = out.relations[0].local_app_data
        assert local_ipa_data["ingress"] == f"remote/0:\n  url: {test_url}\n"
    else:
        assert not out.relations[0].local_app_data
