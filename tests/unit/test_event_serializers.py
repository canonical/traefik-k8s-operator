# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
import yaml
from charms.traefik_k8s.v1.ingress_per_unit import _IPUEvent
from charms.traefik_k8s.v2.ingress import _IPAEvent
from ops.charm import CharmBase
from ops.framework import EventSource, ObjectEvents
from ops.testing import Harness


@pytest.fixture(params=(_IPUEvent, _IPAEvent))
def event_superclass(request):
    return request.param


@pytest.fixture
def event_class(event_superclass):
    class _MyEventClass(event_superclass):
        __args__ = ("foo", "bar", "foo2", "bar2")
        __optional_kwargs__ = {"baz": "0"}

    return _MyEventClass


@pytest.fixture
def event_container(event_class):
    class _EventContainer(ObjectEvents):
        event = EventSource(event_class)

    return _EventContainer


@pytest.fixture
def charm_cls(event_container):
    class MyCharm(CharmBase):
        on = event_container()
        event = None

        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.event, self._on_event)

        def _on_event(self, event):
            self.event = event

    return MyCharm


META = yaml.safe_dump(
    {"name": "my_charm", "requires": {"my_relation": {"interface": "my_relation"}}}
)


@pytest.fixture
def harness(charm_cls):
    return Harness(charm_cls, meta=META)


@pytest.fixture
def charm(harness):
    harness.begin()
    return harness.charm


# signature is (foo, bar, foo2, bar2, baz=0, model:Model)
@pytest.mark.parametrize(
    "args, kwargs, ok",
    (
        ((), {}, 0),
        (("1",), {}, 0),
        (("1", "2"), {}, 0),
        (("1", "2", "3"), {}, 0),
        (("1", "2", "3"), {"baz": 5}, 0),
        (("1", "2"), {"baz": 5}, 0),
        # good
        (("1", "2", "3", "4"), {}, 1),
        (("1", "2", "3", "4"), {"baz": "5"}, 1),
    ),
)
def test_constructor(harness, charm, args, kwargs, ok):
    relation_id = harness.add_relation("my_relation", "remote")
    relation = harness.model.get_relation("my_relation", relation_id)

    if ok:
        charm.on.event.emit(relation, *args, **kwargs)

        event = charm.event
        assert event

        assert event.foo == "1"
        assert event.bar == "2"
        assert event.foo2 == "3"
        assert event.bar2 == "4"
        assert event.baz == kwargs.get("baz", "0")

    else:
        with pytest.raises(TypeError):
            charm.on.event.emit(relation, *args, **kwargs)
