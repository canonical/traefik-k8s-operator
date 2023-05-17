# GIVEN a charm with ingress impl'd
# WHEN a relation with traefik is formed
# THEN traefik's config file's `server` section has all the units listed
# AND WHEN the charm rescales
# THEN the traefik config file is updated

import tempfile
from pathlib import Path

import pytest
import yaml
from ops import pebble
from scenario import Context, State, Container, Relation, Model, Mount


@pytest.fixture
def context(traefik_charm):
    return Context(charm_type=traefik_charm)


@pytest.fixture
def model():
    return Model(name="test-model")


@pytest.fixture
def temp_opt():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def traefik_container(temp_opt):
    layer = pebble.Layer({
        "summary": "Traefik layer",
        "description": "Pebble config layer for Traefik",
        "services": {
            'traefik': {
                "override": "replace",
                "summary": "Traefik",
                "command": '/bin/sh -c "/usr/bin/traefik | tee /var/log/traefik.log"',
                "startup": "enabled",
            },
        },
    })

    opt = Mount('/opt/', temp_opt)

    return Container(
        name="traefik",
        can_connect=True,
        layers={'traefik': layer},
        service_status={'traefik': pebble.ServiceStatus.ACTIVE},
        mounts={'opt': opt}
    )


@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
@pytest.mark.parametrize("event_name", ("joined", "changed"))
def test_ingress_per_leader_created(context, port, host, model, traefik_container, event_name, temp_opt):
    """Check the config when a new ingress per leader is created or changes (single remote unit)."""
    mock_data = {
        "port": str(port),
        "host": host,
        "model": "test-model",
        "name": "remote/0",
        "mode": "http",
    }
    ipl = Relation('ingress',
                   remote_app_data=mock_data,
                   relation_id=1)
    state = State(
        model=model,
        config={"routing_mode": "path",
                "external_hostname": "foo.com"},
        containers=[traefik_container],
        relations=[ipl],
    )

    event = getattr(ipl, f"{event_name}_event")
    context.run(event, state)

    generated_config = yaml.safe_load(traefik_container.filesystem.open(
            '/opt/traefik/juju/juju_ingress_ingress_1_remote.yaml'
        ).read())

    assert generated_config['http']['services']['juju-test-model-remote-0-service'] == {
        'loadBalancer': {'servers': [{'url': f'http://{host}:{port}'}]}
    }


@pytest.mark.parametrize("port, host", ((80, "1.1.1.{}"), (81, "10.1.10.{}")))
@pytest.mark.parametrize("n_units", (2, 3, 10))
@pytest.mark.parametrize("mode", ("http", "https"))
def test_ingress_per_leader_scale(context, host, port, model, temp_opt, n_units, mode):
    """Check the config when a new ingress per leader unit joins."""
    cfg_file = temp_opt.joinpath("traefik", "juju", "juju_ingress_ingress_1_remote.yaml")
    cfg_file.parent.mkdir(parents=True)
    # config that would have been generated from mock_data_0
    # same as config output of the previous test
    initial_cfg = {'http': {'routers': {
        'juju-test-model-remote-0-router': {
            'entryPoints': ['web'],
            'rule': 'PathPrefix(`/test-model-remote-0`)',
            'service': 'juju-test-model-remote-0-service'},
        'juju-test-model-remote-0-router-tls': {
            'entryPoints': ['websecure'],
            'rule': 'PathPrefix(`/test-model-remote-0`)',
            'service': 'juju-test-model-remote-0-service',
            'tls': {'domains': [{'main': 'foo.com', 'sans': ['*.foo.com']}]}}},
        'services': {
            'juju-test-model-remote-0-service': {
                'loadBalancer': {'servers': [{'url': f'{mode}://{host}:{port}'}]}}}}}
    cfg_file.write_text(yaml.safe_dump(initial_cfg))

    def _get_mock_data(n: int):
        return {
            "port": str(port+n),
            "host": host.format(n),
            "model": "test-model",
            "name": f"remote/{n}",
            "mode": mode,
        }

    ipl = Relation('ingress',
                   remote_units_data={
                       n: _get_mock_data(n) for n in range(n_units)
                   })
    state = State(
        model=model,
        config={"routing_mode": "path",
                "external_hostname": "foo.com"},
        containers=[Container(name="traefik", can_connect=False)],
        relations=[ipl]
    )

    context.run(ipl.changed_event, state)

    new_config = yaml.safe_load(cfg_file.read_text())
    # verify that the config has changed!
    new_lbs = new_config['http']['services']['juju-test-model-remote-0-service']['loadBalancer']['servers']
    assert len(new_lbs) == n_units
    for n in range(n_units):
        assert {'url': f'{mode}://{host.format(n)}:{port+n}'} in new_lbs
