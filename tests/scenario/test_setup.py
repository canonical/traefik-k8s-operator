from pathlib import Path
from unittest.mock import patch, PropertyMock

import yaml

from charm import TraefikIngressCharm
from scenario import Scenario
from scenario.structs import RelationMeta, RelationSpec, Context, NetworkSpec, Event, CharmSpec, ContainerSpec, network, \
    State, event, Scene

META = yaml.safe_load((Path(__file__).parent.parent.parent / 'metadata.yaml').read_text())


@patch("charm.KubernetesServicePatch")
@patch("lightkube.core.client.GenericSyncClient")
@patch("charm.TraefikIngressCharm.external_host", PropertyMock(return_value='foo.bar'))
def test_start(*_):
    scenario = Scenario(
        charm_spec=CharmSpec(
            TraefikIngressCharm,
            meta=META)
    )

    null_ctx = Context()
    scenario.play(
        Scene(
            context=null_ctx,
            event=event('start'))
    )


def test_start_as_follower(*_):
    my_scenario = Scenario(
        charm_spec=CharmSpec(
            TraefikIngressCharm,
            meta=META)
    )

    with my_scenario as scenario:
        null_ctx = Context()
        a, b, c = scenario.play(
            context=null_ctx.replace(leader=False),
            event=Event('start'))
        assert c.harness.charm.unit.status.name == 'active'


def test_ipu_changed():
    my_scenario = Scenario(
        charm_spec=CharmSpec(
            TraefikIngressCharm,
            meta=META)
    )

    with my_scenario as scenario:
        scenario.play(
            context=Context(
                state=State(
                    containers=(
                        ContainerSpec('mimir', can_connect=False),
                    ),
                    networks=(
                        NetworkSpec(
                            name='endpoint', bind_id=2,
                            network=network(private_address='0.0.0.2')),
                    ),
                    relations=(
                        RelationSpec(
                            application_data={'foo': 'bar'},
                            units_data={0: {'baz': 'qux'}},
                            meta=RelationMeta(
                                remote_app_name='remote',
                                relation_id=2,
                                endpoint='remote-db',
                                remote_unit_ids=(0,),
                                interface='db')),
                    ),
                    leader=True
                ),
            ),
            event=Event('ingress-per-unit-relation-changed'))
