import io
import tarfile
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

    return Container(
        name="traefik",
        can_connect=True,
        layers={"traefik": layer},
        exec_mock={
            ("/usr/bin/traefik", "version"): ExecOutput(stdout="42.42"),
            (
                "tar",
                "-xzf",
                f"{DYNAMIC_CONFIG_DIR}/_ingress_configs.tar.gz",
                "-C",
                DYNAMIC_CONFIG_DIR,
            ): ExecOutput(return_code=0),
        },
        service_status={"traefik": pebble.ServiceStatus.ACTIVE},
        mounts={"opt": opt, "/etc/traefik": etc_traefik},
    )


@pytest.fixture(autouse=True)
def _simulate_tar_extraction_in_scenario(monkeypatch, tmp_path):
    """Patch flush_dynamic_configs so tar extraction works with scenario Mounts.

    In scenario tests ``container.exec`` is mocked and does not actually run
    ``tar``.  This fixture wraps the method to extract individual YAML files
    from the in-memory archive into the mounted filesystem.
    """
    original_flush = Traefik.flush_dynamic_configs

    def _patched_flush(self):
        original_flush(self)
        # The original method builds the archive from self._dynamic_configs.
        # Replay the same build and extract directly to the mount path.
        target_dir = tmp_path / "traefik" / "juju"
        if self._dynamic_configs and target_dir.is_dir():
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for key, config in self._dynamic_configs.items():
                    yaml_bytes = yaml.safe_dump(config).encode("utf-8")
                    info = tarfile.TarInfo(name=f"{key}.yaml")
                    info.size = len(yaml_bytes)
                    tar.addfile(info, io.BytesIO(yaml_bytes))
            buf.seek(0)
            with tarfile.open(fileobj=buf, mode="r:gz") as tar:
                tar.extractall(path=str(target_dir))  # noqa: S202

    monkeypatch.setattr(Traefik, "flush_dynamic_configs", _patched_flush)


@pytest.fixture(autouse=True)
def mock_lightkube_client():
    """Global mock for the Lightkube Client to avoid loading kubeconfig in CI."""
    with patch.object(Client, "__init__", lambda self, *args, **kwargs: None):
        with patch.object(Client, "_client", create=True):
            with patch.object(Client, "get"):
                with patch.object(Client, "patch"):
                    with patch.object(Client, "list"):
                        yield
