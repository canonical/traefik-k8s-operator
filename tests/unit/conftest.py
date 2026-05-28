from unittest.mock import PropertyMock, patch

import pytest
import yaml
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from lightkube import Client
from ops import pebble
from scenario import Container, Context, ExecOutput, Model, Mount

from charm import TraefikIngressCharm
from traefik import DYNAMIC_CONFIG_DIR, Traefik

MOCK_LB_ADDRESS = "1.2.3.4"


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

    # Simulate the system CA bundle that's always present in the container image.
    ssl_certs_dir = tmp_path / "ssl_certs"
    ssl_certs_dir.mkdir()
    (ssl_certs_dir / "ca-certificates.crt").write_text("# system CA bundle\n")
    etc_ssl_certs = Mount("/etc/ssl/certs/", ssl_certs_dir)

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
        mounts={"opt": opt, "/etc/traefik": etc_traefik, "/etc/ssl/certs": etc_ssl_certs},
    )


@pytest.fixture(autouse=True)
def mock_lightkube_client():
    """Global mock for the Lightkube Client to avoid loading kubeconfig in CI."""
    with patch.object(Client, "__init__", lambda self, *args, **kwargs: None):
        with patch.object(Client, "_client", create=True):
            with patch.object(Client, "get"):
                with patch.object(Client, "patch"):
                    with patch.object(Client, "list"):
                        yield


@pytest.fixture(autouse=True)
def _mock_flush_dynamic_configs(monkeypatch):
    """Mock flush_dynamic_configs to push files individually.

    In production, flush_dynamic_configs uses a tar archive for efficiency.
    In tests, we simply push each file via container.push() so the test
    filesystem reflects the written configs.
    """

    def mock_flush(self):
        for key, config in self._dynamic_configs.items():
            self._container.push(
                f"{DYNAMIC_CONFIG_DIR}/{key}.yaml",
                yaml.safe_dump(config),
                make_dirs=True,
            )

    monkeypatch.setattr(Traefik, "flush_dynamic_configs", mock_flush)
