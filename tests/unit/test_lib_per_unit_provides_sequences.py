# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from functools import partial

import pytest
import yaml
from ops.charm import CharmBase, InstallEvent
from ops.testing import Harness

from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitProvider
from evt_sequences import Scenario, RelationMeta, RelationSpec, Model, Context, Emitter, Event, \
    CharmSpec, Scene, previous_context, Playbook


class MockProviderCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressPerUnitProvider(self)


charm_spec = CharmSpec(
    charm_type=MockProviderCharm,
    meta={
        'name': 'test-provider',
        'provides':
            {
                'ingress-per-unit':
                    {
                        'interface': 'ingress_per_unit'
                    },
                'limit': 1
            }
    }
)

IPUMeta = RelationMeta(endpoint='ingress-per-unit',
                       interface='ingress_per_unit',
                       remote_app_name='remote',
                       relation_id=0)

base_ctx = Context(model=Model(name='test-model'))
related_ctx = base_ctx.replace(relations=[
    RelationSpec(meta=IPUMeta)
])
ipu_data_base = {"port": '10',
                 "host": 'foo.bar',
                 "model": "test-model",
                 "name": "remote/0",
                 "mode": 'http'}
base_ipu_relation_spec = RelationSpec(
    meta=IPUMeta,
    units_data={0: ipu_data_base})

# context in which the remote side (single unit) has
# provided its side of the relation data.
related_ctx_remote_provided_req = base_ctx.replace(relations=[
    base_ipu_relation_spec
])


def assert_not_ready(_, __, emitter: Emitter):
    h: Harness = emitter.harness
    relation = h.model.get_relation('ingress-per-unit')
    if not relation:
        return True
    assert not h.charm.ipu.is_ready(relation)


def assert_ready(_, __, emitter: Emitter):
    h: Harness = emitter.harness
    relation = h.model.get_relation('ingress-per-unit')
    assert relation, 'relation not present'
    assert h.charm.ipu.is_ready(relation)


def assert_local_published_url(_, __, emitter: Emitter, url: str = None, value: bool = True):
    # check that the local side has published a url in their relation data.
    # and that that matches the proxied_endpoints

    h: Harness = emitter.harness
    relation = h.model.get_relation('ingress-per-unit')
    if not value:
        assert h.charm.ipu.proxied_endpoints == {}
        assert not relation.data[h.model.app], 'non-leader IPU providers should not have app data'
        assert not relation.data[
            h.model.unit], 'non-leader IPU providers should not have unit data'
        return

    for unit_dct in h.charm.ipu.proxied_endpoints.values():
        if url:
            assert unit_dct['url'] == url
        else:
            assert unit_dct['url']

    assert relation.data[h.model.app]['ingress'] == yaml.safe_dump({'remote/0': {'url': url}})
    assert not relation.data[h.model.unit], 'leader IPU providers should not have unit data'


def assert_remote_data(_, __, emitter: Emitter, data: dict = None):
    # check that the remote unit has correct mocked data
    h: Harness = emitter.harness
    data = data or {}
    relation = h.model.get_relation('ingress-per-unit')
    for unit in relation.units:
        unit_data = relation.data[unit]
        for key in ("port", "host", "model", "name", "mode"):
            if data:
                assert unit_data[key] == data.get(key)
            else:
                assert unit_data[key]


def test_startup_sequence_leader():
    scenario = Scenario.builtins.STARTUP_LEADER.bind(charm_spec)
    # check that every step of the way, IPU is not ready
    scenario.play_until_complete(assertions=assert_not_ready)


def test_startup_sequence_follower():
    scenario = Scenario.builtins.STARTUP_FOLLOWER.bind(charm_spec)
    scenario.play_until_complete(assertions=assert_not_ready)


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize("event_name", ('update-status', 'install', 'start',
                                        'ingress-per-unit-relation-changed',
                                        'config-changed'))
