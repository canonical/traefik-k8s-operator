from unittest.mock import patch

import pytest
from ops import pebble
from scenario import Container, Context, ExecOutput, Model, Mount

from charm import TraefikIngressCharm

MOCK_LB_ADDRESS = "1.2.3.4"


@pytest.fixture
def traefik_charm():
    with patch("charm.KubernetesLoadBalancer"):
        with patch("lightkube.core.client.GenericSyncClient"):
            with patch(
                "charm._get_loadbalancer_status",
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
