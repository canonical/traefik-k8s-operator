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
        relation_id=0,
    )


def test_builtin_sequences():
    check_builtin_sequences(
        charm_type=MockProviderCharm,
        meta={
            "name": "test-provider",
            "provides": {"ingress-per-unit": {"interface": "ingress_per_unit", "limit": 1}},
        },
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
@pytest.mark.parametrize("mode", ("tcp", "http"))
@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
def test_ingress_unit_provider_request_response(port, host, leader, url, mode, ipu_empty, model):
    mock_data = {
        "port": str(port),
        "host": host,
        "model": "test-model",
        "name": "remote/0",
        "mode": mode,
    }

    ipu_remote_provided = ipu_empty.replace(remote_units_data={0: mock_data})
    state = State(model=model, relations=[ipu_remote_provided], leader=leader)

    ctx = Context(charm_type=MockProviderCharm, meta=MockProviderCharm.META)
    ctx.run(ipu_remote_provided.changed_event, state)
