import pytest
from ops.charm import CharmBase
from scenario import State, Relation

from peer_storage import PeerStorage, _decode, _encode


@pytest.fixture(
    params=(
            # 'endpoint_name, interface_name',
            'storage',
            'my-endpoint',
    ))
def endpoint_name(request):
    return request.param


@pytest.fixture(
    params=(
            'peer-storage',  # default
            'my-interface',
    ))
def interface_name(request):
    return request.param


@pytest.fixture
def mycharm(endpoint_name, interface_name):
    class MyCharm(CharmBase):
        META = {
            "name": "my-charm",
            "peers": {endpoint_name: {"interface": interface_name}},
        }

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.stored = PeerStorage(self, endpoint=endpoint_name, interface=interface_name)
            self.stored.set_default(foo=42)

    return MyCharm


def test_base(mycharm):
    State().trigger('start', mycharm, meta=mycharm.META)


def test_with_relation(mycharm, endpoint_name, interface_name):
    out = State(
        relations=[
            Relation(endpoint=endpoint_name,
                     interface=interface_name,
                     remote_app_name='my-charm')
        ]
    ).trigger('install', mycharm, meta=mycharm.META)

    assert _decode(out.relations[0].local_unit_data['foo']) == 42


@pytest.mark.parametrize('override',
                         (10, 'foo', {'a': 'b'}, {'c', 'd'}, [1, 2], ('10', 20), {'a': {'10': [1.23]}})
                         )
def test_default(mycharm, endpoint_name, interface_name, override):
    def callback(charm):
        assert charm.stored.foo == 42
        charm.stored.foo = override
        charm.stored.bar = override

    out = State(
        relations=[
            Relation(endpoint=endpoint_name,
                     interface=interface_name,
                     remote_app_name='my-charm')
        ]
    ).trigger('install', mycharm, meta=mycharm.META,
              post_event=callback)

    stored_data = out.relations[0].local_unit_data
    assert _decode(stored_data['foo']) == override
    assert _decode(stored_data['bar']) == override


@pytest.mark.parametrize('override',
                         (10, 'foo', {'a': 'b'}, {'c', 'd'}, [1, 2], ('10', 20), {'a': {'10': [1.23]}})
                         )
def test_default_does_not_write(mycharm, endpoint_name, interface_name, override):
    out = State(
        relations=[
            Relation(endpoint=endpoint_name,
                     interface=interface_name,
                     remote_app_name='my-charm',
                     local_unit_data={
                         'foo': _encode(override),
                         'bar': _encode(override)
                     })
        ]
    ).trigger('install', mycharm, meta=mycharm.META)

    # check that the charm's __init__ (set_default call) did not overwrite 'foo'.
    stored_data = out.relations[0].local_unit_data
    assert _decode(stored_data['foo']) == override
    assert _decode(stored_data['bar']) == override
