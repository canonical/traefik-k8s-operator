import pathlib
from unittest.mock import PropertyMock, patch

import pytest
import yaml
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from ops import pebble
from scenario import Container, Context, ExecOutput, Model, Mount, Relation, State

from charm import TraefikIngressCharm

MOCK_LB_ADDRESS = "1.2.3.4"

ROUTE_CONFIG = yaml.dump(
    {
        "http": {
            "routers": {
                "juju-foo-router": {
                    "entryPoints": ["web"],
                    "rule": "PathPrefix(`/path`)",
                    "service": "juju-foo-service",
                }
            },
            "services": {
                "juju-foo-service": {
                    "loadBalancer": {
                        "servers": [{"url": "http://foo.testmodel-endpoints.local:8080"}]
                    }
                }
            },
        }
    }
)


@pytest.fixture
def fake_fs(fs):
    fs.add_real_directory(pathlib.Path(__file__).parent.parent.parent)
    fs.create_dir("/tmp/pytest-of-dylan")
    yield fs


@pytest.fixture
def traefik_charm():
    with charm_tracing_disabled():
        with patch("lightkube.core.client.GenericSyncClient"):
            with patch(
                "charm.TraefikIngressCharm._get_loadbalancer_status",
                new_callable=PropertyMock,
                return_value=MOCK_LB_ADDRESS,
            ):
                yield TraefikIngressCharm


@pytest.fixture
def traefik_ctx(traefik_charm):
    return Context(charm_type=traefik_charm)


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

    opt = Mount("/opt/", tmp_path)
    etc_traefik = Mount("/etc/traefik/", tmp_path)

    return Container(
        name="traefik",
        can_connect=True,
        layers={"traefik": layer},
        exec_mock={
            ("update-ca-certificates", "--fresh"): ExecOutput(),
            ("find", "/opt/traefik/juju", "-name", "*.yaml", "-delete"): ExecOutput(),
            ("/usr/bin/traefik", "version"): ExecOutput(stdout="42.42"),
        },
        service_status={"traefik": pebble.ServiceStatus.ACTIVE},
        mounts={"opt": opt, "/etc/traefik": etc_traefik},
    )


@pytest.fixture
def tr_rel():
    return Relation(
        endpoint="traefik-route",
        remote_app_name="route-requirer",
        remote_app_data={"config": ROUTE_CONFIG},
        local_app_data={"external_host": "10.0.0.1", "scheme": "http"},
    )


@pytest.fixture
def tr_state(tr_rel, traefik_container):
    return State(
        leader=True,
        config={"external_hostname": "testhostname", "routing_mode": "path"},
        relations=[tr_rel],
        containers=[traefik_container],
    )
