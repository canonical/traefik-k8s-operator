from unittest.mock import PropertyMock, patch

import pytest
from ops import pebble
from scenario import Container, Context, Exec, Model, Mount

from charm import TraefikIngressCharm

MOCK_EXTERNAL_HOSTNAME = "testhostname"


@pytest.fixture
def traefik_charm():
    with patch("charm.KubernetesServicePatch"):
        with patch("lightkube.core.client.GenericSyncClient"):
            with patch(
                "charm.TraefikIngressCharm._external_host",
                PropertyMock(return_value=MOCK_EXTERNAL_HOSTNAME),
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

    opt = Mount(location="/opt/", source=tmp_path)

    return Container(
        name="traefik",
        can_connect=True,
        layers={"traefik": layer},
        execs={
            Exec(command_prefix=("update-ca-certificates", "--fresh")),
            Exec(command_prefix=("find", "/opt/traefik/juju", "-name", "*.yaml", "-delete")),
            Exec(command_prefix=("/usr/bin/traefik", "version"), stdout="42.42"),
        },
        service_statuses={"traefik": pebble.ServiceStatus.ACTIVE},
        mounts={"opt": opt},
    )
