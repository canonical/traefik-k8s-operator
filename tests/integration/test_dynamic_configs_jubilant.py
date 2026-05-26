#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test: verify dynamic config files are written to the workload container.

Deploys traefik with 2+ apps integrated via ingress, then checks that the expected
dynamic config YAML files exist in /opt/traefik/juju/ inside the traefik container.
"""

import logging
import os
from pathlib import Path

import jubilant
import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in METADATA["resources"].items()
}

TRAEFIK_APP_NAME = "traefik"
ALERTMANAGER_APP_NAME = "alertmanager"
GRAFANA_APP_NAME = "grafana"
DYNAMIC_CONFIG_DIR = "/opt/traefik/juju"


@pytest.fixture(scope="module")
def juju():
    with jubilant.temp_model() as juju:
        juju.wait_timeout = 10 * 60
        yield juju


@pytest.fixture(scope="module")
def traefik_charm():
    charm_path = os.environ.get("CHARM_PATH")
    if charm_path:
        return Path(charm_path)
    charms = sorted(Path(".").glob("traefik*.charm"))
    if charms:
        return charms[0]
    raise FileNotFoundError(
        "Set CHARM_PATH to the built traefik charm, "
        "or place a traefik*.charm file in the repo root."
    )


@pytest.fixture(scope="module")
def deploy_traefik(juju, traefik_charm):
    """Deploy traefik."""
    juju.deploy(
        traefik_charm,
        TRAEFIK_APP_NAME,
        resources=TRAEFIK_RESOURCES,
        trust=True,
    )
    juju.config(TRAEFIK_APP_NAME, {"external_hostname": "traefik.test"})
    juju.wait(jubilant.all_active, timeout=600)
    return TRAEFIK_APP_NAME


@pytest.fixture(scope="module")
def deploy_alertmanager(juju, deploy_traefik):
    """Deploy alertmanager and integrate with traefik."""
    juju.deploy(
        "ch:alertmanager-k8s",
        ALERTMANAGER_APP_NAME,
        channel="2/edge",
        trust=True,
    )
    juju.wait(jubilant.all_active, timeout=600)
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(jubilant.all_active, timeout=600)
    return ALERTMANAGER_APP_NAME


@pytest.fixture(scope="module")
def deploy_grafana(juju, deploy_traefik):
    """Deploy grafana and integrate with traefik."""
    juju.deploy(
        "ch:grafana-k8s",
        GRAFANA_APP_NAME,
        channel="1/edge",
        trust=True,
    )
    juju.wait(jubilant.all_active, timeout=600)
    juju.integrate(f"{GRAFANA_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(jubilant.all_active, timeout=600)
    return GRAFANA_APP_NAME


def _list_dynamic_configs(juju):
    """List YAML files in the dynamic config directory."""
    output = juju.ssh(
        f"{TRAEFIK_APP_NAME}/0",
        f"ls {DYNAMIC_CONFIG_DIR}/",
        container="traefik",
    )
    return [f for f in output.strip().split("\n") if f.endswith(".yaml")]


def test_dynamic_configs_present(juju, deploy_traefik, deploy_alertmanager, deploy_grafana):
    """After integrating 2 apps, verify dynamic config files exist in the container."""
    files = _list_dynamic_configs(juju)
    logger.info("Dynamic config files in container: %s", files)

    # Each integrated app should have a config file matching juju_ingress_ingress_*_{app}.yaml
    alertmanager_configs = [f for f in files if ALERTMANAGER_APP_NAME in f]
    grafana_configs = [f for f in files if GRAFANA_APP_NAME in f]

    assert len(alertmanager_configs) == 1, (
        f"Expected exactly 1 config for {ALERTMANAGER_APP_NAME}, "
        f"found {alertmanager_configs} in {files}"
    )
    assert len(grafana_configs) == 1, (
        f"Expected exactly 1 config for {GRAFANA_APP_NAME}, "
        f"found {grafana_configs} in {files}"
    )

    # Verify naming convention: juju_ingress_{relation_name}_{relation_id}_{app_name}.yaml
    for f in alertmanager_configs + grafana_configs:
        assert f.startswith("juju_ingress_ingress_"), (
            f"Config file {f} doesn't follow expected naming convention"
        )


def test_dynamic_config_content_valid(juju, deploy_traefik, deploy_alertmanager, deploy_grafana):
    """Verify that the dynamic config files contain valid traefik routing config."""
    files = _list_dynamic_configs(juju)

    for app_name in (ALERTMANAGER_APP_NAME, GRAFANA_APP_NAME):
        config_file = next(f for f in files if app_name in f)
        output = juju.ssh(
            f"{TRAEFIK_APP_NAME}/0",
            f"cat {DYNAMIC_CONFIG_DIR}/{config_file}",
            container="traefik",
        )
        config = yaml.safe_load(output)
        logger.info("Config for %s: %s", app_name, config)

        # Every dynamic config should have http.routers and http.services
        assert "http" in config, f"No 'http' key in config for {app_name}"
        http = config["http"]
        assert "routers" in http, f"No routers in config for {app_name}"
        assert "services" in http, f"No services in config for {app_name}"

        # There should be at least one router and one service
        assert len(http["routers"]) >= 1, f"No routers defined for {app_name}"
        assert len(http["services"]) >= 1, f"No services defined for {app_name}"


def test_dynamic_config_removed_after_relation_removed(
    juju, deploy_traefik, deploy_alertmanager, deploy_grafana
):
    """After removing a relation, the corresponding config file should be cleaned up."""
    # Verify file exists before removal
    files_before = _list_dynamic_configs(juju)
    alertmanager_configs = [f for f in files_before if ALERTMANAGER_APP_NAME in f]
    assert len(alertmanager_configs) == 1

    # Remove the alertmanager relation
    juju.remove_relation(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(jubilant.all_active, timeout=300)

    # Verify the alertmanager config file is gone
    files_after = _list_dynamic_configs(juju)
    alertmanager_configs_after = [f for f in files_after if ALERTMANAGER_APP_NAME in f]
    assert len(alertmanager_configs_after) == 0, (
        f"Expected alertmanager config to be removed after relation broken, "
        f"but found: {alertmanager_configs_after}"
    )

    # Grafana config should still be present
    grafana_configs_after = [f for f in files_after if GRAFANA_APP_NAME in f]
    assert len(grafana_configs_after) == 1, (
        f"Grafana config should still exist, but found: {grafana_configs_after}"
    )
