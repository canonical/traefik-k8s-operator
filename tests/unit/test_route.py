# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Helpers for unit testing charms which use this library."""
from unittest.mock import Mock, patch

import pytest
import yaml
from charm import TraefikIngressCharm
from ops.testing import Harness

MODEL_NAME = "test-model"
REMOTE_APP_NAME = "traefikRouteApp"
REMOTE_UNIT_NAME = REMOTE_APP_NAME + "/0"
TR_RELATION_NAME = "traefik-route"

CONFIG = {
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
                "loadBalancer": {"servers": [{"url": "http://foo.testmodel-endpoints.local:8080"}]}
            }
        },
    }
}

CONFIG_WITH_TLS = {
    "http": {
        "routers": {
            "juju-foo-router": {
                "entryPoints": ["web"],
                "rule": "PathPrefix(`/path`)",
                "service": "juju-foo-service",
            },
            "juju-foo-router-tls": {
                "entryPoints": ["websecure"],
                "rule": "PathPrefix(`/path`)",
                "service": "juju-foo-service",
                "tls": {
                    "domains": [
                        {
                            "main": "testhostname",
                            "sans": ["*.testhostname"],
                        },
                    ],
                },
            },
        },
        "services": {
            "juju-foo-service": {
                "loadBalancer": {"servers": [{"url": "http://foo.testmodel-endpoints.local:8080"}]}
            }
        },
    }
}


@pytest.fixture
def harness() -> Harness[TraefikIngressCharm]:
    harness = Harness(TraefikIngressCharm)
    harness.set_model_name(MODEL_NAME)
    harness.handle_exec("traefik", ["update-ca-certificates", "--fresh"], result=0)

    patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
    patcher.start()

    yield harness
    harness.cleanup()


@patch("charm.KubernetesServicePatch", lambda *_, **__: None)
def initialize_and_setup_tr_relation(harness):
    harness.update_config({"external_hostname": "testhostname"})
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    harness.container_pebble_ready("traefik")

    charm = harness.charm
    # reinitialize charm to get around harness not rerunning init on hooks
    charm.container = charm.unit.get_container("traefik")

    tr_relation_id = harness.add_relation(TR_RELATION_NAME, REMOTE_APP_NAME)
    harness.add_relation_unit(tr_relation_id, REMOTE_UNIT_NAME)
    return tr_relation_id, charm.model.get_relation(TR_RELATION_NAME)


def test_relation_initialization(harness: Harness[TraefikIngressCharm]):
    """Test round-trip bootstrap and relation with a consumer."""
    _, relation = initialize_and_setup_tr_relation(harness)
    assert relation is not None


def test_relation_not_ready(harness: Harness[TraefikIngressCharm]):
    _, relation = initialize_and_setup_tr_relation(harness)
    charm = harness.charm
    assert not charm.traefik_route.is_ready(relation)
    assert charm.traefik_route.get_config(relation) is None


def test_relation_ready(harness: Harness[TraefikIngressCharm]):
    tr_relation_id, relation = initialize_and_setup_tr_relation(harness)
    charm = harness.charm
    config = yaml.dump(CONFIG)
    harness.update_relation_data(tr_relation_id, REMOTE_APP_NAME, {"config": config})

    assert charm.traefik_route.is_ready(relation)
    assert charm.traefik_route.get_config(relation) == config


def test_tr_ready_handler_called(harness: Harness[TraefikIngressCharm]):
    tr_relation_id, relation = initialize_and_setup_tr_relation(harness)
    charm = harness.charm
    charm._handle_traefik_route_ready = mocked_handle = Mock(return_value=None)

    config = yaml.dump(CONFIG)
    harness.update_relation_data(tr_relation_id, REMOTE_APP_NAME, {"config": config})

    assert charm.traefik_route.is_ready(relation)
    assert charm.traefik_route.get_config(relation) == config

    assert mocked_handle.called


def test_tls_is_added(harness: Harness[TraefikIngressCharm]):
    tr_relation_id, relation = initialize_and_setup_tr_relation(harness)
    charm = harness.charm
    config = yaml.dump(CONFIG)
    harness.update_relation_data(tr_relation_id, REMOTE_APP_NAME, {"config": config})

    assert charm.traefik_route.is_ready(relation)
    assert charm.traefik_route.get_config(relation) == config
    file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
    conf = yaml.safe_load(charm.container.pull(file).read())
    assert conf == CONFIG_WITH_TLS
