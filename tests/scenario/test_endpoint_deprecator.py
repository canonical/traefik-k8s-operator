import pytest
from ops import CharmBase, Framework, ActiveStatus, WaitingStatus
from scenario import Context, State, Relation, capture_events

from endpoint_deprecator import EventRemapper
from lib.charms.traefik_k8s.v1 import ingress as ingress_v1
from lib.charms.traefik_k8s.v2 import ingress as ingress_v2


class IPAV1Shim(ingress_v1.IngressPerAppProvider):
    handle_kind = "ipav1_shim"


class IPAV2Shim(ingress_v2.IngressPerAppProvider):
    handle_kind = "ipav2_shim"


@pytest.fixture
def charm_type():
    class MyCharm(CharmBase):
        _calls = []

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.ipa_v1 = ipa_v1 = IPAV1Shim(charm=self)
            self.ipa_v2 = ipa_v2 = IPAV2Shim(charm=self)
            self.ipa = EventRemapper(self, "ingress", (
                (("1", ipa_v1, ipa_v1.is_ready), {
                    ipa_v1.on.data_provided: self._provide_ingress_v1,
                    ipa_v1.on.data_removed: self._remove_ingress_v1
                }),
                (("2", ipa_v2, ipa_v2.is_ready), {
                    ipa_v2.on.data_provided: self._provide_ingress_v2,
                    ipa_v2.on.data_removed: self._remove_ingress_v2
                }),
            ))

        def _provide_ingress_v1(self, e):
            MyCharm._calls.append("+v1")

        def _remove_ingress_v1(self, e):
            MyCharm._calls.append("-v1")

        def _provide_ingress_v2(self, e):
            MyCharm._calls.append("+v2")

        def _remove_ingress_v2(self, e):
            MyCharm._calls.append("-v2")

    return MyCharm


@pytest.fixture
def ctx(charm_type):
    return Context(
        charm_type,
        meta={'name': 'foo',
              "provides": {"ingress": {"interface": "ingress"}}
              }
    )


def test_remapped_event_empty_relations(ctx, charm_type):
    # both relations are empty, so we won't scream unsupported
    ipa_v1 = Relation(
        endpoint='ingress',
    )
    ipa_v2 = Relation(
        endpoint='ingress',
    )
    state = State(relations=[ipa_v1, ipa_v2])

    def post_event(charm):
        assert charm.ipa.status == WaitingStatus("waiting on relation data")

    with capture_events() as captured:
        ctx.run("start", state, post_event=post_event)

    assert not charm_type._calls


def test_remapped_event_observation(ctx, charm_type):
    remote_data_v1 = {
        "host": "host",
        "port": "42",
        "name": "foo",
        "model": "bar",
    }
    ipa_v1 = Relation(
        endpoint='ingress',
        remote_app_data=remote_data_v1
    )
    ipa_v2 = Relation(
        endpoint='ingress',
    )
    state = State(relations=[ipa_v1, ipa_v2])

    def post_event(charm):
        assert isinstance(charm.ipa.status, ActiveStatus)
        assert charm.ipa.status.message  # nonempty

    with capture_events() as captured:
        ctx.run(ipa_v1.changed_event, state, post_event=post_event)

    assert len(captured) == 2
    assert charm_type._calls == ['+v1']


def test_simultaneous_remapping(ctx, charm_type):
    remote_data_v1 = {
        "host": "host",
        "port": "42",
        "name": "foo",
        "model": "bar",
    }
    remote_app_data_v2 = {
        "name": "foo",
        "model": "bar",
    }
    remote_unit_data_v2 = {
        "port": "42",
        "host": "host",
    }

    ipa_v1 = Relation(
        endpoint='ingress',
        remote_app_data=remote_data_v1
    )
    ipa_v2 = Relation(
        endpoint='ingress',
        remote_app_data=remote_app_data_v2,
        remote_units_data={1: remote_unit_data_v2},
    )
    state = State(relations=[ipa_v1, ipa_v2])

    def post_event(charm):
        assert isinstance(charm.ipa.status, ActiveStatus)
        assert not charm.ipa.status.message  # empty

    with capture_events():
        ctx.run(ipa_v1.changed_event, state, post_event=post_event)

    assert charm_type._calls == ["+v1"]

    with capture_events():
        ctx.run(ipa_v2.changed_event, state, post_event=post_event)

    assert charm_type._calls == ["+v1", "+v2"]


def test_departing(ctx, charm_type):
    remote_data_v1 = {
        "host": "host",
        "port": "42",
        "name": "foo",
        "model": "bar",
    }
    remote_app_data_v2 = {
        "name": "foo",
        "model": "bar",
    }
    remote_unit_data_v2 = {
        "port": "42",
        "host": "host",
    }

    ipa_v1 = Relation(
        endpoint='ingress',
    )
    ipa_v2 = Relation(
        endpoint='ingress',
        remote_app_data=remote_app_data_v2,
        remote_units_data={1: remote_unit_data_v2},
    )
    state = State(relations=[ipa_v1, ipa_v2])

    with capture_events():
        ctx.run(ipa_v2.broken_event, state)

    assert charm_type._calls == ["-v2"]