def test_ingress_unit_provider_related_is_ready(leader, event_name):
    related_ctx_remote_provided_req.replace(leader=leader).play(
        # shouldn't actually matter what event we test.
        # IPU should report ready because in this context
        # we can find remote relation data
        event=Event(event_name),
        charm_spec=charm_spec,
        assertions=[assert_ready,
                    assert_remote_data]
    )


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize("url", ('url.com', 'http://foo.bar.baz'))
@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
def test_ingress_unit_provider_request_response(port, host, leader, url):
    _, __, emitter = base_ctx.replace(
        leader=leader,
        relations=[
            base_ipu_relation_spec.replace(
                units_data={0: {"port": str(port), "host": str(host),
                                "model": "test-model",
                                "name": "remote/0",
                                "mode": 'http'}})]
    ).play(
        Event('ingress-per-unit-relation-changed'),
        charm_spec=charm_spec
    )

    relation = emitter.harness.model.get_relation('ingress-per-unit')
    provider: IngressPerUnitProvider = emitter.harness.charm.ipu
    if leader:
        assert provider.publish_url(relation, 'remote/0', url)

    assert_local_published_url(None, None, emitter, url, leader)

    unit_data = provider.get_data(relation, relation.units.pop())
    assert unit_data["model"] == "test-model"
    assert unit_data["name"] == "remote/0"
    assert unit_data["host"] == host
    assert unit_data["port"] == port

    # fail because unit isn't leader
    with pytest.raises(AssertionError):
        provider.publish_url(relation, unit_data["name"], "http://url/")


def test_ingress_remains_consistent():
    ipu_data_changed = {"port": '10',
                        "host": 'choo.choo',  # changed
                        "model": "test-model",
                        "name": "remote/0",
                        "mode": 'tcp'}
    scenario = Scenario(charm_spec, Playbook(
        (
            Scene(Event('install'), base_ctx.replace(leader=False)),
            # we gain leadership as we run config-changed
            Scene(Event('config-changed'), previous_context.replace(leader=True)),
            # previous context is assumed by default: we still have leadership
            # as we run start
            Scene(Event('start')),
            Scene(Event('ingress-per-unit-relation-created'),
                  previous_context.replace(relations=[RelationSpec(meta=IPUMeta)])),
            Scene(Event('ingress-per-unit-relation-joined'),
                  previous_context.replace(relations=[base_ipu_relation_spec])),
            Scene(Event('ingress-per-unit-relation-changed'),
                  previous_context.replace(relations=[base_ipu_relation_spec])),
            Scene(Event('update-status')),
            # now relation data REALLY changes!
            Scene(Event('ingress-per-unit-relation-changed'),
                  previous_context.replace(relations=[
                      base_ipu_relation_spec.replace(
                          units_data={0: ipu_data_changed})  # changed
                  ])),
            # add an unchanged teardown sequence at the boottom
        )) + Scenario.builtins.TEARDOWN.playbook
                        )

    with scenario:
        evt, _, _ = scenario.play_next()
        assert isinstance(evt, InstallEvent)

        evt, _, _ = scenario.play_next(3)  # skip to ipu-relation-created

        # check that up until the teardown sequence,
        # ipu has remote data and some local published url
        scenario.play_next(
            4,
            assertions=[assert_ready,
                        partial(assert_remote_data, data=ipu_data_base),
                        assert_local_published_url]
        )
        # now the remote data ACTUALLY changes!
        scenario.play_next(
            4,
            assertions=[assert_ready,
                        partial(assert_remote_data, data=ipu_data_changed),
                        assert_local_published_url]
        )

        # we simulate a teardown sequence: first step is break all relations,
        # which means local and remote data will be gone, and IPU will be not ready.
        scenario.embed(scenario.builtins.TEARDOWN,
                assertions=[assert_not_ready,
                            partial(assert_local_published_url, value=False)])

    from pathlib import Path
    (Path(__file__).parent / 'ipu.playbook').write_text(scenario.playbook.dump())
