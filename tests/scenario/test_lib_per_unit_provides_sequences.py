# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from ops.charm import CharmBase
from scenario.scenario import Scenario, Scene
from scenario.runtime import Runtime
from scenario.scenario import check_builtin_sequences
from scenario.structs import (
    CharmSpec,
    Event,
    Model,
    RelationMeta,
    RelationSpec,
    State,
    event,
)

from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitProvider


class MockProviderCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressPerUnitProvider(self)


charm_spec = CharmSpec(
    charm_type=MockProviderCharm,
    meta={
        "name": "test-provider",
        "provides": {"ingress-per-unit": {"interface": "ingress_per_unit", "limit": 1}},
    },
)


@pytest.fixture
def scenario():
    return Scenario(charm_spec=charm_spec)



@pytest.fixture
def ipu_base_meta():
    return RelationMeta(
        endpoint="ingress-per-unit",
        interface="ingress_per_unit",
        remote_app_name="remote",
        relation_id=0,
    )


@pytest.fixture
def ipu_related(ipu_base_meta, ):
    """Context in which there is an IPU relation."""
    return State(model=Model(name="test-model"),
                 relations=[RelationSpec(meta=ipu_base_meta)])


@pytest.fixture
def ipu_related_data_provided(ipu_base_meta, ipu_related):
    """Context in which there is an IPU relation, and the remote side (single unit) has
    provided its side of the relation data.
    """
    data = {
        "port": "10",
        "host": "foo.bar",
        "model": "test-model",
        "name": "remote/0",
        "mode": "http",
    }
    return ipu_related.with_relations(
        (RelationSpec(meta=ipu_base_meta, remote_units_data={0: data}),)
    )


# def assert_not_ready(_, __, emitter: Emitter):
#     h: Harness = emitter.harness
#     relation = h.model.get_relation('ingress-per-unit')
#     if not relation:
#         return True
#     assert not h.charm.ipu.is_ready(relation)
#
#
# def assert_ready(_, __, emitter: Emitter):
#     h: Harness = emitter.harness
#     relation = h.model.get_relation('ingress-per-unit')
#     assert relation, 'relation not present'
#     assert h.charm.ipu.is_ready(relation)
#
#
# def assert_local_published_url(_, __, harness: Emitter, url: str = None, value: bool = True):
#     # check that the local side has published a url in their relation data.
#     # and that that matches the proxied_endpoints
#
#     h: Harness = emitter.harness
#     relation = h.model.get_relation('ingress-per-unit')
#     if not value:
#         assert h.charm.ipu.proxied_endpoints == {}
#         assert not relation.data[h.model.app], 'non-leader IPU providers should not have app data'
#         assert not relation.data[
#             h.model.unit], 'non-leader IPU providers should not have unit data'
#         return
#
#     for unit_dct in h.charm.ipu.proxied_endpoints.values():
#         if url:
#             assert unit_dct['url'] == url
#         else:
#             assert unit_dct['url']
#
#     assert relation.data[h.model.app]['ingress'] == yaml.safe_dump({'remote/0': {'url': url}})
#     assert not relation.data[h.model.unit], 'leader IPU providers should not have unit data'
#
#
# def assert_remote_data(_, __, emitter: Emitter, data: dict = None):
#     # check that the remote unit has correct mocked data
#     h: Harness = emitter.harness
#     data = data or {}
#     relation = h.model.get_relation('ingress-per-unit')
#     for unit in relation.units:
#         unit_data = relation.data[unit]
#         for key in ("port", "host", "model", "name", "mode"):
#             if data:
#                 assert unit_data[key] == data.get(key)
#             else:
#                 assert unit_data[key]


def test_builtin_sequences():
    check_builtin_sequences(charm_spec)


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize(
    "event_name",
    ("update-status", "install", "start", "ingress-per-unit-relation-changed", "config-changed"),
)
def test_ingress_unit_provider_related_is_ready(
    leader, event_name, ipu_related_data_provided, scenario
):
    # patch the ctx with leadership
    ctx = ipu_related_data_provided.replace(
        state=ipu_related_data_provided.state.replace(leader=leader)
    )

    # shouldn't actually matter what event we test.
    # IPU should report ready because in this context
    # we can find remote relation data
    scenario.play(Scene(context=ctx, event=event("start")))

    # todo: write assertions for ready and remote-data


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize("url", ("url.com", "http://foo.bar.baz"))
@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
def test_ingress_unit_provider_request_response(
    port, host, leader, url, ipu_base_meta, ipu_related, scenario
):
    mock_data = {
        "port": str(port),
        "host": str(host),
        "model": "test-model",
        "name": "remote/0",
        "mode": "http",
    }

    ipu = RelationSpec(meta=ipu_base_meta, remote_units_data={0: mock_data})
    ctx = ipu_related.with_leadership(leader).with_relations((ipu,))
    scenario.play(Scene(context=ctx, event=ipu.changed))

    # relation = emitter.harness.model.get_relation('ingress-per-unit')
    # provider: IngressPerUnitProvider = emitter.harness.charm.ipu
    # if leader:
    #     assert provider.publish_url(relation, 'remote/0', url)
    #
    # assert_local_published_url(None, None, emitter, url, leader)
    #
    # unit_data = provider.get_data(relation, relation.units.pop())
    # assert unit_data["model"] == "test-model"
    # assert unit_data["name"] == "remote/0"
    # assert unit_data["host"] == host
    # assert unit_data["port"] == port
    #
    # # fail because unit isn't leader
    # with pytest.raises(AssertionError):
    #     provider.publish_url(relation, unit_data["name"], "http://url/")
