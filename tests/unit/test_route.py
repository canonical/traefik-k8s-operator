# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Helpers for unit testing charms which use this library."""
import uuid
from unittest.mock import Mock, patch

import ops
import pytest
import yaml
from cosl import JujuTopology
from ops.testing import Harness

from charm import TraefikIngressCharm
from traefik import StaticConfigMergeConflictError, Traefik

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

TCP_CONFIG_WITH_PASSTHROUGH = {
    "tcp": {
        "routers": {
            "juju-foo-router": {
                "entryPoints": ["websecure"],
                "rule": "HostSNI(`*`)",
                "service": "juju-foo-service",
                "tls": {"passthrough": True},  # Passthrough enabled
            }
        },
        "services": {
            "juju-foo-service": {
                "loadBalancer": {"servers": [{"address": "foo.testmodel-endpoints.local:8080"}]}
            }
        },
    }
}

HTTP_CONFIG_WITH_PASSTHROUGH = {
    "http": {
        "routers": {
            "juju-foo-router": {
                "entryPoints": ["web"],
                "rule": "PathPrefix(`/path`)",
                "service": "juju-foo-service",
                "tls": {"passthrough": True},  # Passthrough enabled
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


@pytest.fixture(scope="function")
def harness() -> Harness[TraefikIngressCharm]:
    harness = Harness(TraefikIngressCharm)
    harness.set_model_name(MODEL_NAME)
    harness.handle_exec("traefik", ["update-ca-certificates", "--fresh"], result=0)
    harness.handle_exec(
        "traefik", ["find", "/opt/traefik/juju", "-name", "*.yaml", "-delete"], result=0
    )

    patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
    patcher.start()

    yield harness
    harness.cleanup()


@pytest.fixture(scope="function")
def topology(harness):
    topology = JujuTopology(
        model="model",
        model_uuid=str(uuid.uuid4()),
        application="app",
        charm_name="charm",
    )
    return topology


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


def test_static_config(harness: Harness[TraefikIngressCharm], topology: JujuTopology):
    tr_relation_id, relation = initialize_and_setup_tr_relation(harness)
    config = yaml.dump(CONFIG)
    static = yaml.safe_dump({"foo": "bar"})

    with harness.hooks_disabled():
        # don't emit yet: we need to reinitialize Traefik first.
        harness.update_relation_data(
            tr_relation_id,
            REMOTE_APP_NAME,
            {
                "config": config,
                "static": static,
            },
        )

    # reinitialize Traefik, else _traefik_route_static_configs won't be passed to Traefik on init.
    charm = harness.charm
    charm.traefik = Traefik(
        container=charm.container,
        routing_mode=charm._routing_mode,
        tcp_entrypoints=charm._tcp_entrypoints(),
        tls_enabled=charm._is_tls_enabled(),
        experimental_forward_auth_enabled=charm._is_forward_auth_enabled,
        traefik_route_static_configs=charm._traefik_route_static_configs(),
        topology=topology,
    )

    charm.traefik_route.on.ready.emit(charm.model.get_relation("traefik-route"))

    assert charm.traefik._traefik_route_static_configs == [{"foo": "bar"}]
    assert charm.traefik_route.is_ready(relation)

    # verify the static config is there
    assert charm.traefik_route.get_static_config(relation) == static
    file = "/etc/traefik/traefik.yaml"
    conf = yaml.safe_load(charm.container.pull(file).read())
    assert conf["foo"] == "bar"

    # verify the dynamic config is there too
    file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
    assert yaml.safe_load(charm.container.pull(file).read()) == CONFIG_WITH_TLS


def test_static_config_broken(harness: Harness[TraefikIngressCharm], topology: JujuTopology):
    tr_relation_id, relation = initialize_and_setup_tr_relation(harness)
    config = yaml.dump(CONFIG)

    # IF a remote sends invalid static data via traefik-route

    # the base config already has a log: level: DEBUG config.
    # this should cause a merge error
    static = yaml.safe_dump({"log": {"level": "ERROR"}})

    with harness.hooks_disabled():
        # don't emit yet: we need to reinitialize Traefik first.
        harness.update_relation_data(
            tr_relation_id,
            REMOTE_APP_NAME,
            {
                "config": config,
                "static": static,
            },
        )

    # reinitialize Traefik, else _traefik_route_static_configs won't be passed to Traefik on init.
    charm = harness.charm
    charm.traefik = Traefik(
        container=charm.container,
        routing_mode=charm._routing_mode,
        tcp_entrypoints=charm._tcp_entrypoints(),
        tls_enabled=charm._is_tls_enabled(),
        experimental_forward_auth_enabled=charm._is_forward_auth_enabled,
        traefik_route_static_configs=charm._traefik_route_static_configs(),
        topology=topology,
    )

    # WHEN the charm receives a traefik-route ready event
    charm.traefik_route.on.ready.emit(charm.model.get_relation("traefik-route"))
    with pytest.raises(StaticConfigMergeConflictError):
        charm.traefik.generate_static_config(_raise=True)

    # THEN the charm status is blocked
    assert isinstance(charm.unit.status, ops.BlockedStatus)
    charm.on.update_status.emit()
    assert isinstance(charm.unit.status, ops.ActiveStatus)

    # THEN the static config has NOT been updated
    file = "/etc/traefik/traefik.yaml"
    conf = yaml.safe_load(charm.container.pull(file).read())
    assert conf["log"] == {"level": "DEBUG"}

    # THEN  the dynamic config is there too
    file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
    assert yaml.safe_load(charm.container.pull(file).read()) == CONFIG_WITH_TLS


def test_static_config_partially_broken(
    harness: Harness[TraefikIngressCharm], topology: JujuTopology
):
    initialize_and_setup_tr_relation(harness)

    # IF we initialize Traefik with some specially crafted
    # _traefik_route_static_configs
    charm = harness.charm
    charm.traefik = Traefik(
        container=charm.container,
        routing_mode=charm._routing_mode,
        tcp_entrypoints=charm._tcp_entrypoints(),
        tls_enabled=charm._is_tls_enabled(),
        experimental_forward_auth_enabled=charm._is_forward_auth_enabled,
        traefik_route_static_configs=[
            # GOOD: this config won't conflict with any other
            {"barbaras": {"rhabarber": "bar"}},
            # BAD: this will conflict with traefik's baseline static config
            {"log": {"level": "ERROR"}},
            # GOOD: this config won't conflict with any other
            {"foo": {"bar": "baz"}},
            # GOOD: this one won't conflict with other entrypoints
            {"entryPoints": {"shondaland": {"address": ":6767"}}},
        ],
        topology=topology,
    )

    # WHEN the charm receives a traefik-route ready event
    charm.traefik_route.on.ready.emit(charm.model.get_relation("traefik-route"))

    # THEN Traefik can detect that there is something wrong with the config
    with pytest.raises(StaticConfigMergeConflictError):
        charm.traefik.generate_static_config(_raise=True)

    # BUT Traefik can still generate a static config
    generated_config = charm.traefik.generate_static_config()

    # AND the conflicting config has NOT been updated
    assert generated_config["log"] == {"level": "DEBUG"}
    # BUT the non-conflicting ones have.
    assert generated_config["barbaras"] == {"rhabarber": "bar"}
    assert generated_config["entryPoints"]["shondaland"]["address"] == ":6767"
    assert generated_config["foo"] == {"bar": "baz"}


def test_static_config_updates_tcp_entrypoints(
    harness: Harness[TraefikIngressCharm], topology: JujuTopology
):
    tr_relation_id, relation = initialize_and_setup_tr_relation(harness)
    config = yaml.dump(CONFIG)
    static = yaml.safe_dump({"entryPoints": {"shondaland": {"address": ":6767"}}})

    with harness.hooks_disabled():
        # don't emit yet: we need to reinitialize Traefik first.
        harness.update_relation_data(
            tr_relation_id,
            REMOTE_APP_NAME,
            {
                "config": config,
                "static": static,
            },
        )

    # reinitialize Traefik, else _traefik_route_static_configs won't be passed to Traefik on init.
    charm = harness.charm
    charm.traefik = Traefik(
        container=charm.container,
        routing_mode=charm._routing_mode,
        tcp_entrypoints=charm._tcp_entrypoints(),
        tls_enabled=charm._is_tls_enabled(),
        experimental_forward_auth_enabled=charm._is_forward_auth_enabled,
        traefik_route_static_configs=charm._traefik_route_static_configs(),
        topology=topology,
    )

    charm.traefik_route.on.ready.emit(charm.model.get_relation("traefik-route"))

    # THEN Traefik can list the provided entrypoints
    tcp_entrypoints = charm._tcp_entrypoints()
    assert tcp_entrypoints["shondaland"] == "6767"

    # AND that shows up in the service ports
    assert [p for p in charm._service_ports if p.port == 6767][0]


def test_tls_http_passthrough_no_tls_added(harness: Harness[TraefikIngressCharm]):
    """Ensure no TLS configuration is generated for routes with tls.passthrough."""
    tr_relation_id, relation = initialize_and_setup_tr_relation(harness)
    charm = harness.charm

    # Update relation with the passthrough configuration
    config = yaml.dump(HTTP_CONFIG_WITH_PASSTHROUGH)
    harness.update_relation_data(tr_relation_id, REMOTE_APP_NAME, {"config": config})

    # Verify the relation is ready and the configuration is loaded
    assert charm.traefik_route.is_ready(relation)
    assert charm.traefik_route.get_config(relation) == config

    # Check the dynamic configuration written to the container
    file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
    dynamic_config = yaml.safe_load(charm.container.pull(file).read())

    # Ensure the passthrough configuration is preserved
    assert dynamic_config == HTTP_CONFIG_WITH_PASSTHROUGH

    # Check no additional TLS configurations are added
    assert "juju-foo-router-tls" not in dynamic_config["http"]["routers"]


def test_tls_tcp_passthrough_no_tls_added(harness: Harness[TraefikIngressCharm]):
    """Ensure no TLS configuration is generated for routes with tls.passthrough."""
    tr_relation_id, relation = initialize_and_setup_tr_relation(harness)
    charm = harness.charm

    # Update relation with the passthrough configuration
    config = yaml.dump(TCP_CONFIG_WITH_PASSTHROUGH)
    harness.update_relation_data(tr_relation_id, REMOTE_APP_NAME, {"config": config})

    # Verify the relation is ready and the configuration is loaded
    assert charm.traefik_route.is_ready(relation)
    assert charm.traefik_route.get_config(relation) == config

    # Check the dynamic configuration written to the container
    file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
    dynamic_config = yaml.safe_load(charm.container.pull(file).read())

    # Ensure the passthrough configuration is preserved
    assert dynamic_config == TCP_CONFIG_WITH_PASSTHROUGH

    # Check no additional TLS configurations are added
    assert "juju-foo-router-tls" not in dynamic_config["tcp"]["routers"]
