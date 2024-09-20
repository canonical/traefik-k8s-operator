# GIVEN a charm with ingress impl'd
# WHEN a relation with traefik is formed
# THEN traefik's config file's `server` section has all the units listed
# AND WHEN the charm rescales
# THEN the traefik config file is updated
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from ops import pebble
from scenario import Container, Model, Mount, Relation, State
from scenario.context import CharmEvents

on = CharmEvents()


@pytest.fixture
def model():
    return Model(name="test-model")


@pytest.fixture
def traefik_container(tmp_path):
    layer = pebble.Layer(
        {
            "summary": "Traefik layer",
            "description": "Pebble config layer for Traefik",
            "services": {
                "traefik": {
                    "override": "replace",
                    "summary": "Traefik",
                    "command": '/bin/sh -c "/usr/bin/traefik | tee /var/log/traefik.log"',
                    "startup": "enabled",
                },
            },
        }
    )

    opt = Mount(location="/opt/", source=tmp_path)

    return Container(
        name="traefik",
        can_connect=True,
        layers={"traefik": layer},
        service_statuses={"traefik": pebble.ServiceStatus.ACTIVE},
        mounts={"opt": opt},
    )


@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
@pytest.mark.parametrize(
    "event_source", (on.relation_joined, on.relation_changed, on.relation_created)
)
def test_ingress_per_app_created(
    traefik_ctx, port, host, model, traefik_container, event_source, tmp_path, caplog
):
    """Check the config when a new ingress per leader is created or changes (single remote unit)."""
    ipa = Relation(
        "ingress",
        remote_app_data={
            "model": "test-model",
            "name": "remote/0",
            "port": str(port),
            "host": host,
        },
        id=1,
    )
    state = State(
        model=model,
        config={"routing_mode": "path", "external_hostname": "foo.com"},
        containers=[traefik_container],
        relations=[ipa],
    )

    # WHEN any relevant event fires
    with caplog.at_level("WARNING"):
        traefik_ctx.run(event_source(ipa), state)
    assert "is using a deprecated ingress v1 protocol to talk to Traefik." in caplog.text

    generated_config = yaml.safe_load(
        traefik_container.get_filesystem(traefik_ctx)
        .joinpath(f"opt/traefik/juju/juju_ingress_ingress_{ipa.id}_remote.yaml")
        .read_text()
    )

    assert generated_config["http"]["services"]["juju-test-model-remote-0-service"] == {
        "loadBalancer": {"servers": [{"url": f"http://{host}:{port}"}]},
    }


@patch("charm.TraefikIngressCharm._static_config_changed", PropertyMock(return_value=False))
@pytest.mark.parametrize("port, host", ((80, "1.1.1.2"), (81, "10.1.10.2")))
@pytest.mark.parametrize("n_units", (2, 3, 10))
def test_ingress_per_app_scale(
    traefik_ctx, host, port, model, traefik_container, tmp_path, n_units, caplog
):
    """Check the config when a new ingress per leader unit joins."""
    cfg_file = tmp_path.joinpath("traefik", "juju", "juju_ingress_ingress_1_remote.yaml")
    cfg_file.parent.mkdir(parents=True)

    # config that would have been generated from mock_data_0
    # same as config output of the previous test
    initial_cfg = {
        "http": {
            "routers": {
                "juju-test-model-remote-0-router": {
                    "entryPoints": ["web"],
                    "rule": "PathPrefix(`/test-model-remote-0`)",
                    "service": "juju-test-model-remote-0-service",
                },
                "juju-test-model-remote-0-router-tls": {
                    "entryPoints": ["websecure"],
                    "rule": "PathPrefix(`/test-model-remote-0`)",
                    "service": "juju-test-model-remote-0-service",
                    "tls": {"domains": [{"main": "foo.com", "sans": ["*.foo.com"]}]},
                },
            },
            "services": {
                "juju-test-model-remote-0-service": {
                    "loadBalancer": {"servers": [{"url": f"http://{host}:{port}"}]}
                }
            },
        }
    }
    cfg_file.write_text(yaml.safe_dump(initial_cfg))
    ipa = Relation(
        "ingress",
        remote_app_data={
            "model": "test-model",
            "name": "remote",
            "port": str(port),
            "host": host,
        },
        id=1,
    )
    state = State(
        model=model,
        config={"routing_mode": "path", "external_hostname": "foo.com"},
        containers=[traefik_container],
        relations=[ipa],
    )

    with caplog.at_level("WARNING"):
        traefik_ctx.run(on.relation_changed(ipa), state)
    assert "is using a deprecated ingress v1 protocol to talk to Traefik." in caplog.text

    new_config = yaml.safe_load(cfg_file.read_text())
    # verify that the config has changed!
    new_lbs = new_config["http"]["services"]["juju-test-model-remote-service"]["loadBalancer"][
        "servers"
    ]

    assert len(new_lbs) == 1
    assert {"url": f"http://{host}:{port}"} in new_lbs
